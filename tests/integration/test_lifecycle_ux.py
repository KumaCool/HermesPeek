import json
import subprocess
from pathlib import Path

from hermes_peek.cli import main
from hermes_peek.lifecycle import InstallPaths

class Runner:
    def __init__(self): self.commands=[]
    def __call__(self, command):
        self.commands.append(tuple(command)); return subprocess.CompletedProcess(command, 0, "log line\n", "")

class MatrixRunner:
    def __init__(self): self.commands=[]
    def __call__(self, command):
        command=tuple(command); self.commands.append(command); joined=" ".join(command)
        if "is-active" in command or "is-enabled" in command: return subprocess.CompletedProcess(command,0,"active\n","")
        if "--property=MainPID" in command: return subprocess.CompletedProcess(command,0,"321\n","")
        if "plugins list --json" in joined: return subprocess.CompletedProcess(command,0,json.dumps([{"name":"hermes-peek","status":"enabled"}]),"")
        if "gateway status" in joined: return subprocess.CompletedProcess(command,0,"active","")
        return subprocess.CompletedProcess(command,0,"","")

def test_status_and_doctor_are_read_only_and_redacted(tmp_path, capsys):
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    paths.config_dir.mkdir(); paths.manifest_file.write_text(json.dumps({"target":{"hermes_home":str(paths.hermes_home)},"plugin_hashes":{}}))
    from hermes_peek.lifecycle_ux import status, doctor
    runner=Runner(); report=status(paths, runner); diagnosis=doctor(paths, runner)
    assert report["schema_version"] == 1 and "token" not in json.dumps(report).lower()
    assert diagnosis["checks"] and all("start" not in " ".join(c) for c in runner.commands)


def test_status_schema_covers_manifest_health_plugin_gateway_telegram_https_and_drift(tmp_path):
    paths=InstallPaths(tmp_path/"hermes",tmp_path/"config",tmp_path/"state",tmp_path/"systemd")
    paths.plugin_dir.mkdir(parents=True); plugin=paths.plugin_dir/"plugin.yaml"; plugin.write_text("owned")
    paths.config_dir.mkdir(parents=True); paths.config_file.write_text(json.dumps({"external_base_url":"https://preview.example.test/"}))
    paths.manifest_file.write_text(json.dumps({"schema_version":2,"transaction_id":"abc","target":{"identity":"bad"},
        "owned_resources":[{"path":str(plugin),"sha256":"wrong"}]}))
    from hermes_peek.lifecycle_ux import status
    runner=MatrixRunner(); report=status(paths,runner,
        port_probe=lambda h,p:{"listening":True,"address":"127.0.0.1:8765","pid":321},
        health_probe=lambda u:{"ok":True,"status":200},
        https_probe=lambda u:{"reachable":True,"status":200},
        telegram_probe=lambda:{"verified":True,"main_mini_app_requires_botfather":True})
    assert set(report) == {"schema_version","target","manifest","transaction","service","plugin","gateway","telegram","https","drift","data"}
    assert report["service"]["health"]["ok"] and report["plugin"]["loaded"] and report["gateway"]["active"]
    assert report["drift"]["detected"] is True and report["telegram"]["verified"] is True
    assert all(word not in json.dumps(report).lower() for word in ("preview_id","bot_token","connection_key"))


def test_doctor_matrix_has_named_checks_and_actionable_suggestions(tmp_path):
    from hermes_peek.lifecycle_ux import doctor
    paths=InstallPaths(tmp_path/"hermes",tmp_path/"config",tmp_path/"state",tmp_path/"systemd")
    report=doctor(paths,MatrixRunner(),port_probe=lambda h,p:{"listening":False,"address":None,"pid":None},
                  health_probe=lambda u:{"ok":False,"status":None},https_probe=lambda u:{"reachable":False,"status":None},
                  telegram_probe=lambda:{"verified":False,"main_mini_app_requires_botfather":True})
    names={check["name"] for check in report["checks"]}
    assert {"manifest","service_health","plugin_loaded","gateway","telegram","https","config_drift"} <= names
    assert report["suggestions"] and all(isinstance(item,str) for item in report["suggestions"])


