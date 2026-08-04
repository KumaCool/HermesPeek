from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
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
        return self.config_dir / "hermes-peek.env"

    @property
    def manifest_file(self) -> Path:
        return self.config_dir / "install.json"

    @property
    def unit_file(self) -> Path:
        return self.systemd_dir / "hermes-peek.service"


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
            f'HERMES_PEEK_ALLOWED_ROOTS="{_env_value(os.pathsep.join(map(str, roots)))}"',
            f'HERMES_PEEK_STATE_DIR="{_env_value(str(paths.state_dir))}"',
            f'HERMES_PEEK_EXTERNAL_BASE_URL="{_env_value(external_url.rstrip("/") + "/")}"',
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


def install(
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
    _atomic_write(paths.unit_file, _render_unit(paths, executable), 0o644)
    hashes = {
        name: hashlib.sha256((paths.plugin_dir / name).read_bytes()).hexdigest()
        for name in _PLUGIN_FILES
    }
    manifest = {
        "schema_version": 1,
        "plugin_dir": str(paths.plugin_dir),
        "env_file": str(paths.env_file),
        "unit_file": str(paths.unit_file),
        "state_dir": str(paths.state_dir),
        "plugin_hashes": hashes,
    }
    _atomic_write(paths.manifest_file, json.dumps(manifest, indent=2, sort_keys=True) + "\n", 0o600)

    if activate:
        _run(runner, ("systemctl", "--user", "daemon-reload"))
        _run(runner, ("systemctl", "--user", "enable", "--now", "hermes-peek.service"))
        _run(runner, ("hermes", "plugins", "enable", "--no-allow-tool-override", "hermes-peek"))
        _run(runner, ("hermes", "gateway", "restart"))
    return {"installed": True, "activated": activate, "state_preserved": True}


def uninstall(
    *,
    paths: InstallPaths,
    purge_data: bool = False,
    deactivate: bool = True,
    runner: CommandRunner = _default_runner,
) -> dict[str, object]:
    if deactivate:
        _run(runner, ("hermes", "plugins", "disable", "hermes-peek"), optional=True)
        _run(runner, ("hermes", "gateway", "restart"), optional=True)
        _run(runner, ("systemctl", "--user", "disable", "--now", "hermes-peek.service"), optional=True)

    shutil.rmtree(paths.plugin_dir, ignore_errors=True)
    shutil.rmtree(paths.legacy_hook_dir, ignore_errors=True)
    paths.unit_file.unlink(missing_ok=True)
    paths.env_file.unlink(missing_ok=True)
    paths.manifest_file.unlink(missing_ok=True)
    try:
        paths.config_dir.rmdir()
    except OSError:
        pass
    if purge_data:
        shutil.rmtree(paths.state_dir, ignore_errors=True)
    if deactivate:
        _run(runner, ("systemctl", "--user", "daemon-reload"), optional=True)
    return {"uninstalled": True, "data_purged": purge_data, "state_preserved": not purge_data}


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
