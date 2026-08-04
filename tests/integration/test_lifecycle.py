from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from hermes_peek.lifecycle import LifecycleError, InstallPaths, install, read_bot_token, rollback_transaction, uninstall
from hermes_peek.lifecycle import plan_purge, purge
from hermes_peek.telegram_lifecycle import TelegramLifecycle


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


class StatefulRunner(RecordingRunner):
    def __init__(self, *, fail_gateway_restart: bool = False) -> None:
        super().__init__()
        self.service_active = False
        self.service_enabled = False
        self.plugin_enabled = False
        self.gateway_active = True
        self.fail_gateway_restart = fail_gateway_restart

    def __call__(self, command):
        command = tuple(command); self.commands.append(command)
        joined = " ".join(command)
        if "is-active" in command:
            return subprocess.CompletedProcess(command, 0 if self.service_active else 3, "active\n" if self.service_active else "inactive\n", "")
        if "is-enabled" in command:
            return subprocess.CompletedProcess(command, 0 if self.service_enabled else 1, "enabled\n" if self.service_enabled else "disabled\n", "")
        if "plugins status hermes-peek" in joined:
            return subprocess.CompletedProcess(command, 0, json.dumps({"enabled": self.plugin_enabled}), "")
        if "gateway status" in joined:
            return subprocess.CompletedProcess(command, 0, json.dumps({"active": self.gateway_active}), "")
        if command[-3:] == ("enable", "--now", "hermes-peek.service"):
            self.service_enabled = self.service_active = True
        elif command[-3:] == ("disable", "--now", "hermes-peek.service"):
            self.service_enabled = self.service_active = False
        elif "plugins enable" in joined:
            self.plugin_enabled = True
        elif "plugins disable" in joined:
            self.plugin_enabled = False
        elif "gateway restart" in joined and self.fail_gateway_restart:
            self.fail_gateway_restart = False
            return subprocess.CompletedProcess(command, 1, "", "simulated gateway failure")
        return subprocess.CompletedProcess(command, 0, "", "")


class FakeServiceBackend:
    def __init__(self, runner): self.runner = runner
    def preflight(self): return None
    def verify_running(self):
        if isinstance(self.runner, StatefulRunner):
            self.runner.service_enabled = self.runner.service_active = True
        return {"active": True, "enabled": True}


class SetupTelegramTransport:
    def __init__(self, *, fail_set=False): self.calls=[]; self.menu={"type":"default"}; self.fail_set=fail_set
    def call(self, method, token, payload=None):
        self.calls.append((method,payload))
        if method == "getMe": return {"ok":True,"result":{"id":7,"username":"peek_bot"}}
        if method == "getWebhookInfo": return {"ok":True,"result":{"url":""}}
        if method == "getChatMenuButton": return {"ok":True,"result":self.menu}
        if method == "setChatMenuButton":
            if self.fail_set: return {"ok":False,"description":"contains secret"}
            self.menu=payload["menu_button"]; return {"ok":True,"result":True}
        raise AssertionError(method)


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
        service_backend=FakeServiceBackend(runner),
    )

    assert result["installed"] is True and result["activated"] is True
    assert result["state_preserved"] is True and result["transaction_id"]
    assert (target.plugin_dir / "plugin.yaml").exists()
    assert (target.plugin_dir / "handler.py").exists()
    assert target.unit_file.exists() and target.env_file.exists() and target.manifest_file.exists()
    assert stat.S_IMODE(target.env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.manifest_file.stat().st_mode) == 0o600
    assert token in target.env_file.read_text(encoding="utf-8")
    assert token not in target.manifest_file.read_text(encoding="utf-8")
    assert str(executable.resolve()) in target.unit_file.read_text(encoding="utf-8")
    assert runner.commands[-4:] == [
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
    owned = {entry["path"]: entry for entry in manifest["owned_resources"]}
    for path in (target.env_file, target.config_file, target.unit_file):
        assert owned[str(path)]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert owned[str(path)]["transaction_id"] == manifest["transaction_id"]


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
        service_backend=FakeServiceBackend(runner),
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
            service_backend=FakeServiceBackend(runner),
        )

    assert not target.plugin_dir.exists()
    assert not target.unit_file.exists()
    assert not target.env_file.exists()
    assert not target.manifest_file.exists()
    journals = list((target.state_dir / "journal").glob("*.json"))
    assert journals and json.loads(journals[0].read_text())["state"] == "rolled_back"


