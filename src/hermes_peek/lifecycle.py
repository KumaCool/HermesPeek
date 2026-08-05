from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse


class LifecycleError(RuntimeError):
    """A safe installation or removal failure."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
_PLUGIN_FILES = ("plugin.yaml", "__init__.py", "collector.py", "handler.py")
_PLUGIN_CONFIG_POINTER = ".hermes-peek-config.json"
_BOT_TOKEN = re.compile(r"^[0-9]{6,12}:[A-Za-z0-9_-]{20,}$")


@dataclass(frozen=True, slots=True)
class InstallPaths:
    hermes_home: Path
    config_dir: Path
    state_dir: Path
    systemd_dir: Path

    @classmethod
    def for_user(
        cls,
        *,
        hermes_home: Path | None = None,
        config_home: Path | None = None,
        state_home: Path | None = None,
    ) -> "InstallPaths":
        home = Path.home().resolve()
        return cls(
            hermes_home=(hermes_home or home / ".hermes").expanduser().resolve(),
            config_dir=(config_home or home / ".config").expanduser().resolve() / "hermes-peek",
            state_dir=(state_home or home / ".local" / "state").expanduser().resolve() / "hermes-peek",
            systemd_dir=(config_home or home / ".config").expanduser().resolve() / "systemd" / "user",
        )

    @property
    def plugin_dir(self) -> Path:
        return self.hermes_home / "plugins" / "hermes-peek"

    @property
    def legacy_hook_dir(self) -> Path:
        return self.hermes_home / "hooks" / "hermes-peek"

    @property
    def env_file(self) -> Path:
        return self.config_dir / "secrets.env"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def manifest_file(self) -> Path:
        return self.config_dir / "install.json"

    @property
    def unit_file(self) -> Path:
        return self.systemd_dir / "hermes-peek.service"


@dataclass(frozen=True, slots=True)
class HermesTarget:
    hermes_home: Path

    @classmethod
    def from_paths(cls, paths: InstallPaths) -> "HermesTarget":
        return cls(paths.hermes_home.expanduser().resolve())

    @property
    def identity(self) -> str:
        return hashlib.sha256(str(self.hermes_home).encode()).hexdigest()

    def command(self, *arguments: str) -> tuple[str, ...]:
        return ("env", f"HERMES_HOME={self.hermes_home}", "hermes", *arguments)


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _env_value(value: str) -> str:
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise LifecycleError("configuration values must be non-empty single-line strings")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _validate_setup(allowed_roots: Sequence[Path], external_url: str, bot_token: str) -> tuple[Path, ...]:
    roots = tuple(path.expanduser().resolve(strict=True) for path in allowed_roots)
    if not roots or any(not path.is_dir() for path in roots):
        raise LifecycleError("at least one existing allowed root directory is required")
    parsed = urlparse(external_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise LifecycleError("external URL must be an HTTPS origin without credentials")
    if parsed.query or parsed.fragment:
        raise LifecycleError("external URL must not contain a query or fragment")
    if not _BOT_TOKEN.fullmatch(bot_token):
        raise LifecycleError("Telegram Bot Token has an invalid format")
    return roots


def _render_env(roots: Sequence[Path], paths: InstallPaths, external_url: str, bot_token: str) -> str:
    return "\n".join(
        (
            f'HERMES_PEEK_CONFIG_FILE="{_env_value(str(paths.config_file))}"',
            f'HERMES_PEEK_TELEGRAM_BOT_TOKEN="{_env_value(bot_token)}"',
            "HERMES_PEEK_DEVELOPMENT=false",
            "",
        )
    )


def _render_unit(paths: InstallPaths, executable: Path) -> str:
    return f"""[Unit]
Description=HermesPeek local preview service
After=network.target

[Service]
Type=simple
EnvironmentFile={paths.env_file}
ExecStart={executable} serve --host 127.0.0.1 --port 8765
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
ReadWritePaths={paths.state_dir}