def test_doctor_layers_telegram_onboarding_evidence_without_claiming_botfather_acceptance(tmp_path):
    from hermes_peek.lifecycle_ux import doctor
    paths=InstallPaths(tmp_path/"hermes",tmp_path/"config",tmp_path/"state",tmp_path/"systemd")
    paths.hermes_home.mkdir(); (paths.hermes_home/".env").write_text(
        "TELEGRAM_BOT_TOKEN=fake-token\nTELEGRAM_ALLOWED_USERS=1001\n"
    ); (paths.hermes_home/".env").chmod(0o600)
    paths.config_dir.mkdir(); paths.config_file.write_text(json.dumps({
        "external_base_url":"https://preview.example.test",
        "telegram_bot_username":"peek_bot",
        "telegram_mini_app_short_name":"named_app",
    }))
    report=doctor(paths,MatrixRunner(),
        port_probe=lambda h,p:{"listening":True,"address":"127.0.0.1:8765","pid":321},
        health_probe=lambda u:{"ok":True,"status":200},
        https_probe=lambda u:{"reachable":True,"status":200,"configured":True},
        telegram_probe=lambda:{"verified":True,"identity_verified":True,"bot_id":7,
            "bot_username":"peek_bot","webhook":{"configured":False,"pending_update_count":0,
            "last_error_present":False},"main_mini_app_requires_botfather":True})
    onboarding=report["telegram_onboarding"]
    assert onboarding["token_file"] == {"readable": True, "permissions_restricted": True}
    assert onboarding["allowed_users"]["configured"] is True
    assert onboarding["identity"]["status"] == "verified"
    assert onboarding["configuration_evidence"]["status"] == "reliable"
    assert onboarding["main_mini_app"]["direct_link_constructable"] is True
    assert onboarding["main_mini_app"]["short_name"] == "named_app"
    assert onboarding["main_mini_app"]["url_match"] == "unverified"
    assert onboarding["main_mini_app"]["telegram_client_acceptance"] == "pending"
    assert onboarding["main_mini_app"]["botfather_configured"] == "not_inferable"


def test_doctor_blocks_missing_allowed_users_with_official_hermes_configuration_link(tmp_path):
    from hermes_peek.lifecycle_ux import doctor
    paths=InstallPaths(tmp_path/"hermes",tmp_path/"config",tmp_path/"state",tmp_path/"systemd")
    paths.hermes_home.mkdir(); (paths.hermes_home/".env").write_text("TELEGRAM_BOT_TOKEN=fake-token\n")
    report=doctor(paths,MatrixRunner(),telegram_probe=lambda:{"verified":True,"bot_username":"peek_bot"})
    allowed=report["telegram_onboarding"]["allowed_users"]
    assert allowed["status"] == "blocking"
    assert allowed["configured"] is False
    assert allowed["configure_with"] == "hermes gateway setup"
    assert allowed["documentation"].startswith("https://hermes-agent.nousresearch.com/")

def test_cli_exposes_status_doctor_and_service_commands():
    from hermes_peek.cli import build_parser
    parser=build_parser()
    assert parser.parse_args(["status", "--json"]).command == "status"
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["doctor", "--json"]).json is True
    assert parser.parse_args(["service", "restart"]).action == "restart"
    purge = parser.parse_args(["uninstall", "--purge", "--dry-run"])
    assert purge.purge is True and purge.dry_run is True and purge.yes is False
    assert parser.parse_args(["setup","--allowed-root","/tmp","--external-url","https://example.test","--plan"]).plan is True


def test_cli_service_stop_verifies_process_and_port_exit(monkeypatch, capsys):
    import hermes_peek.cli as cli
    calls = []
    monkeypatch.setattr(cli.SystemdUserBackend, "stop", lambda self: calls.append("stop"))
    monkeypatch.setattr(cli.SystemdUserBackend, "verify_stopped", lambda self: calls.append("verify"))
    assert main(["service", "stop"]) == 0
    assert calls == ["stop", "verify"]


