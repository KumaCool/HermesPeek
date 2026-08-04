from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from hermes_peek.lifecycle import LifecycleError, InstallPaths, install, read_bot_token, uninstall
from hermes_peek.lifecycle import plan_purge, purge


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src" / "hermes_peek" / "hermes_plugin"


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")


class FailingRunner(RecordingRunner):
    def __init__(self, failing_prefix: tuple[str, ...]) -> None:
        super().__init__()
        self.failing_prefix = failing_prefix

    def __call__(self, command):
        normalized = tuple(command)
        self.commands.append(normalized)
        returncode = 1 if normalized[: len(self.failing_prefix)] == self.failing_prefix else 0
        return subprocess.CompletedProcess(command, returncode, "", "simulated failure" if returncode else "")


def paths(tmp_path: Path) -> InstallPaths:
    return InstallPaths(
        hermes_home=tmp_path / "hermes",
        config_dir=tmp_path / "config" / "hermes-peek",
        state_dir=tmp_path / "state" / "hermes-peek",
        systemd_dir=tmp_path / "systemd",
    )


def test_setup_and_safe_uninstall_round_trip(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "bin" / "hermes-peek"
    executable.parent.mkdir()
    executable.write_text("launcher", encoding="utf-8")
    token = "123456789:" + "A" * 35
    runner = RecordingRunner()

    result = install(
        paths=target,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(allowed,),
        external_url="https://preview.example.test",
        bot_token=token,
        runner=runner,
    )

    assert result == {"installed": True, "activated": True, "state_preserved": True}
    assert (target.plugin_dir / "plugin.yaml").exists()
    assert (target.plugin_dir / "handler.py").exists()
    assert target.unit_file.exists() and target.env_file.exists() and target.manifest_file.exists()
    assert stat.S_IMODE(target.env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.manifest_file.stat().st_mode) == 0o600
    assert token in target.env_file.read_text(encoding="utf-8")
    assert token not in target.manifest_file.read_text(encoding="utf-8")
    assert str(executable.resolve()) in target.unit_file.read_text(encoding="utf-8")
    assert runner.commands == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "hermes-peek.service"),
        ("env", f"HERMES_HOME={target.hermes_home}", "hermes", "plugins", "enable", "--no-allow-tool-override", "hermes-peek"),
        ("env", f"HERMES_HOME={target.hermes_home}", "hermes", "gateway", "restart"),
    ]

    marker = target.state_dir / "keep.json"
    marker.write_text("{}", encoding="utf-8")
    removed = uninstall(paths=target, runner=runner)

    assert removed["uninstalled"] is True and removed["state_preserved"] is True
    assert not target.plugin_dir.exists()
    assert not target.unit_file.exists() and not target.env_file.exists()
    assert marker.exists()
    assert ("env", f"HERMES_HOME={target.hermes_home}", "hermes", "plugins", "disable", "hermes-peek") in runner.commands


