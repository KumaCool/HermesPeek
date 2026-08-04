from __future__ import annotations

import json
from pathlib import Path

from hermes_peek.lifecycle import InstallPaths, install, purge, uninstall
from hermes_peek.lifecycle_ux import status


ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "src" / "hermes_peek" / "hermes_plugin"


class ReadOnlyRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command):
        import subprocess

        normalized = tuple(command)
        self.commands.append(normalized)
        return subprocess.CompletedProcess(command, 1, "", "isolated fake backend")


def make_paths(root: Path, profile: str) -> InstallPaths:
    return InstallPaths(
        hermes_home=root / "profiles" / profile,
        config_dir=root / "config" / profile,
        state_dir=root / "state" / profile,
        systemd_dir=root / "systemd" / profile,
    )


def install_offline(paths: InstallPaths, workspace: Path, executable: Path) -> dict[str, object]:
    return install(
        paths=paths,
        integration_dir=PLUGIN,
        executable=executable,
        allowed_roots=(workspace,),
        external_url="https://preview.example.test",
        bot_token="123456789:" + "E" * 35,
        activate=False,
    )


def test_isolated_profile_lifecycle_and_purge_preserve_user_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "index.html"
    source.write_text("<h1>keep</h1>", encoding="utf-8")
    executable = tmp_path / "bin" / "hermes-peek"
    executable.parent.mkdir()
    executable.write_text("launcher", encoding="utf-8")
    profile_a = make_paths(tmp_path, "a")
    profile_b = make_paths(tmp_path, "b")

    result = install_offline(profile_a, workspace, executable)

    assert result["installed"] is True
    assert profile_a.manifest_file.is_file()
    assert not profile_b.config_dir.exists()
    runner = ReadOnlyRunner()
    report = status(profile_a, runner)
    assert report["manifest"]["present"] is True
    assert all("enable" not in command and "restart" not in command for command in runner.commands)

    uninstall(paths=profile_a, deactivate=False)
    assert profile_a.state_dir.is_dir()
    reinstall = install_offline(profile_a, workspace, executable)
    assert reinstall["installed"] is True
    uninstall(paths=profile_a, deactivate=False)
    plan = __import__("hermes_peek.lifecycle", fromlist=["plan_purge"]).plan_purge(profile_a)
    assert plan["dry_run"] is True and source.is_file()
    purge(profile_a, confirmed=True)

    assert not profile_a.state_dir.exists()
    assert not profile_a.config_dir.exists()
    assert source.read_text(encoding="utf-8") == "<h1>keep</h1>"
    assert not profile_b.hermes_home.exists()


def test_isolated_manifest_never_contains_bot_token(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher", encoding="utf-8")
    paths = make_paths(tmp_path, "a")

    install_offline(paths, workspace, executable)

    manifest = json.loads(paths.manifest_file.read_text(encoding="utf-8"))
    assert "token" not in json.dumps(manifest).lower()