def test_setup_failure_restores_service_plugin_and_gateway_state(tmp_path: Path) -> None:
    target = paths(tmp_path); allowed = tmp_path / "workspace"; allowed.mkdir()
    executable = tmp_path / "hermes-peek"; executable.write_text("launcher")
    runner = StatefulRunner(fail_gateway_restart=True)

    with pytest.raises(LifecycleError, match="transaction"):
        install(paths=target, integration_dir=PLUGIN, executable=executable,
                allowed_roots=(allowed,), external_url="https://preview.example.test",
                bot_token="123456789:" + "R" * 35, runner=runner,
                service_backend=FakeServiceBackend(runner))

    assert runner.service_active is False
    assert runner.service_enabled is False
    assert runner.plugin_enabled is False
    journal = json.loads(next((target.state_dir / "journal").glob("*.json")).read_text())
    assert journal["state"] == "rolled_back" and journal["rollback_errors"] == []
    assert journal["before"]["gateway_active"] is True


def test_committed_transaction_can_be_rolled_back_by_id(tmp_path: Path) -> None:
    target = paths(tmp_path); allowed = tmp_path / "workspace"; allowed.mkdir()
    executable = tmp_path / "hermes-peek"; executable.write_text("launcher")
    runner = StatefulRunner()
    result = install(paths=target, integration_dir=PLUGIN, executable=executable,
                     allowed_roots=(allowed,), external_url="https://preview.example.test",
                     bot_token="123456789:" + "S" * 35, runner=runner,
                     service_backend=FakeServiceBackend(runner))

    rolled_back = rollback_transaction(target, result["transaction_id"], runner=runner)

    assert rolled_back["rolled_back"] is True
    assert not target.manifest_file.exists() and not target.plugin_dir.exists()
    assert runner.service_active is False and runner.plugin_enabled is False


def test_setup_validates_and_records_telegram_change_in_transaction(tmp_path: Path) -> None:
    target=paths(tmp_path); allowed=tmp_path/"workspace"; allowed.mkdir(); executable=tmp_path/"hermes-peek"; executable.write_text("x")
    transport=SetupTelegramTransport(); telegram=TelegramLifecycle(transport)
    result=install(paths=target,integration_dir=PLUGIN,executable=executable,allowed_roots=(allowed,),
                   external_url="https://preview.example.test",bot_token="123456789:"+"V"*35,
                   activate=False,telegram=telegram,configure_telegram_menu=True,expected_bot_id=7)
    journal=json.loads((target.state_dir/"journal"/f'{result["transaction_id"]}.json').read_text())
    assert [call[0] for call in transport.calls[:3]] == ["getMe","getWebhookInfo","getChatMenuButton"]
    assert journal["telegram_changes"][0]["before"] == {"type":"default"}


def test_later_setup_failure_conditionally_restores_telegram_menu(tmp_path: Path) -> None:
    target=paths(tmp_path); allowed=tmp_path/"workspace"; allowed.mkdir(); executable=tmp_path/"hermes-peek"; executable.write_text("x")
    transport=SetupTelegramTransport(); telegram=TelegramLifecycle(transport)
    def fail_verify(): raise RuntimeError("simulated final verification failure")
    with pytest.raises(LifecycleError):
        install(paths=target,integration_dir=PLUGIN,executable=executable,allowed_roots=(allowed,),
                external_url="https://preview.example.test",bot_token="123456789:"+"W"*35,
                activate=False,telegram=telegram,configure_telegram_menu=True,expected_bot_id=7,
                final_verify=fail_verify)
    assert transport.menu == {"type":"default"}


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


def test_uninstall_backs_up_modified_config_and_refuses_manifest_target_mismatch(tmp_path: Path) -> None:
    target = paths(tmp_path); allowed = tmp_path / "workspace"; allowed.mkdir()
    executable = tmp_path / "hermes-peek"; executable.write_text("launcher")
    install(paths=target, integration_dir=PLUGIN, executable=executable,
            allowed_roots=(allowed,), external_url="https://preview.example.test",
            bot_token="123456789:" + "U" * 35, activate=False)
    target.config_file.write_text('{"user":"change"}')
    result = uninstall(paths=target, deactivate=False)
    assert any(Path(item).name == "config.json" for item in result["modified_backups"])

    other = paths(tmp_path / "other"); other.plugin_dir.mkdir(parents=True)
    other.config_dir.mkdir(parents=True); other.manifest_file.write_text(json.dumps({"schema_version":2,"target":{"identity":"wrong"},"owned_resources":[]}))
    with pytest.raises(LifecycleError, match="target"):
        uninstall(paths=other, deactivate=False)


def test_uninstall_refuses_symlink_owned_resource_without_following_it(tmp_path: Path) -> None:
    target = paths(tmp_path); target.config_dir.mkdir(parents=True)
    outside = tmp_path / "outside"; outside.write_text("keep")
    target.env_file.symlink_to(outside)
    target.manifest_file.write_text(json.dumps({"schema_version":2,
        "target":{"identity": hashlib.sha256(str(target.hermes_home.resolve()).encode()).hexdigest()},
        "owned_resources":[{"path":str(target.env_file),"type":"file","sha256":"x","transaction_id":"t"}]}))
    with pytest.raises(LifecycleError, match="symlink"):
        uninstall(paths=target, deactivate=False)
    assert outside.read_text() == "keep"


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