def test_uninstall_purge_removes_state_and_is_idempotent(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.state_dir.mkdir(parents=True)
    (target.state_dir / "preview.json").write_text("{}", encoding="utf-8")

    first = uninstall(paths=target, purge_data=True, deactivate=False)
    second = uninstall(paths=target, purge_data=True, deactivate=False)

    assert first["data_purged"] is True and second["data_purged"] is True
    assert not target.state_dir.exists()
    assert not target.plugin_dir.exists()


def test_install_manifest_hashes_owned_plugin_files(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")

    install(
        paths=target,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(allowed,),
        external_url="https://preview.example.test/",
        bot_token="123456789:" + "B" * 35,
        activate=False,
    )

    manifest = json.loads(target.manifest_file.read_text(encoding="utf-8"))
    for name, digest in manifest["plugin_hashes"].items():
        assert digest == hashlib.sha256((target.plugin_dir / name).read_bytes()).hexdigest()


def test_read_bot_token_accepts_hermes_env_without_copying_other_secrets(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    token = "123456789:" + "C" * 35
    env.write_text(f'OTHER_SECRET=do-not-copy\nTELEGRAM_BOT_TOKEN="{token}"\n', encoding="utf-8")

    assert read_bot_token(env) == token


def test_setup_scopes_hermes_commands_to_selected_home(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")
    runner = RecordingRunner()

    install(
        paths=target,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(allowed,),
        external_url="https://preview.example.test",
        bot_token="123456789:" + "D" * 35,
        runner=runner,
    )

    hermes_commands = [command for command in runner.commands if "hermes" in command]
    assert hermes_commands
    assert all(f"HERMES_HOME={target.hermes_home}" in command for command in hermes_commands)


def test_manifest_records_stable_target_identity(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")

    install(
        paths=target,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(allowed,),
        external_url="https://preview.example.test",
        bot_token="123456789:" + "G" * 35,
        activate=False,
    )

    manifest = json.loads(target.manifest_file.read_text(encoding="utf-8"))
    assert manifest["target"] == {
        "hermes_home": str(target.hermes_home),
        "identity": hashlib.sha256(str(target.hermes_home).encode()).hexdigest(),
    }


def test_setup_writes_configuration_that_gateway_plugin_can_load(tmp_path: Path, monkeypatch) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")

    install(
        paths=target,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(allowed,),
        external_url="https://preview.example.test",
        bot_token="123456789:" + "E" * 35,
        activate=False,
    )

    monkeypatch.delenv("HERMES_PEEK_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("HERMES_PEEK_STATE_DIR", raising=False)
    monkeypatch.setenv("HERMES_PEEK_CONFIG_FILE", str(target.config_dir / "config.json"))
    from hermes_peek.hermes_plugin import _configured_roots

    assert _configured_roots() == (allowed.resolve(),)
    config_text = (target.config_dir / "config.json").read_text(encoding="utf-8")
    assert "123456789:" not in config_text
    assert target.env_file.name == "secrets.env"


def test_setup_rolls_back_files_when_plugin_enable_fails(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")
    runner = FailingRunner(("env", f"HERMES_HOME={target.hermes_home}", "hermes", "plugins", "enable"))

    with pytest.raises(LifecycleError):
        install(
            paths=target,
            integration_dir=PLUGIN,
            executable=executable,
            allowed_roots=(allowed,),
            external_url="https://preview.example.test",
            bot_token="123456789:" + "F" * 35,
            runner=runner,
        )

    assert not target.plugin_dir.exists()
    assert not target.unit_file.exists()
    assert not target.env_file.exists()
    assert not target.manifest_file.exists()
    journals = list((target.state_dir / "journal").glob("*.json"))
    assert journals and json.loads(journals[0].read_text())["state"] == "rolled_back"


def test_uninstall_keeps_resources_when_service_stop_fails(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.plugin_dir.mkdir(parents=True)
    (target.plugin_dir / "plugin.yaml").write_text("name: owned", encoding="utf-8")
    target.config_dir.mkdir(parents=True)
    target.env_file.write_text("secret", encoding="utf-8")
    target.manifest_file.write_text("{}", encoding="utf-8")
    target.systemd_dir.mkdir(parents=True)
    target.unit_file.write_text("unit", encoding="utf-8")
    runner = FailingRunner(("systemctl", "--user", "disable", "--now"))

    with pytest.raises(LifecycleError):
        uninstall(paths=target, runner=runner)

    assert target.plugin_dir.exists()
    assert target.unit_file.exists()
    assert target.env_file.exists()
    assert target.manifest_file.exists()


def test_uninstall_preserves_unowned_or_modified_plugin_directory(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.plugin_dir.mkdir(parents=True)
    user_file = target.plugin_dir / "user-not-owned.txt"
    user_file.write_text("do not delete", encoding="utf-8")

    with pytest.raises(LifecycleError):
        uninstall(paths=target, deactivate=False)

    assert user_file.exists()


def test_uninstall_backs_up_modified_owned_plugin(tmp_path: Path) -> None:
    target = paths(tmp_path)
    allowed = tmp_path / "workspace"; allowed.mkdir()
    executable = tmp_path / "hermes-peek"; executable.write_text("launcher")
    install(paths=target, integration_dir=PLUGIN, executable=executable,
            allowed_roots=(allowed,), external_url="https://preview.example.test",
            bot_token="123456789:" + "Z" * 35, activate=False)
    (target.plugin_dir / "handler.py").write_text("user modification")
    result = uninstall(paths=target, deactivate=False)
    assert result["modified_backups"]
    assert Path(result["modified_backups"][0]).read_text() == "user modification"


def test_purge_dry_run_has_zero_side_effects_and_reports_size(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.state_dir.mkdir(parents=True)
    data = target.state_dir / "registry.json"; data.write_bytes(b"1234")
    plan = plan_purge(target)
    assert plan["dry_run"] is True and plan["total_bytes"] == 4
    assert data.exists()


def test_purge_requires_confirmation_and_never_deletes_allowed_roots(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.state_dir.mkdir(parents=True)
    original = tmp_path / "workspace" / "source.txt"; original.parent.mkdir(); original.write_text("keep")
    with pytest.raises(LifecycleError):
        purge(target, confirmed=False)
    purge(target, confirmed=True)
    assert original.exists() and not target.state_dir.exists()


def test_purge_rejects_an_active_install_manifest(tmp_path: Path) -> None:
    target = paths(tmp_path)
    target.config_dir.mkdir(parents=True)
    target.manifest_file.write_text('{"schema_version": 1}', encoding="utf-8")

    with pytest.raises(LifecycleError, match="uninstall"):
        purge(target, confirmed=True)
