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
        if "plugins status" in joined: return subprocess.CompletedProcess(command,0,json.dumps({"enabled":True,"loaded":True}),"")
        if "gateway status" in joined: return subprocess.CompletedProcess(command,0,json.dumps({"active":True}),"")
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

def test_cli_exposes_status_doctor_and_service_commands():
    from hermes_peek.cli import build_parser
    parser=build_parser()
    assert parser.parse_args(["status", "--json"]).command == "status"
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["service", "restart"]).action == "restart"
    purge = parser.parse_args(["uninstall", "--purge", "--dry-run"])
    assert purge.purge is True and purge.dry_run is True and purge.yes is False
    assert parser.parse_args(["setup","--allowed-root","/tmp","--external-url","https://example.test","--plan"]).plan is True


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
    assert main(["uninstall", "--purge", "--yes"]) == 0
    assert calls == ["uninstall", "purge"]