[Install]
WantedBy=default.target
"""


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _run(runner: CommandRunner, command: Sequence[str], *, optional: bool = False) -> None:
    result = runner(command)
    if result.returncode and not optional:
        detail = (result.stderr or result.stdout or "command failed").strip().splitlines()[-1]
        raise LifecycleError(f"{command[0]} failed: {detail}")


def _plugin_state(paths: InstallPaths, runner: CommandRunner) -> dict[str, bool]:
    """Read Hermes plugin state using the supported machine-readable list API."""
    result = runner(HermesTarget.from_paths(paths).command("plugins", "list", "--json"))
    if result.returncode:
        return {"installed": False, "enabled": False, "loaded": False}
    try:
        entries = json.loads(result.stdout or "[]")
    except (TypeError, ValueError):
        return {"installed": False, "enabled": False, "loaded": False}
    if not isinstance(entries, list):
        return {"installed": False, "enabled": False, "loaded": False}
    entry = next((item for item in entries if isinstance(item, dict) and item.get("name") == "hermes-peek"), None)
    enabled = bool(entry and str(entry.get("status", "")).lower() == "enabled")
    return {"installed": entry is not None, "enabled": enabled, "loaded": enabled}


def _probe_runtime(paths: InstallPaths, runner: CommandRunner) -> dict[str, bool]:
    target = HermesTarget.from_paths(paths)
    active = runner(("systemctl", "--user", "is-active", "hermes-peek.service")).returncode == 0
    enabled = runner(("systemctl", "--user", "is-enabled", "hermes-peek.service")).returncode == 0
    gateway = runner(target.command("gateway", "status"))
    plugin = _plugin_state(paths, runner)
    return {"service_active": active, "service_enabled": enabled,
            "plugin_installed": plugin["installed"], "plugin_enabled": plugin["enabled"],
            "gateway_active": gateway.returncode == 0}


def _restore_files(resources: Sequence[Path], existed: dict[str, bool], backup: Path) -> None:
    for index, resource in reversed(tuple(enumerate(resources))):
        if resource.is_dir() and not resource.is_symlink():
            shutil.rmtree(resource, ignore_errors=True)
        else:
            resource.unlink(missing_ok=True)
        if existed.get(str(resource), False):
            source = backup / str(index)
            resource.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir() and not source.is_symlink():
                shutil.copytree(source, resource, symlinks=True)
            else:
                shutil.copy2(source, resource, follow_symlinks=False)


def _restore_runtime(paths: InstallPaths, runner: CommandRunner, before: dict[str, bool]) -> list[str]:
    target = HermesTarget.from_paths(paths); errors: list[str] = []
    commands: list[tuple[str, ...]] = []
    if before.get("plugin_enabled"):
        commands.append(target.command("plugins", "enable", "--no-allow-tool-override", "hermes-peek"))
    elif before.get("plugin_installed"):
        commands.append(target.command("plugins", "disable", "hermes-peek"))
    else:
        commands.append(target.command("plugins", "remove", "hermes-peek"))
    if before.get("service_enabled") and before.get("service_active"):
        commands.append(("systemctl", "--user", "enable", "--now", "hermes-peek.service"))
    elif before.get("service_enabled"):
        commands.append(("systemctl", "--user", "enable", "hermes-peek.service"))
        commands.append(("systemctl", "--user", "stop", "hermes-peek.service"))
    elif before.get("service_active"):
        commands.append(("systemctl", "--user", "disable", "hermes-peek.service"))
        commands.append(("systemctl", "--user", "start", "hermes-peek.service"))
    else:
        commands.append(("systemctl", "--user", "disable", "--now", "hermes-peek.service"))
    if before.get("gateway_active"):
        commands.append(target.command("gateway", "restart"))
    for command in commands:
        result = runner(command)
        missing_plugin = command[-2:] == ("remove", "hermes-peek") and any(
            marker in (result.stderr or result.stdout or "").lower()
            for marker in ("not installed", "not found", "does not exist")
        )
        if result.returncode and not missing_plugin:
            errors.append(" ".join(command[:4]))
    return errors


def _install_apply(
    *,
    paths: InstallPaths,
    integration_dir: Path,
    executable: Path,
    allowed_roots: Sequence[Path],
    external_url: str,
    bot_token: str,
    telegram_bot_username: str | None = None,
    telegram_mini_app_short_name: str | None = None,
    telegram_mini_app_mode: str = "compact",
    activate: bool = True,
    runner: CommandRunner = _default_runner,
    service_backend: Any | None = None,
    transaction_id: str = "pending",
    defer_gateway_restart: bool = False,
) -> dict[str, object]:
    target = HermesTarget.from_paths(paths)
    roots = _validate_setup(allowed_roots, external_url, bot_token)
    executable = executable.expanduser().resolve(strict=True)
    source = integration_dir.expanduser().resolve(strict=True)
    missing = [name for name in _PLUGIN_FILES if not (source / name).is_file()]
    if missing:
        raise LifecycleError("integration package is incomplete")
    if paths.legacy_hook_dir.exists() or paths.legacy_hook_dir.is_symlink():
        raise LifecycleError("unowned legacy hook must be reviewed and removed explicitly")

    if activate:
        from .service_backend import SystemdUserBackend
        backend = service_backend or SystemdUserBackend(runner)
        backend.preflight()


    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(paths.state_dir, 0o700)
    paths.plugin_dir.mkdir(parents=True, exist_ok=True)
    for name in _PLUGIN_FILES:
        shutil.copy2(source / name, paths.plugin_dir / name)
    _atomic_write(
        paths.plugin_dir / _PLUGIN_CONFIG_POINTER,
        json.dumps({"config_file": str(paths.config_file)}, sort_keys=True) + "\n",
        0o644,
    )

    _atomic_write(paths.env_file, _render_env(roots, paths, external_url, bot_token), 0o600)
    config = {
        "schema_version": 1,
        "allowed_roots": [str(root) for root in roots],
        "state_dir": str(paths.state_dir),
        "external_base_url": external_url.rstrip("/") + "/",
        "target": {"hermes_home": str(target.hermes_home), "identity": target.identity},
    }
    if telegram_bot_username:
        config["telegram_bot_username"] = telegram_bot_username.removeprefix("@")
    if telegram_mini_app_short_name:
        config["telegram_mini_app_short_name"] = telegram_mini_app_short_name
    config["telegram_mini_app_mode"] = telegram_mini_app_mode
    _atomic_write(paths.config_file, json.dumps(config, indent=2, sort_keys=True) + "\n", 0o644)
    _atomic_write(paths.unit_file, _render_unit(paths, executable), 0o644)
    owned_plugin_files = _PLUGIN_FILES + (_PLUGIN_CONFIG_POINTER,)
    hashes = {
        name: hashlib.sha256((paths.plugin_dir / name).read_bytes()).hexdigest()
        for name in owned_plugin_files
    }
    owned_paths = [paths.plugin_dir / name for name in owned_plugin_files] + [paths.env_file, paths.config_file, paths.unit_file]
    manifest = {
        "schema_version": 2,
        "transaction_id": transaction_id,
        "target": {"hermes_home": str(target.hermes_home), "identity": target.identity},
        "plugin_dir": str(paths.plugin_dir),
        "env_file": str(paths.env_file),
        "config_file": str(paths.config_file),
        "unit_file": str(paths.unit_file),
        "state_dir": str(paths.state_dir),
        "plugin_hashes": hashes,
        "owned_resources": [
            {"path": str(path), "type": "file", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "transaction_id": transaction_id}
            for path in owned_paths
        ],
    }
    _atomic_write(paths.manifest_file, json.dumps(manifest, indent=2, sort_keys=True) + "\n", 0o600)

    if activate:
        _run(runner, ("systemctl", "--user", "daemon-reload"))
        _run(runner, ("systemctl", "--user", "enable", "--now", "hermes-peek.service"))
        backend.verify_running()
        _run(runner, target.command("plugins", "enable", "--no-allow-tool-override", "hermes-peek"))
        if not defer_gateway_restart:
            _run(runner, target.command("gateway", "restart"))
    return {"installed": True, "activated": activate, "state_preserved": True,
            "activation_pending_gateway_restart": bool(activate and defer_gateway_restart)}


@contextmanager
def lifecycle_lock(paths: InstallPaths):
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    lock_file = paths.config_dir / ".lifecycle.lock"
    with lock_file.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LifecycleError("another lifecycle operation is already in progress") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _install_transaction(**kwargs) -> dict[str, object]:
    """Apply setup as a filesystem transaction and retain a recovery journal."""
    paths: InstallPaths = kwargs["paths"]
    transaction_id = uuid.uuid4().hex
    kwargs["transaction_id"] = transaction_id
    journal_dir = paths.state_dir / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = journal_dir / f"{transaction_id}.json"
    resources = (paths.plugin_dir, paths.legacy_hook_dir, paths.env_file, paths.config_file,
                 paths.unit_file, paths.manifest_file)
    backup = Path(tempfile.mkdtemp(prefix=f"txn-{transaction_id}-", dir=paths.state_dir))
    existed: dict[str, bool] = {}
    for index, resource in enumerate(resources):
        existed[str(resource)] = resource.exists() or resource.is_symlink()
        if existed[str(resource)]:
            destination = backup / str(index)
            if resource.is_dir() and not resource.is_symlink():
                shutil.copytree(resource, destination, symlinks=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resource, destination, follow_symlinks=False)
    before = _probe_runtime(paths, kwargs["runner"]) if kwargs.get("activate", True) else {}
    record: dict[str, Any] = {"id": transaction_id, "state": "applying", "backup": str(backup),
                              "resources": [str(path) for path in resources], "existed": existed,
                              "before": before, "rollback_errors": [], "telegram_changes": []}
    _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True) + "\n", 0o600)
    telegram = kwargs.pop("telegram", None)
    try:
        configure_menu = kwargs.pop("configure_telegram_menu", False)
        expected_bot_id = kwargs.pop("expected_bot_id", None)
        final_verify = kwargs.pop("final_verify", None)
        if telegram is not None:
            telegram.inspect(kwargs["bot_token"], expected_bot_id=expected_bot_id)
            if configure_menu:
                record["telegram_changes"].append(
                    telegram.set_menu(kwargs["bot_token"], kwargs["external_url"].rstrip("/")))
                _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True) + "\n", 0o600)
        result = _install_apply(**kwargs)
        if final_verify is not None:
            final_verify()
    except Exception as exc:
        for change in reversed(record["telegram_changes"]):
            try:
                if telegram is not None:
                    telegram.rollback(kwargs["bot_token"], change)
            except Exception:
                record["rollback_errors"].append("telegram")
        _restore_files(resources, existed, backup)
        errors = _restore_runtime(paths, kwargs["runner"], before) if before else []
        errors = record["rollback_errors"] + errors
        record.update(state="rollback_incomplete" if errors else "rolled_back", rollback_errors=errors)
        _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True) + "\n", 0o600)
        if not errors:
            shutil.rmtree(backup, ignore_errors=True)
        raise LifecycleError(f"setup transaction {transaction_id} failed; rollback " +
                             ("incomplete: " + ", ".join(errors) if errors else "completed")) from exc
    record["state"] = "committed"
    _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True) + "\n", 0o600)
    result["transaction_id"] = transaction_id
    return result


def install(**kwargs) -> dict[str, object]:
    paths: InstallPaths = kwargs["paths"]
    if paths.plugin_dir.is_symlink():
        raise LifecycleError("symlinked plugin directory is unsafe")
    if paths.plugin_dir.exists():
        try:
            manifest = json.loads(paths.manifest_file.read_text(encoding="utf-8"))
            target = HermesTarget.from_paths(paths)
            owned = manifest.get("owned_resources")
            hashes = manifest.get("plugin_hashes")
            owned_by_path = {
                entry.get("path"): entry
                for entry in owned
                if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            } if isinstance(owned, list) else {}
            valid_manifest = (
                manifest.get("schema_version") == 2
                and manifest.get("target", {}).get("identity") == target.identity
                and isinstance(owned, list)
                and isinstance(hashes, dict)
                and all(
                    isinstance(name, str)
                    and (paths.plugin_dir / name).is_file()
                    and not (paths.plugin_dir / name).is_symlink()
                    and hashlib.sha256((paths.plugin_dir / name).read_bytes()).hexdigest() == digest
                    and owned_by_path.get(str(paths.plugin_dir / name), {}).get("sha256") == digest
                    for name, digest in hashes.items()
                )
                and {child.name for child in paths.plugin_dir.iterdir()} == set(hashes)
            )
        except (OSError, ValueError, TypeError):
            valid_manifest = False
        if not valid_manifest:
            raise LifecycleError("pre-existing plugin directory requires a valid ownership manifest")
    if paths.legacy_hook_dir.exists() or paths.legacy_hook_dir.is_symlink():
        raise LifecycleError("unowned legacy hook must be reviewed and removed explicitly")
    with lifecycle_lock(paths):
        return _install_transaction(**kwargs)


def _rollback_transaction(paths: InstallPaths, transaction_id: str, *, runner: CommandRunner = _default_runner) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise LifecycleError("invalid transaction ID")
    journal = paths.state_dir / "journal" / f"{transaction_id}.json"
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleError("transaction journal is unavailable") from exc
    if record.get("id") != transaction_id or record.get("state") != "committed":
        raise LifecycleError("transaction is not committed and rollbackable")
    resources = tuple(Path(value) for value in record["resources"])
    backup = Path(record["backup"])
    if not backup.is_dir():
        raise LifecycleError("transaction backup is unavailable")
    _restore_files(resources, record["existed"], backup)
    errors = _restore_runtime(paths, runner, record.get("before", {}))
    record.update(state="rollback_incomplete" if errors else "rolled_back", rollback_errors=errors)
    _atomic_write(journal, json.dumps(record, indent=2, sort_keys=True) + "\n", 0o600)
    if errors:
        raise LifecycleError(f"transaction {transaction_id} rollback incomplete: {', '.join(errors)}")
    shutil.rmtree(backup, ignore_errors=True)
    return {"rolled_back": True, "transaction_id": transaction_id}


def rollback_transaction(paths: InstallPaths, transaction_id: str, *, runner: CommandRunner = _default_runner) -> dict[str, object]:
    with lifecycle_lock(paths):
        return _rollback_transaction(paths, transaction_id, runner=runner)


def _verify_plugin_unloaded(paths: InstallPaths, runner: CommandRunner) -> None:
    state = _plugin_state(paths, runner)
    if state["enabled"] or state["loaded"]:
        raise LifecycleError("plugin remained enabled or loaded after Gateway restart")


def _uninstall_transaction(
    *,
    paths: InstallPaths,
    purge_data: bool = False,
    deactivate: bool = True,
    runner: CommandRunner = _default_runner,
    service_backend: Any | None = None,
) -> dict[str, object]:
    target = HermesTarget.from_paths(paths)
    if not paths.manifest_file.is_file():
        if paths.plugin_dir.exists():
            raise LifecycleError("committed install manifest is required for recursive removal")
        if purge_data:
            shutil.rmtree(paths.state_dir, ignore_errors=True)
        return {"uninstalled": True, "data_purged": purge_data, "state_preserved": not purge_data, "modified_backups": []}
    try:
        manifest = json.loads(paths.manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleError("committed install manifest is invalid") from exc
    if manifest.get("schema_version") == 2:
        if manifest.get("target", {}).get("identity") != target.identity:
            raise LifecycleError("manifest target does not match requested Hermes target")
        owned = manifest.get("owned_resources")
        if not isinstance(owned, list):
            raise LifecycleError("manifest owned resources are invalid")
        approved = (paths.plugin_dir, paths.config_dir, paths.systemd_dir)
        for entry in owned:
            resource = Path(entry.get("path", ""))
            if resource.is_symlink():
                raise LifecycleError("owned resource symlink is unsafe")
            resolved = resource.resolve(strict=False)
            if not any(resolved == root.resolve() or resolved.is_relative_to(root.resolve()) for root in approved):
                raise LifecycleError("owned resource is outside approved directories")
    if deactivate:
        from .service_backend import SystemdUserBackend
        backend = service_backend or SystemdUserBackend(runner)
        _run(runner, ("systemctl", "--user", "disable", "--now", "hermes-peek.service"))
        backend.verify_stopped()
        _run(runner, target.command("plugins", "disable", "hermes-peek"))
        _run(runner, target.command("gateway", "restart"))
        _verify_plugin_unloaded(paths, runner)

    backups: list[str] = []
    backup_dir = paths.state_dir / "uninstall-backups" / target.identity[:12]
    owned_entries = {entry["path"]: entry for entry in manifest.get("owned_resources", [])}
    owned_hashes = manifest.get("plugin_hashes", {})
    for child in list(paths.plugin_dir.iterdir()) if paths.plugin_dir.is_dir() else []:
        if child.name == "__pycache__" and child.is_dir() and not child.is_symlink():
            if any(item.is_symlink() or item.is_dir() for item in child.iterdir()):
                raise LifecycleError("plugin bytecode cache contains an unsafe resource")
            shutil.rmtree(child)
            continue
        expected = owned_hashes.get(child.name)
        if expected is None or child.is_symlink():
            raise LifecycleError("plugin directory contains an unowned resource")
        actual = hashlib.sha256(child.read_bytes()).hexdigest()
        if actual != expected:
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination = backup_dir / child.name
            shutil.move(child, destination)
            backups.append(str(destination))
        else:
            child.unlink()
    if paths.plugin_dir.exists():
        paths.plugin_dir.rmdir()
    for resource in (paths.unit_file, paths.env_file, paths.config_file):
        if not resource.exists():
            continue
        entry = owned_entries.get(str(resource))
        if manifest.get("schema_version") == 2 and entry is None:
            raise LifecycleError("resource lacks ownership evidence")
        digest = hashlib.sha256(resource.read_bytes()).hexdigest()
        if entry and digest != entry.get("sha256"):
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination = backup_dir / resource.name
            shutil.move(resource, destination); backups.append(str(destination))
        else:
            resource.unlink()
    paths.manifest_file.unlink(missing_ok=True)
    if purge_data:
        shutil.rmtree(paths.state_dir, ignore_errors=True)
    if deactivate:
        _run(runner, ("systemctl", "--user", "daemon-reload"))
    return {"uninstalled": True, "data_purged": purge_data, "state_preserved": not purge_data, "modified_backups": backups}


def uninstall(**kwargs) -> dict[str, object]:
    with lifecycle_lock(kwargs["paths"]):
        return _uninstall_transaction(**kwargs)


def read_bot_token(env_file: Path) -> str:
    try:
        lines = env_file.expanduser().read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise LifecycleError(f"cannot read Telegram credentials from {env_file}") from exc
    for line in lines:
        key, separator, raw = line.partition("=")
        if separator and key.strip() in {"TELEGRAM_BOT_TOKEN", "HERMES_PEEK_TELEGRAM_BOT_TOKEN"}:
            value = raw.strip().strip('"').strip("'")
            if _BOT_TOKEN.fullmatch(value):
                return value
    raise LifecycleError("Telegram Bot Token was not found in the credential file")


def plan_purge(paths: InstallPaths) -> dict[str, object]:
    approved = (paths.state_dir, paths.config_dir)
    entries: list[dict[str, object]] = []
    total = 0
    for root in approved:
        if root.exists() and root.is_dir() and not root.is_symlink():
            size = sum(item.stat().st_size for item in root.rglob("*") if item.is_file() and not item.is_symlink())
            total += size
            entries.append({"path": str(root), "type": "directory", "bytes": size, "recoverable": False})
    return {"dry_run": True, "entries": entries, "total_bytes": total, "original_files_excluded": True}


def purge(paths: InstallPaths, *, confirmed: bool) -> dict[str, object]:
    if not confirmed:
        raise LifecycleError("purge requires explicit confirmation")
    if paths.manifest_file.exists():
        raise LifecycleError("purge requires a completed uninstall")
    for root in (paths.state_dir, paths.config_dir):
        resolved = root.resolve()
        if resolved == Path("/") or resolved == Path.home().resolve() or root.is_symlink():
            raise LifecycleError("unsafe purge target")
        shutil.rmtree(root, ignore_errors=True)
    return {"purged": True, "original_files_preserved": True}
