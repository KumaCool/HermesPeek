from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .lifecycle import HermesTarget, InstallPaths, LifecycleError, read_bot_token
from .telegram_lifecycle import TelegramLifecycle, UrllibTelegramTransport
from .service_backend import HealthProbe, PortProbe, Runner, SystemdUserBackend, _health_probe, _port_probe

Probe = Callable[[], dict[str, Any]]
HttpsProbe = Callable[[str], dict[str, Any]]


def setup_plan(paths: InstallPaths, *, allowed_roots: list[Path], external_url: str,
               activate: bool) -> dict[str, Any]:
    """Describe setup without reading secrets, running commands, or writing files."""
    roots = [str(root.expanduser().resolve()) for root in allowed_roots]
    actions = [
        {"action": "write_shared_config", "path": str(paths.config_file), "allowed_roots": roots,
         "external_url": external_url},
        {"action": "write_secret_file", "path": str(paths.env_file), "values": ["TELEGRAM_BOT_TOKEN"]},
        {"action": "install_plugin", "path": str(paths.plugin_dir)},
        {"action": "write_service_unit", "path": str(paths.unit_file)},
        {"action": "write_manifest", "path": str(paths.manifest_file)},
    ]
    if activate:
        actions.extend((
            {"action": "enable_plugin", "target": str(paths.hermes_home)},
            {"action": "restart_gateway", "target": str(paths.hermes_home)},
            {"action": "start_service", "unit": paths.unit_file.name},
        ))
    return {
        "schema_version": 1,
        "dry_run": True,
        "target": {"hermes_home": str(paths.hermes_home)},
        "actions": actions,
        "rollback_points": ["filesystem_snapshot", "plugin_state", "gateway_state", "service_state"],
    }


def _command_json(runner: Runner, command: tuple[str, ...]) -> dict[str, Any]:
    result = runner(command)
    if result.returncode:
        return {}
    try:
        value = json.loads(result.stdout or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _telegram_probe(paths: InstallPaths) -> dict[str, Any]:
    try:
        result = TelegramLifecycle(UrllibTelegramTransport()).inspect(read_bot_token(paths.env_file))
        return {"verified": True, **result}
    except LifecycleError:
        return {"verified": False, "main_mini_app_requires_botfather": True}


def _https_probe(url: str) -> dict[str, Any]:
    if not url:
        return {"reachable": False, "status": None, "configured": False}
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=3) as response:
            return {"reachable": 200 <= response.status < 500, "status": response.status, "configured": True}
    except (OSError, urllib.error.URLError):
        return {"reachable": False, "status": None, "configured": True}


def status(paths: InstallPaths, runner: Runner, *, port_probe: PortProbe = _port_probe,
           health_probe: HealthProbe = _health_probe, https_probe: HttpsProbe | None = None,
           telegram_probe: Probe | None = None) -> dict[str, Any]:
    manifest = None
    if paths.manifest_file.is_file():
        try:
            value = json.loads(paths.manifest_file.read_text(encoding="utf-8"))
            manifest = value if isinstance(value, dict) else None
        except (OSError, ValueError):
            pass
    config: dict[str, Any] = {}
    if paths.config_file.is_file():
        try:
            value = json.loads(paths.config_file.read_text(encoding="utf-8"))
            config = value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            pass
    target = HermesTarget.from_paths(paths)
    backend = SystemdUserBackend(runner, port_probe=port_probe, health_probe=health_probe)
    service = backend.inspect()
    plugin_state = _command_json(runner, target.command("plugins", "status", "hermes-peek"))
    gateway = _command_json(runner, target.command("gateway", "status"))
    drifted: list[str] = []
    if manifest:
        if manifest.get("target", {}).get("identity") not in (None, target.identity):
            drifted.append("target")
        for entry in manifest.get("owned_resources", []):
            resource = Path(str(entry.get("path", "")))
            if resource.is_symlink() or not resource.is_file():
                drifted.append("owned_resource")
            elif hashlib.sha256(resource.read_bytes()).hexdigest() != entry.get("sha256"):
                drifted.append("owned_resource")
    external = str(config.get("external_base_url") or "")
    return {
        "schema_version": 1,
        "target": {"hermes_home": str(paths.hermes_home), "identity": target.identity},
        "manifest": {"present": manifest is not None, "schema_version": manifest.get("schema_version") if manifest else None},
        "transaction": {"id": manifest.get("transaction_id") if manifest else None, "state": "committed" if manifest else None},
        "service": service,
        "plugin": {"installed": paths.plugin_dir.is_dir(), "enabled": bool(plugin_state.get("enabled")), "loaded": bool(plugin_state.get("loaded"))},
        "gateway": {"active": bool(gateway.get("active"))},
        "telegram": telegram_probe() if telegram_probe else _telegram_probe(paths),
        "https": https_probe(external) if https_probe else _https_probe(external),
        "drift": {"detected": bool(drifted), "categories": sorted(set(drifted))},
        "data": {"state_directory_present": paths.state_dir.is_dir(), "bytes": _directory_size(paths.state_dir)},
    }


def _directory_size(root: Path) -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    return sum(item.stat().st_size for item in root.rglob("*") if item.is_file() and not item.is_symlink())


def doctor(paths: InstallPaths, runner: Runner, **probes: Any) -> dict[str, Any]:
    report = status(paths, runner, **probes)
    checks = [
        {"name": "manifest", "ok": report["manifest"]["present"], "suggestion": "run setup to create a committed manifest"},
        {"name": "service_health", "ok": bool(report["service"]["health"].get("ok")), "suggestion": "inspect service logs and restart the managed service"},
        {"name": "plugin_loaded", "ok": report["plugin"]["loaded"], "suggestion": "enable the plugin for the selected Hermes target"},
        {"name": "gateway", "ok": report["gateway"]["active"], "suggestion": "inspect the selected Gateway status"},
        {"name": "telegram", "ok": bool(report["telegram"].get("verified")), "suggestion": "verify the Bot token and BotFather prerequisites"},
        {"name": "https", "ok": bool(report["https"].get("reachable")), "suggestion": "verify the configured external HTTPS origin"},
        {"name": "config_drift", "ok": not report["drift"]["detected"], "suggestion": "review modified installer-owned resources before repair"},
    ]
    return {"schema_version": 1, "checks": checks,
            "suggestions": [check["suggestion"] for check in checks if not check["ok"]]}
