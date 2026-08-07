from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import hashlib
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

import uvicorn
from pydantic import ValidationError

from hermes_peek import __version__
from hermes_peek.app import create_app

from hermes_peek.config import Settings
from hermes_peek.lifecycle import (
    InstallPaths,
    LifecycleError,
    install as install_application,
    plan_purge,
    purge as purge_application,
    read_bot_token,
    rollback_transaction,
    uninstall as uninstall_application,
)
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import (
    CorruptPreviewError,
    PreviewNotFoundError,
    PreviewRegistry,
)
from hermes_peek.service import PreviewService, PublishError
from hermes_peek.lifecycle_ux import (
    _plugin_runtime_probe,
    doctor as lifecycle_doctor,
    setup_plan as lifecycle_setup_plan,
    status as lifecycle_status,
)
from hermes_peek.service_backend import SystemdUserBackend
from hermes_peek.setup_wizard import (
    discover_hermes_profiles,
    discover_installed_hermes_home,
    read_existing_setup,
    run_setup_wizard,
    select_hermes_profile,
    validate_allowed_roots,
    validate_https_origin,
    validate_secret_file,
)
from hermes_peek.telegram import TelegramClient, TelegramNotificationError
from hermes_peek.telegram_lifecycle import TelegramLifecycle


def telegram_transport():
    """Production uses httpx's default transport; tests inject MockTransport here."""
    return None


def telegram_lifecycle_transport():
    from hermes_peek.telegram_lifecycle import UrllibTelegramTransport
    return UrllibTelegramTransport()