def test_cli_exposes_rollback_command():
    from hermes_peek.cli import build_parser
    args = build_parser().parse_args(["rollback", "a" * 32, "--hermes-home", "/tmp/hermes"])
    assert args.command == "rollback" and args.transaction_id == "a" * 32


def test_rollback_cli_invokes_transaction_rollback(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    calls = []
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    monkeypatch.setattr(cli, "rollback_transaction", lambda p, txn, runner: calls.append((p, txn)) or {"rolled_back": True})
    assert main(["rollback", "a" * 32]) == 0
    assert calls == [(paths, "a" * 32)]


def test_setup_cli_constructs_telegram_lifecycle_and_inspects_bot(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    allowed = tmp_path/"workspace"; allowed.mkdir(); executable = tmp_path/"hermes-peek"; executable.write_text("x")
    env = tmp_path/"telegram.env"; env.write_text("TELEGRAM_BOT_TOKEN=123456789:" + "X" * 35)
    captured = {}
    class Telegram:
        def __init__(self, transport): captured["transport"] = transport
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(cli, "TelegramLifecycle", Telegram)
    monkeypatch.setattr(cli, "telegram_lifecycle_transport", lambda: "transport")
    monkeypatch.setattr(cli, "install_application", lambda **kw: captured.update(kw) or {"installed": True})
    assert main(["setup", "--allowed-root", str(allowed), "--external-url", "https://preview.example.test",
                 "--telegram-env", str(env), "--no-activate"]) == 0
    assert captured["telegram"].__class__ is Telegram and captured["transport"] == "transport"
    assert captured["runner"] is cli.lifecycle_runner


def test_setup_outputs_owner_onboarding_checklist_without_claiming_menu_registers_main_app(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    allowed = tmp_path/"workspace"; allowed.mkdir(); executable = tmp_path/"hermes-peek"; executable.write_text("x")
    env = tmp_path/"telegram.env"; env.write_text("TELEGRAM_BOT_TOKEN=fake-token")
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(cli, "read_bot_token", lambda path: "fake-token")
    monkeypatch.setattr(cli, "install_application", lambda **kw: {"installed": True})
    assert main(["setup", "--allowed-root", str(allowed), "--external-url", "https://preview.example.test",
                 "--telegram-env", str(env), "--telegram-bot-username", "peek_bot", "--no-activate"]) == 0
    result=json.loads(capsys.readouterr().out)
    checklist=result["telegram_onboarding_checklist"]
    assert {item["scope"] for item in checklist} == {"botfather", "private_chat", "group", "forum_topic"}
    botfather=next(item for item in checklist if item["scope"] == "botfather")
    assert botfather["status"] == "pending_owner_action"
    assert botfather["menu_button_is_not_main_mini_app_registration"] is True


def test_gateway_session_detection_uses_systemd_cgroup(monkeypatch):
    import hermes_peek.cli as cli
    monkeypatch.delenv("HERMES_SESSION_PLATFORM", raising=False)
    monkeypatch.setattr(cli.Path, "read_text", lambda self, **kw: "0::/user.slice/app.slice/hermes-gateway.service")
    assert cli._running_inside_gateway_session() is True


def test_gateway_session_detection_prefers_exported_session_marker(monkeypatch):
    import hermes_peek.cli as cli
    import sys
    from types import SimpleNamespace
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "telegram")
    monkeypatch.setattr(cli.Path, "read_text", lambda self, **kw: "0::/")
    monkeypatch.setitem(sys.modules, "gateway.session_context", SimpleNamespace(get_session_env=lambda key, default: default))

    assert cli._running_inside_gateway_session() is True


def test_default_https_probe_is_read_only_and_redacted(monkeypatch):
    import hermes_peek.lifecycle_ux as ux
    class Response:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *args): pass
    seen = []
    monkeypatch.setattr(ux.urllib.request, "urlopen", lambda request, timeout: seen.append((request.full_url, request.method)) or Response())
    assert ux._https_probe("https://preview.example.test/") == {"reachable": True, "status": 204, "configured": True}
    assert seen == [("https://preview.example.test/healthz", "HEAD")]


def test_default_telegram_probe_reads_installed_token_and_redacts_failure(tmp_path, monkeypatch):
    import hermes_peek.lifecycle_ux as ux
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    paths.config_dir.mkdir(); token = "123456789:" + "X" * 35; paths.env_file.write_text(f'HERMES_PEEK_TELEGRAM_BOT_TOKEN="{token}"')
    class Lifecycle:
        def __init__(self, transport): pass
        def inspect(self, value): assert value == token; return {"bot_id": 7}
    monkeypatch.setattr(ux, "TelegramLifecycle", Lifecycle)
    assert ux._telegram_probe(paths) == {"verified": True, "bot_id": 7}


def test_setup_plan_is_read_only_redacted_and_lists_actions(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths=InstallPaths(tmp_path/"hermes",tmp_path/"config",tmp_path/"state",tmp_path/"systemd")
    allowed=tmp_path/"workspace"; allowed.mkdir(); token_file=tmp_path/"telegram.env"; token="123456789:"+"X"*35; token_file.write_text(f"TELEGRAM_BOT_TOKEN={token}")
    monkeypatch.setattr(cli.InstallPaths,"for_user",classmethod(lambda cls,**kw:paths))
    calls=[]; monkeypatch.setattr(cli,"lifecycle_runner",lambda command:(calls.append(tuple(command)) or subprocess.CompletedProcess(command,1,"","")))
    assert main(["setup","--allowed-root",str(allowed),"--external-url","https://preview.example.test","--telegram-env",str(token_file),"--plan"]) == 0
    report=json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True and report["actions"] and report["rollback_points"]
    assert token not in json.dumps(report)
    assert all(not any(word in command for word in ("enable","restart","start")) for command in calls)


def test_status_cli_outputs_stable_json_without_service_side_effects(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    commands = []
    monkeypatch.setattr(cli, "lifecycle_runner", lambda command: (commands.append(tuple(command)) or subprocess.CompletedProcess(command, 1, "", "")))
    assert main(["status", "--json", "--hermes-home", str(tmp_path / "hermes")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 1
    assert all("start" not in command and "restart" not in command for command in commands)


def test_uninstall_purge_dry_run_cli_has_zero_side_effects(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    config = tmp_path / "config"; state = tmp_path / "state"; systemd = tmp_path / "systemd"
    paths = InstallPaths(tmp_path/"hermes", config, state, systemd)
    state.mkdir(); marker = state / "registry.json"; marker.write_text("keep")
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    assert main(["uninstall", "--purge", "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True and marker.exists()


def test_uninstall_purge_requires_yes_in_noninteractive_mode(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    paths.state_dir.mkdir(parents=True); marker = paths.state_dir / "registry.json"; marker.write_text("keep")
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert main(["uninstall", "--purge"]) == 2
    assert marker.exists() and "--yes" in capsys.readouterr().err


def test_uninstall_purge_runs_default_uninstall_before_delete(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    paths.state_dir.mkdir(parents=True); paths.config_dir.mkdir(parents=True)
    paths.manifest_file.write_text("{}")
    calls=[]
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kw: paths))
    def fake_uninstall(**kwargs): calls.append("uninstall"); paths.manifest_file.unlink(); return {"uninstalled":True}
    def fake_purge(paths, *, confirmed): calls.append("purge"); return {"purged":True}
    monkeypatch.setattr(cli, "uninstall_application", fake_uninstall)
    monkeypatch.setattr(cli, "purge_application", fake_purge)
    monkeypatch.setattr(cli, "_remove_uv_tool", lambda: (True, "已通过 uv tool 删除"))
    assert main(["uninstall", "--purge", "--yes"]) == 0
    assert calls == ["uninstall", "purge"]
    output = capsys.readouterr().out
    assert "HermesPeek 卸载成功" in output
    assert "已通过 uv tool 删除" in output
    assert "original_files_preserved" not in output
