from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse


class LifecycleError(RuntimeError):
    """A safe installation or removal failure."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
_PLUGIN_FILES = ("plugin.yaml", "__init__.py", "collector.py", "handler.py")
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
PrivateDevices=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
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


def _install_apply(
    *,
    paths: InstallPaths,
    integration_dir: Path,
    executable: Path,
    allowed_roots: Sequence[Path],
    external_url: str,
    bot_token: str,
    activate: bool = True,
    runner: CommandRunner = _default_runner,
) -> dict[str, object]:
    target = HermesTarget.from_paths(paths)
    roots = _validate_setup(allowed_roots, external_url, bot_token)
    executable = executable.expanduser().resolve(strict=True)
    source = integration_dir.expanduser().resolve(strict=True)
    missing = [name for name in _PLUGIN_FILES if not (source / name).is_file()]
    if missing:
        raise LifecycleError("integration package is incomplete")

    paths.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(paths.state_dir, 0o700)
    paths.plugin_dir.mkdir(parents=True, exist_ok=True)
    for name in _PLUGIN_FILES:
        shutil.copy2(source / name, paths.plugin_dir / name)
    # Remove only the obsolete HermesPeek hook; leaving it would create duplicate notifications.
    shutil.rmtree(paths.legacy_hook_dir, ignore_errors=True)

    _atomic_write(paths.env_file, _render_env(roots, paths, external_url, bot_token), 0o600)
    config = {
        "schema_version": 1,
        "allowed_roots": [str(root) for root in roots],
        "state_dir": str(paths.state_dir),
        "external_base_url": external_url.rstrip("/") + "/",
        "target": {"hermes_home": str(target.hermes_home), "identity": target.identity},
    }
    _atomic_write(paths.config_file, json.dumps(config, indent=2, sort_keys=True) + "\n", 0o644)
    _atomic_write(paths.unit_file, _render_unit(paths, executable), 0o644)
    hashes = {
        name: hashlib.sha256((paths.plugin_dir / name).read_bytes()).hexdigest()
        for name in _PLUGIN_FILES
    }
    manifest = {
        "schema_version": 1,
        "target": {"hermes_home": str(target.hermes_home), "identity": target.identity},
        "plugin_dir": str(paths.plugin_dir),
        "env_file": str(paths.env_file),
        "config_file": str(paths.config_file),
        "unit_file": str(paths.unit_file),
        "state_dir": str(paths.state_dir),
        "plugin_hashes": hashes,
    }
    _atomic_write(paths.manifest_file, json.dumps(manifest, indent=2, sort_keys=True) + "\n", 0o600)

    if activate:
        _run(runner, ("systemctl", "--user", "daemon-reload"))
        _run(runner, ("systemctl", "--user", "enable", "--now", "hermes-peek.service"))
        _run(runner, target.command("plugins", "enable", "--no-allow-tool-override", "hermes-peek"))
        _run(runner, target.command("gateway", "restart"))
    return {"installed": True, "activated": activate, "state_preserved": True}


def install(**kwargs) -> dict[str, object]:
    """Apply setup as a filesystem transaction and retain a recovery journal."""
    paths: InstallPaths = kwargs["paths"]
    transaction_id = uuid.uuid4().hex
    journal_dir = paths.state_dir / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = journal_dir / f"{transaction_id}.json"
    resources = (paths.plugin_dir, paths.env_file, paths.config_file, paths.unit_file, paths.manifest_file)
    backup = Path(tempfile.mkdtemp(prefix=f"txn-{transaction_id}-", dir=paths.state_dir))
    existed: dict[Path, bool] = {}
    for index, resource in enumerate(resources):
        existed[resource] = resource.exists() or resource.is_symlink()
        if existed[resource]:
            destination = backup / str(index)
            if resource.is_dir() and not resource.is_symlink():
                shutil.copytree(resource, destination, symlinks=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resource, destination, follow_symlinks=False)
    _atomic_write(journal, json.dumps({"id": transaction_id, "state": "applying"}) + "\n", 0o600)
    try:
        result = _install_apply(**kwargs)
    except Exception:
        for index, resource in reversed(tuple(enumerate(resources))):
            if resource.is_dir() and not resource.is_symlink():
                shutil.rmtree(resource, ignore_errors=True)
            else:
                resource.unlink(missing_ok=True)
            if existed[resource]:
                source = backup / str(index)
                resource.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir() and not source.is_symlink():
                    shutil.copytree(source, resource, symlinks=True)
                else:
                    shutil.copy2(source, resource, follow_symlinks=False)
        _atomic_write(journal, json.dumps({"id": transaction_id, "state": "rolled_back"}) + "\n", 0o600)
        shutil.rmtree(backup, ignore_errors=True)
        raise
    _atomic_write(journal, json.dumps({"id": transaction_id, "state": "committed"}) + "\n", 0o600)
    shutil.rmtree(backup, ignore_errors=True)
    return result


def uninstall(
    *,
    paths: InstallPaths,
    purge_data: bool = False,
    deactivate: bool = True,
    runner: CommandRunner = _default_runner,
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
    if deactivate:
        _run(runner, ("systemctl", "--user", "disable", "--now", "hermes-peek.service"))
        _run(runner, target.command("plugins", "disable", "hermes-peek"))
        _run(runner, target.command("gateway", "restart"))

    backups: list[str] = []
    backup_dir = paths.state_dir / "uninstall-backups" / target.identity[:12]
    owned_hashes = manifest.get("plugin_hashes", {})
    for child in list(paths.plugin_dir.iterdir()) if paths.plugin_dir.is_dir() else []:
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
    paths.unit_file.unlink(missing_ok=True)
    paths.env_file.unlink(missing_ok=True)
    paths.config_file.unlink(missing_ok=True)
    paths.manifest_file.unlink(missing_ok=True)
    if purge_data:
        shutil.rmtree(paths.state_dir, ignore_errors=True)
    if deactivate:
        _run(runner, ("systemctl", "--user", "daemon-reload"))
    return {"uninstalled": True, "data_purged": purge_data, "state_preserved": not purge_data, "modified_backups": backups}


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