def lifecycle_runner(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _paths_for_user(hermes_home: Path | None = None) -> InstallPaths:
    return InstallPaths.for_user(
        hermes_home=hermes_home or discover_installed_hermes_home() or Path.home() / ".hermes"
    )


def _resolve_lifecycle_home(requested: Path | None) -> Path:
    """Use the committed install target unless the operator explicitly selects the same target."""
    committed = discover_installed_hermes_home()
    if requested is None:
        return committed or (Path.home() / ".hermes").resolve()
    resolved = requested.expanduser().resolve()
    if committed is not None and resolved != committed:
        raise LifecycleError(
            "requested Hermes target does not match the installed target; "
            "omit --hermes-home to use the committed installation target"
        )
    return resolved


def _remove_uv_tool() -> tuple[bool, str]:
    """Refuse to remove a uv tool unless it owns the executable actually invoked."""
    uv = shutil.which("uv")
    if uv is None:
        return False, "uv 未找到，CLI 未删除"
    directory = subprocess.run([uv, "tool", "dir"], text=True, capture_output=True, check=False)
    if directory.returncode:
        return False, "无法确认 uv tool 所有权，CLI 未删除"
    candidate = Path(directory.stdout.strip()) / "hermes-peek/bin/hermes-peek"
    try:
        if candidate.resolve(strict=True) != resolve_current_executable():
            return False, "当前 CLI 不属于默认 uv tool，CLI 未删除"
    except OSError:
        return False, "无法确认 uv tool 所有权，CLI 未删除"
    return False, "默认 uv tool 安装不能安全地自删除；请执行 uv tool uninstall hermes-peek"


def _curl_install_paths() -> tuple[Path, Path, Path]:
    candidates = [
        Path(os.environ.get("HERMES_PEEK_INSTALL_ROOT", Path.home() / ".local/share/hermes-peek")),
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "hermes-peek",
    ]
    for candidate in candidates:
        metadata = candidate.expanduser() / "install-metadata.json"
        if not metadata.is_file() or metadata.is_symlink():
            continue
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
            root = Path(value["install_root"]).expanduser().resolve(strict=True)
            executable = Path(value["executable"]).expanduser().resolve(strict=True)
            command = Path(value["command_link"]).expanduser()
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
        return root, executable, command
    raise LifecycleError("curl installation ownership metadata is missing or invalid")


def _curl_tool_executable(root: Path) -> Path:
    return root / "hermes-peek/bin/hermes-peek"


def _remove_cli_installation() -> tuple[bool, str]:
    """Quarantine an owned curl install and remove it after this process exits."""
    try:
        root, executable, command = _curl_install_paths()
    except LifecycleError:
        return _remove_uv_tool()
    current = resolve_current_executable()
    approved_parent = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser().resolve()
    expected = _curl_tool_executable(root).resolve(strict=True)
    if root == Path("/") or root == Path.home().resolve() or root.parent != approved_parent:
        return False, "安装根目录未通过安全校验，CLI 未删除"
    if executable != expected or current != expected:
        return False, "安装元数据与当前 CLI 不一致，CLI 未删除"
    if not command.is_symlink() or command.resolve(strict=True) != expected:
        return False, "命令入口不属于当前 HermesPeek 安装，CLI 未删除"
    quarantine = root.with_name(f"{root.name}.remove-{os.getpid()}")
    if quarantine.exists():
        return False, "CLI 延迟删除目录已存在，CLI 未删除"
    command.unlink()
    os.replace(root, quarantine)
    helper = "while kill -0 \"$1\" 2>/dev/null; do sleep 0.1; done; rm -rf -- \"$2\""
    try:
        subprocess.Popen(["/bin/sh", "-c", helper, "hermes-peek-remove", str(os.getpid()), str(quarantine)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        os.replace(quarantine, root)
        command.symlink_to(expected)
        return False, "无法启动延迟删除助手，CLI 未删除"
    return True, "curl 安装的 CLI 将在当前命令退出后删除"


def _latest_release_version() -> str:
    request = urllib.request.Request(
        "https://api.github.com/repos/KumaCool/HermesPeek/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "hermes-peek"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            tag = json.load(response).get("tag_name", "")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise LifecycleError("could not query the latest HermesPeek release") from exc
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise LifecycleError("latest HermesPeek release metadata is invalid")
    return tag[1:]


def _version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise LifecycleError("release version must contain only dot-separated numbers") from exc


def _update_subprocess_error(phase: str, result: subprocess.CompletedProcess[str]) -> LifecycleError:
    """Preserve a bounded, single-line child error without leaking common Bot tokens."""
    detail = "\n".join(part for part in (result.stderr, result.stdout) if part).strip()
    detail = re.sub(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", detail)
    detail = " ".join(detail.split())[:1000]
    suffix = f": {detail}" if detail else f" (exit code {result.returncode})"
    return LifecycleError(f"updated integration {phase} failed{suffix}")


def _update_cli(
    target: str,
    *,
    apply: bool,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    report = progress or (lambda _phase: None)
    root, owned_executable, command_link = _curl_install_paths()
    current_executable = resolve_current_executable()
    if owned_executable != current_executable:
        raise LifecycleError("update is only supported from the owned curl installation")
    try:
        current_executable.relative_to(root)
    except ValueError as exc:
        raise LifecycleError("update is supported for curl-installed HermesPeek only") from exc
    if not apply:
        return {"current_version": __version__, "target_version": target,
                "update_available": _version_key(target) > _version_key(__version__),
                "changes": ["download and verify the fixed release wheel", "stage and atomically switch the curl CLI",
                            "reapply the committed integration", "run status and doctor", "roll back on failure"]}
    if command_link.exists() and not command_link.is_symlink():
        raise LifecycleError("refusing to replace a non-symlink hermes-peek command")
    report("downloading_update")
    asset = f"hermes_peek-{target}-py3-none-any.whl"
    base = f"https://github.com/KumaCool/HermesPeek/releases/download/v{target}"
    uv = shutil.which("uv")
    if uv is None:
        raise LifecycleError("uv is required to update HermesPeek")
    with tempfile.TemporaryDirectory(prefix="hermes-peek-update-") as temporary:
        directory = Path(temporary)
        try:
            urllib.request.urlretrieve(f"{base}/{asset}", directory / asset)
            urllib.request.urlretrieve(f"{base}/SHA256SUMS", directory / "SHA256SUMS")
        except (OSError, urllib.error.URLError) as exc:
            raise LifecycleError("failed to download the requested HermesPeek release") from exc
        expected = None
        for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].lstrip("*") == asset:
                expected = fields[0]
        actual = hashlib.sha256((directory / asset).read_bytes()).hexdigest()
        if expected is None or expected != actual:
            raise LifecycleError("release checksum verification failed")
        report("staging_update")
        env = os.environ.copy()
        stage = directory / "tool"
        env.update(UV_TOOL_DIR=str(stage), UV_TOOL_BIN_DIR=str(stage / "bin"))
        result = subprocess.run([uv, "tool", "install", "--force", str(directory / asset)],
                                text=True, capture_output=True, env=env, check=False)
        if result.returncode:
            raise LifecycleError("uv failed to stage the verified HermesPeek release")
        staged = _curl_tool_executable(stage)
        probe = subprocess.run([str(staged), "--version"], text=True, capture_output=True, check=False)
        if probe.returncode or probe.stdout.strip() != f"hermes-peek {target}":
            raise LifecycleError("staged HermesPeek version verification failed")
        backup = root.with_name(root.name + ".update-backup")
        shutil.rmtree(backup, ignore_errors=True)
        if root.exists():
            os.replace(root, backup)
        try:
            report("switching_update")
            final_env = os.environ.copy()
            final_env.update(UV_TOOL_DIR=str(root), UV_TOOL_BIN_DIR=str(root / "bin"))
            install = subprocess.run(
                [uv, "tool", "install", "--force", str(directory / asset)],
                text=True,
                capture_output=True,
                env=final_env,
                check=False,
            )
            if install.returncode:
                raise LifecycleError("uv failed to install the verified HermesPeek release at its final path")
            installed = _curl_tool_executable(root)
            final_probe = subprocess.run(
                [str(installed), "--version"], text=True, capture_output=True, check=False
            )
            if final_probe.returncode or final_probe.stdout.strip() != f"hermes-peek {target}":
                raise LifecycleError("installed HermesPeek version verification failed at final path")
            metadata = root / "install-metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "install_root": str(root),
                        "executable": str(installed),
                        "command_link": str(command_link),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            metadata.chmod(0o600)
            command_link.parent.mkdir(parents=True, exist_ok=True)
            temporary_link = command_link.with_name(command_link.name + ".new")
            temporary_link.unlink(missing_ok=True)
            temporary_link.symlink_to(installed)
            os.replace(temporary_link, command_link)
            report("reapplying_integration")
            setup = subprocess.run(
                [str(installed), "setup"],
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if setup.returncode:
                raise _update_subprocess_error("setup", setup)
            report("verifying_update")
            status = subprocess.run(
                [str(installed), "status"],
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if status.returncode:
                raise _update_subprocess_error("status verification", status)
            doctor = subprocess.run(
                [str(installed), "doctor"],
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if doctor.returncode:
                raise _update_subprocess_error("doctor verification", doctor)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            if backup.exists():
                os.replace(backup, root)
            if _curl_tool_executable(root).is_file():
                temporary_link = command_link.with_name(command_link.name + ".rollback")
                temporary_link.unlink(missing_ok=True)
                temporary_link.symlink_to(_curl_tool_executable(root))
                os.replace(temporary_link, command_link)
            raise
        shutil.rmtree(backup, ignore_errors=True)
    return {"updated": True, "from_version": __version__, "to_version": target,
            "integration_verified": True, "rollback_available_on_failure": True}


def _uninstall_message(result: dict[str, object], cli_status: str | None = None) -> str:
    lines = ["HermesPeek 卸载成功。", "- Hermes 集成：已删除"]
    lines.append("- HermesPeek 数据：已永久删除" if result.get("data_purged") or result.get("purged") else "- Preview 数据：已保留（使用 --purge 才会删除）")
    if cli_status:
        lines.append(f"- CLI：{cli_status}")
    if result.get("original_files_preserved") or result.get("state_preserved"):
        lines.append("- 原始项目文件：按安全策略保留")
    return "\n".join(lines)


def _human_label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _human_value(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None:
        return "Not available"
    return str(value)


def _human_lines(value: object, *, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            label = _human_label(str(key))
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{label}:")
                lines.extend(_human_lines(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}{label}: {_human_value(item)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_human_lines(item, indent=indent + 1))
            else:
                lines.append(f"{prefix}- {_human_value(item)}")
        return lines or [f"{prefix}(none)"]
    return [f"{prefix}{_human_value(value)}"]


def _format_update_result(result: dict[str, object]) -> str:
    current = result.get("current_version") or result.get("from_version")
    target = result.get("target_version") or result.get("to_version")
    if "update_available" in result:
        if result["update_available"]:
            lines = [f"HermesPeek update available: {current} → {target}"]
        else:
            lines = [f"HermesPeek is up to date ({current})."]
        changes = result.get("changes")
        if isinstance(changes, list) and changes:
            lines.append("Update actions:")
            lines.extend(f"  - {change}" for change in changes)
        return "\n".join(lines)
    return f"HermesPeek updated successfully: {current} → {target}\nIntegration verification: passed"


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_status(result: dict[str, object]) -> str:
    service = _mapping(result.get("service"))
    plugin = _mapping(result.get("plugin"))
    gateway = _mapping(result.get("gateway"))
    https = _mapping(result.get("https"))
    drift = _mapping(result.get("drift"))
    manifest = _mapping(result.get("manifest"))
    health = _mapping(service.get("health"))
    runtime = _mapping(plugin.get("runtime"))
    rows = [
        ("Manifest", bool(manifest.get("present"))),
        ("Service active", bool(service.get("active"))),
        ("Service enabled", bool(service.get("enabled"))),
        ("Service health", bool(health.get("ok"))),
        ("Plugin installed", bool(plugin.get("installed"))),
        ("Plugin enabled", bool(plugin.get("enabled"))),
        ("Plugin loaded", bool(plugin.get("loaded"))),
        ("Plugin runtime", bool(runtime.get("available"))),
        ("Hermes Gateway", bool(gateway.get("active"))),
        ("HTTPS origin", bool(https.get("reachable"))),
        ("Configuration drift", not bool(drift.get("detected"))),
    ]
    return "HermesPeek status\n" + "\n".join(
        f"  {'✓' if ok else '✗'} {label}" for label, ok in rows
    )


def _format_doctor(result: dict[str, object]) -> str:
    checks = result.get("checks") if isinstance(result.get("checks"), list) else []
    lines = ["HermesPeek diagnostics"]
    for check in checks:
        if not isinstance(check, dict):
            continue
        ok = bool(check.get("ok"))
        lines.append(f"  {'✓' if ok else '✗'} {_human_label(str(check.get('name', 'check')))}")
        if not ok and check.get("suggestion"):
            lines.append(f"    Suggestion: {check['suggestion']}")
    lines.append("All checks passed." if checks and all(bool(c.get("ok")) for c in checks if isinstance(c, dict))
                 else "One or more checks need attention.")
    return "\n".join(lines)


def _print_result(result: dict[str, object], *, kind: str) -> None:
    if kind == "update":
        print(_format_update_result(result))
    elif kind == "status":
        print(_format_status(result))
    elif kind == "doctor":
        print(_format_doctor(result))
    else:
        heading = {
            "publish": "Preview published",
            "inspect": "Preview details",
            "revoke": "Preview revoked",
            "rollback": "Rollback completed",
            "service": "Service command completed",
            "setup_plan": "HermesPeek setup plan (no changes made)",
            "purge_plan": "HermesPeek purge plan (no changes made)",
        }.get(kind, "HermesPeek result")
        print("\n".join([heading, *_human_lines(result, indent=1)]))


def setup_https_probe(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"reachable": 200 <= response.status < 500, "status": response.status}
    except (OSError, urllib.error.URLError):
        return {"reachable": False, "status": None}


def verify_external_https_health(origin: str) -> None:
    if not setup_https_probe(origin.rstrip("/") + "/healthz").get("reachable"):
        raise LifecycleError("external HTTPS origin is not reachable at /healthz after service startup")


def verify_installed_plugin_runtime(paths: InstallPaths) -> None:
    if not _plugin_runtime_probe(paths).get("available"):
        raise LifecycleError("installed Hermes Plugin cannot import its bundled runtime")


def resolve_current_executable() -> Path:
    invoked = Path(sys.argv[0]).expanduser()
    if invoked.parent != Path("."):
        if invoked.is_file() and os.access(invoked, os.X_OK):
            return invoked.resolve(strict=True)
        raise LifecycleError("invoked hermes-peek executable could not be resolved")
    discovered = shutil.which(sys.argv[0])
    if discovered is not None:
        return Path(discovered).resolve(strict=True)
    raise LifecycleError("hermes-peek executable could not be resolved")


def _running_inside_gateway_session() -> bool:
    """Avoid restarting the Gateway from a turn currently served by it."""
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        if "hermes-gateway.service" in cgroup:
            return True
    except OSError:
        pass
    try:
        import importlib
        get_session_env = importlib.import_module("gateway.session_context").get_session_env
        return bool(get_session_env("HERMES_SESSION_PLATFORM", "")) or bool(os.environ.get("HERMES_SESSION_PLATFORM"))
    except (ImportError, AttributeError, RuntimeError):
        return bool(os.environ.get("HERMES_SESSION_PLATFORM"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-peek")
    parser.add_argument("--version", action="version", version=f"hermes-peek {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish", help="Publish files as a preview")
    publish.add_argument("files", nargs="+", type=Path)
    publish.add_argument("--entry", required=True, type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--owner", required=True)
    publish.add_argument("--notify", action="store_true")
    publish.add_argument("--chat-id")
    publish.add_argument("--thread-id", type=int)
    publish.add_argument("--chat-type", choices=("private", "group", "supergroup"))


    inspect = subparsers.add_parser("inspect", help="Inspect public preview metadata")
    inspect.add_argument("preview_id")


    revoke = subparsers.add_parser("revoke", help="Revoke a preview")
    revoke.add_argument("preview_id")


    serve = subparsers.add_parser("serve", help="Run the local preview service")
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    serve.add_argument("--port", default=8765, type=_port)

    setup = subparsers.add_parser("setup", help="Install and integrate HermesPeek")
    setup.add_argument("--allowed-root", action="append", type=Path)
    setup.add_argument("--external-url")
    setup.add_argument("--telegram-bot-username")
    setup.add_argument("--telegram-mini-app-short-name")
    setup.add_argument("--telegram-mini-app-mode", choices=("compact",), default="compact")
    setup.add_argument(
        "--telegram-env",
        type=Path,
        help="Credential file containing TELEGRAM_BOT_TOKEN (defaults to the active Hermes .env)",
    )
    setup.add_argument("--configure-telegram-menu", action="store_true")
    setup.add_argument("--hermes-home", type=Path)
    setup.add_argument("--no-activate", action="store_true")
    setup.add_argument("--plan", action="store_true", help="Print a read-only, redacted setup plan")


    uninstall = subparsers.add_parser("uninstall", help="Safely remove HermesPeek integration")
    uninstall.add_argument("--hermes-home", type=Path)
    uninstall.add_argument("--purge", "--purge-data", dest="purge", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--yes", action="store_true")
    uninstall.add_argument("--no-deactivate", action="store_true")

    rollback = subparsers.add_parser("rollback", help="Rollback a committed setup transaction")
    rollback.add_argument("transaction_id")
    rollback.add_argument("--hermes-home", type=Path)

    status = subparsers.add_parser("status", help="Show lifecycle status")

    status.add_argument("--hermes-home", type=Path)
    doctor = subparsers.add_parser("doctor", help="Run read-only lifecycle diagnostics")

    doctor.add_argument("--hermes-home", type=Path)
    service = subparsers.add_parser("service", help="Manage the local service")
    service.add_argument("action", choices=("start", "stop", "restart", "logs"))

    update = subparsers.add_parser("update", aliases=("upgrade",), help="Update a curl-installed HermesPeek CLI")
    update.add_argument("--check", action="store_true", help="Check for an update without changing anything")
    update.add_argument("--plan", action="store_true", help="Print a read-only update plan")
    update.add_argument("--version", dest="target_version", help="Update to a specific release version")
    update.add_argument("--yes", action="store_true", help="Apply without interactive confirmation")

    return parser


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


_SETUP_PROGRESS_MESSAGES = {
    "validating_setup": ("Validating setup...", "Setup validated"),
    "installing_integration": ("Installing HermesPeek integration...", "HermesPeek integration installed"),
    "starting_service": ("Starting HermesPeek service...", "HermesPeek service started"),
    "enabling_plugin": ("Enabling HermesPeek in Hermes...", "HermesPeek enabled in Hermes"),
    "restarting_gateway": ("Restarting Hermes Gateway...", "Hermes Gateway restarted"),
    "verifying_installation": ("Verifying installation...", "Installation verified"),
}

_UPDATE_PROGRESS_MESSAGES = {
    "downloading_update": ("Downloading HermesPeek update...", "HermesPeek update downloaded"),
    "staging_update": ("Staging HermesPeek update...", "HermesPeek update staged"),
    "switching_update": ("Installing HermesPeek update...", "HermesPeek update installed"),
    "reapplying_integration": ("Updating HermesPeek integration...", "HermesPeek integration updated"),
    "verifying_update": ("Verifying HermesPeek update...", "HermesPeek update verified"),
}

_UNINSTALL_PROGRESS_MESSAGES = {
    "stopping_service": ("Stopping HermesPeek service...", "HermesPeek service stopped"),
    "disabling_integration": ("Disabling HermesPeek in Hermes...", "HermesPeek disabled in Hermes"),
    "restarting_gateway": ("Restarting Hermes Gateway...", "Hermes Gateway restarted"),
    "removing_integration": ("Removing HermesPeek integration...", "HermesPeek integration removed"),
    "purging_data": ("Purging HermesPeek data...", "HermesPeek data purged"),
    "removing_cli": ("Removing HermesPeek CLI...", "HermesPeek CLI removal scheduled"),
}


class _TerminalProgress:
    """Render one animated progress line on a TTY and stay silent elsewhere."""

    _frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, messages: dict[str, tuple[str, str]]) -> None:
        self.messages = messages
        self.enabled = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._phase: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __call__(self, phase: str) -> None:
        if phase not in self.messages:
            if phase == "committed":
                self.finish()
            return
        self.finish()
        if not self.enabled:
            return
        self._phase = phase
        self._stop.clear()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def _animate(self) -> None:
        message = self.messages[self._phase][0] if self._phase else ""
        index = 0
        while not self._stop.is_set():
            print(f"\r\033[2K{self._frames[index % len(self._frames)]} {message}", end="", flush=True)
            index += 1
            self._stop.wait(0.08)

    def finish(self, *, failed: bool = False) -> None:
        phase = self._phase
        if phase is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        if self.enabled:
            message = self.messages[phase][0 if failed else 1]
            marker = "✗" if failed else "✓"
            print(f"\r\033[2K{marker} {message}", flush=True)
        self._phase = None
        self._thread = None


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        if args.command in {"update", "upgrade"}:
            target = args.target_version or _latest_release_version()
            plan = _update_cli(target, apply=False)
            if args.check or args.plan or not plan["update_available"]:
                _print_result(plan, kind="update")
                return 0
            if not args.yes:
                if not sys.stdin.isatty():
                    raise LifecycleError("non-interactive update requires --yes")
                if input(f"Update HermesPeek {__version__} to {target}? [y/N] ").strip().lower() not in {"y", "yes"}:
                    raise LifecycleError("update cancelled")
            update_progress = _TerminalProgress(_UPDATE_PROGRESS_MESSAGES)
            try:
                update_result = _update_cli(target, apply=True, progress=update_progress)
                update_progress.finish()
            except Exception:
                update_progress.finish(failed=True)
                raise
            _print_result(update_result, kind="update")
            return 0
        if args.command in {"status", "doctor", "service"}:
            paths = _paths_for_user(
                _resolve_lifecycle_home(getattr(args, "hermes_home", None))
                if args.command != "service"
                else None
            )
            if args.command == "status":
                output = lifecycle_status(paths, lifecycle_runner)
            elif args.command == "doctor":
                output = lifecycle_doctor(paths, lifecycle_runner)
            else:
                backend = SystemdUserBackend(lifecycle_runner)
                operation = getattr(backend, args.action)
                value = operation()
                if args.action == "stop":
                    backend.verify_stopped()
                output = {"action": args.action, "ok": True}
                if value is not None:
                    output["output"] = value
            _print_result(output, kind=args.command)
            return 0
        if args.command == "rollback":
            paths = _paths_for_user(_resolve_lifecycle_home(args.hermes_home))
            result = rollback_transaction(paths, args.transaction_id, runner=lifecycle_runner)
            _print_result(result, kind="rollback")
            return 0
        if args.command in {"setup", "uninstall"}:
            selected_home = (
                _resolve_lifecycle_home(args.hermes_home)
                if args.command == "uninstall"
                else args.hermes_home or discover_installed_hermes_home()
            )
            if selected_home is None:
                profiles = discover_hermes_profiles(Path.home() / ".hermes")
                selected_home = (select_hermes_profile(profiles) if sys.stdin.isatty() and len(profiles) > 1
                                 else (profiles[0] if len(profiles) == 1 else Path.home() / ".hermes"))
            paths = _paths_for_user(selected_home)
            if args.command == "setup":
                existing = read_existing_setup(paths)
                allowed_roots_explicit = bool(args.allowed_root)
                external_url_explicit = bool(args.external_url)
                if not args.allowed_root:
                    args.allowed_root = list(existing.get("allowed_roots") or ())
                if not args.external_url:
                    args.external_url = existing.get("external_url")
                if not args.allowed_root or not args.external_url:
                    if not sys.stdin.isatty():
                        missing = []
                        if not args.allowed_root:
                            missing.append("--allowed-root")
                        if not args.external_url:
                            missing.append("--external-url")
                        if len(missing) == 2:
                            raise LifecycleError("first setup requires --allowed-root and --external-url")
                        raise LifecycleError("setup requires " + missing[0] + " in non-interactive mode")
                    wizard_values = dict(existing)
                    if allowed_roots_explicit:
                        wizard_values["allowed_roots"] = tuple(args.allowed_root)
                    if external_url_explicit:
                        wizard_values["external_url"] = args.external_url
                    wizard = run_setup_wizard(paths, input_fn=input, https_probe=setup_https_probe,
                                              activate=not args.no_activate, existing=wizard_values,
                                              prompt_allowed_roots=not bool(args.allowed_root),
                                              prompt_external_url=not bool(args.external_url))
                    args.allowed_root = list(wizard["allowed_roots"])
                    args.external_url = wizard["external_url"]
                if args.telegram_bot_username is None:
                    args.telegram_bot_username = existing.get("telegram_bot_username")
                if args.telegram_mini_app_short_name is None:
                    args.telegram_mini_app_short_name = existing.get("telegram_mini_app_short_name")
            if args.command == "setup":
                args.allowed_root = list(validate_allowed_roots(args.allowed_root))
                args.external_url = validate_https_origin(args.external_url)
                token_file = args.telegram_env or (paths.env_file if paths.env_file.is_file() else paths.hermes_home / ".env")
                if not args.plan:
                    validate_secret_file(token_file)
                if args.plan:
                    result = lifecycle_setup_plan(
                        paths,
                        allowed_roots=args.allowed_root,
                        external_url=args.external_url,
                        activate=not args.no_activate,
                    )
                    _print_result(result, kind="setup_plan")
                    return 0
                executable_path = resolve_current_executable()
                setup_progress = _TerminalProgress(_SETUP_PROGRESS_MESSAGES)
                try:
                    result = install_application(
                        paths=paths,
                        integration_dir=Path(__file__).with_name("hermes_plugin"),
                        executable=executable_path,
                        allowed_roots=tuple(args.allowed_root),
                        external_url=args.external_url,
                        bot_token=read_bot_token(token_file),
                        telegram_bot_username=args.telegram_bot_username,
                        telegram_mini_app_short_name=args.telegram_mini_app_short_name,
                        telegram_mini_app_mode=args.telegram_mini_app_mode,
                        activate=not args.no_activate,
                        telegram=TelegramLifecycle(telegram_lifecycle_transport()),
                        configure_telegram_menu=args.configure_telegram_menu,
                        defer_gateway_restart=_running_inside_gateway_session(),
                        final_verify=(lambda: (
                            verify_installed_plugin_runtime(paths),
                            verify_external_https_health(args.external_url),
                        )) if not args.no_activate else None,
                        runner=lifecycle_runner,
                        progress=setup_progress,
                    )
                    setup_progress.finish()
                except Exception:
                    setup_progress.finish(failed=True)
                    raise
            else:
                if args.dry_run and not args.purge:
                    raise LifecycleError("--dry-run requires --purge")
                if args.purge and args.dry_run:
                    result = plan_purge(paths)
                elif args.purge:
                    if not args.yes:
                        if not sys.stdin.isatty():
                            raise LifecycleError("non-interactive purge requires --yes")
                        expected = json.loads(paths.manifest_file.read_text()).get("transaction_id") if paths.manifest_file.is_file() else "PURGE"
                        if input(f"Type {expected} to permanently purge HermesPeek data: ") != expected:
                            raise LifecycleError("purge confirmation did not match")
                    uninstall_progress = _TerminalProgress(_UNINSTALL_PROGRESS_MESSAGES)
                    try:
                        uninstall_application(paths=paths, purge_data=False,
                                              deactivate=not args.no_deactivate,
                                              progress=uninstall_progress)
                        uninstall_progress("purging_data")
                        result = purge_application(paths, confirmed=True)
                        uninstall_progress("removing_cli")
                        _, cli_status = _remove_cli_installation()
                        uninstall_progress.finish()
                    except Exception:
                        uninstall_progress.finish(failed=True)
                        raise
                    result["original_files_preserved"] = True
                    print(_uninstall_message(result, cli_status=cli_status))
                    return 0
                else:
                    uninstall_progress = _TerminalProgress(_UNINSTALL_PROGRESS_MESSAGES)
                    try:
                        result = uninstall_application(paths=paths, purge_data=False,
                                                       deactivate=not args.no_deactivate,
                                                       progress=uninstall_progress)
                        uninstall_progress("removing_cli")
                        _, cli_status = _remove_cli_installation()
                        uninstall_progress.finish()
                    except Exception:
                        uninstall_progress.finish(failed=True)
                        raise
                    print(_uninstall_message(result, cli_status=cli_status))
                    return 0
            if args.command == "uninstall" and not args.dry_run:
                print(_uninstall_message(result))
            elif args.command == "setup":
                print(f"HermesPeek {__version__} installed successfully", flush=True)
                if result.get("activation_pending_gateway_restart"):
                    print("Gateway restart required: hermes gateway restart", flush=True)
            else:
                _print_result(result, kind="purge_plan")
            return 0
        settings = Settings.from_env()
        if args.command == "serve":
            token = os.environ.get("HERMES_PEEK_TELEGRAM_BOT_TOKEN")
            if not settings.development and not token:
                raise ValueError(
                    "serve requires HERMES_PEEK_TELEGRAM_BOT_TOKEN outside development"
                )
            uvicorn.run(
                create_app(settings, bot_token=token),
                host=args.host,
                port=args.port,
                log_level="info",
                access_log=False,
            )
            return 0
        service = PreviewService(
            registry=PreviewRegistry(settings.state_dir),
            path_policy=PathPolicy(
                settings.allowed_roots,
                max_file_bytes=settings.max_file_bytes,
            ),
            default_ttl_seconds=settings.default_ttl_seconds,
            external_base_url=(
                str(settings.external_base_url)
                if settings.external_base_url is not None
                else None
            ),
        )
        if args.command == "publish":
            result = service.publish(
                tuple(args.files),
                entry=args.entry,
                title=args.title,
                owner_telegram_user_id=args.owner,
            )
            output = {"preview_id": result.record.preview_id, "url": result.url}
            if args.notify:
                if not args.chat_id or not args.chat_type:
                    raise ValueError("--notify requires --chat-id and --chat-type")
                if result.url is None:
                    raise ValueError("--notify requires HERMES_PEEK_EXTERNAL_BASE_URL")
                token = os.environ.get("HERMES_PEEK_TELEGRAM_BOT_TOKEN")
                if not token:
                    raise ValueError(
                        "--notify requires HERMES_PEEK_TELEGRAM_BOT_TOKEN"
                    )
                try:
                    message = TelegramClient(
                        token, transport=telegram_transport()
                    ).send_preview(
                        chat_id=args.chat_id,
                        chat_type=args.chat_type,
                        preview_url=result.url,
                        title=args.title,
                        thread_id=args.thread_id,
                    )
                except TelegramNotificationError as exc:
                    print(
                        "error: Preview was published, but Telegram notification "
                        f"failed: {exc}",
                        file=sys.stderr,
                    )
                    return 3
                output.update(notified=True, message_id=message.get("message_id"))
        elif args.command == "inspect":
            output = service.inspect(args.preview_id).model_dump(mode="json")
        else:
            output = service.revoke(args.preview_id).model_dump(mode="json")
        _print_result(output, kind=args.command)
        return 0
    except (
        ValueError,
        ValidationError,
        PathPolicyError,
        PreviewNotFoundError,
        CorruptPreviewError,
        PublishError,
        LifecycleError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
