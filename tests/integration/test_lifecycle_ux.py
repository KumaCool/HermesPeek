import json
import subprocess
from pathlib import Path

from hermes_peek.cli import main
from hermes_peek.lifecycle import InstallPaths

class Runner:
    def __init__(self): self.commands=[]
    def __call__(self, command):
        self.commands.append(tuple(command)); return subprocess.CompletedProcess(command, 0, "log line\n", "")

def test_status_and_doctor_are_read_only_and_redacted(tmp_path, capsys):
    paths = InstallPaths(tmp_path/"hermes", tmp_path/"config", tmp_path/"state", tmp_path/"systemd")
    paths.config_dir.mkdir(); paths.manifest_file.write_text(json.dumps({"target":{"hermes_home":str(paths.hermes_home)},"plugin_hashes":{}}))
    from hermes_peek.lifecycle_ux import status, doctor
    runner=Runner(); report=status(paths, runner); diagnosis=doctor(paths, runner)
    assert report["schema_version"] == 1 and "token" not in json.dumps(report).lower()
    assert diagnosis["checks"] and all("start" not in " ".join(c) for c in runner.commands)

def test_cli_exposes_status_doctor_and_service_commands():
    from hermes_peek.cli import build_parser
    parser=build_parser()
    assert parser.parse_args(["status", "--json"]).command == "status"
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["service", "restart"]).action == "restart"


def test_status_cli_outputs_stable_json_without_service_side_effects(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli
    commands = []
    monkeypatch.setattr(cli, "lifecycle_runner", lambda command: (commands.append(tuple(command)) or subprocess.CompletedProcess(command, 1, "", "")))
    assert main(["status", "--json", "--hermes-home", str(tmp_path / "hermes")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 1
    assert all("start" not in command and "restart" not in command for command in commands)
