from __future__ import annotations

import json
from pathlib import Path

from hermes_peek.lifecycle import InstallPaths
from hermes_peek.setup_wizard import discover_installed_hermes_home, read_existing_setup, run_setup_wizard


def paths(tmp_path: Path) -> InstallPaths:
    return InstallPaths(tmp_path / "hermes", tmp_path / "config/hermes-peek", tmp_path / "state", tmp_path / "systemd")


def test_existing_setup_is_reused_for_single_field_patch(tmp_path, monkeypatch):
    import hermes_peek.cli as cli

    target = paths(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target.hermes_home.mkdir()
    (target.hermes_home / ".env").write_text("TELEGRAM_BOT_TOKEN=123456789:" + "X" * 35)
    target.config_dir.mkdir(parents=True)
    target.config_file.write_text(json.dumps({
        "allowed_roots": [str(workspace)],
        "external_base_url": "https://old.example.test/",
        "target": {"hermes_home": str(target.hermes_home)},
    }))
    captured = {}
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: target.hermes_home)
    monkeypatch.setattr(cli, "_paths_for_user", lambda home=None: target)
    monkeypatch.setattr(cli, "resolve_current_executable", lambda: tmp_path / "hermes-peek")
    monkeypatch.setattr(cli, "read_bot_token", lambda path: "123456789:" + "X" * 35)
    monkeypatch.setattr(cli, "install_application", lambda **kw: captured.update(kw) or {"installed": True})
    assert cli.main(["setup", "--external-url", "https://new.example.test", "--no-activate"]) == 0
    assert captured["allowed_roots"] == (workspace.resolve(),)
    assert captured["external_url"] == "https://new.example.test"
    assert captured["paths"].hermes_home == target.hermes_home


def test_discover_installed_home_prefers_manifest(tmp_path, monkeypatch):
    config_home = tmp_path / "config"
    directory = config_home / "hermes-peek"
    directory.mkdir(parents=True)
    expected = tmp_path / "custom-hermes"
    (directory / "install.json").write_text(json.dumps({"target": {"hermes_home": str(expected)}}))
    assert discover_installed_hermes_home(config_home=config_home) == expected.resolve()


def test_interactive_wizard_prefills_existing_values(tmp_path):
    target = paths(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    answers = iter(["", ""])
    result = run_setup_wizard(
        target,
        input_fn=lambda prompt: next(answers),
        output_fn=lambda message: None,
        https_probe=lambda url: {"reachable": True},
        existing={"allowed_roots": (workspace,), "external_url": "https://preview.example.test"},
    )
    assert result["allowed_roots"] == (workspace.resolve(),)
    assert result["external_url"] == "https://preview.example.test"


def test_interactive_setup_only_prompts_for_value_missing_from_arguments(tmp_path, monkeypatch):
    import hermes_peek.cli as cli

    target = paths(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompts = []
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: target.hermes_home)
    monkeypatch.setattr(cli, "_paths_for_user", lambda home=None: target)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "https://preview.example.test")

    assert cli.main(["setup", "--allowed-root", str(workspace), "--plan"]) == 0
    assert prompts == ["External HTTPS origin []: "]


def test_interactive_setup_does_not_overwrite_explicit_external_url(tmp_path, monkeypatch):
    import hermes_peek.cli as cli

    target = paths(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompts = []
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: target.hermes_home)
    monkeypatch.setattr(cli, "_paths_for_user", lambda home=None: target)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or str(workspace))

    assert cli.main(["setup", "--external-url", "https://preview.example.test", "--plan"]) == 0
    assert prompts == ["Allowed preview directories (comma-separated) []: "]


def test_partial_setup_arguments_fail_clearly_without_tty(tmp_path, monkeypatch, capsys):
    import hermes_peek.cli as cli

    target = paths(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(cli, "discover_installed_hermes_home", lambda: target.hermes_home)
    monkeypatch.setattr(cli, "_paths_for_user", lambda home=None: target)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    assert cli.main(["setup", "--allowed-root", str(workspace), "--plan"]) == 2
    error = capsys.readouterr().err
    assert "setup requires --external-url in non-interactive mode" in error
    assert "EOFError" not in error


def test_update_parser_supports_public_command_and_alias():
    from hermes_peek.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["update", "--check"]).command == "update"
    assert parser.parse_args(["upgrade", "--plan"]).command == "upgrade"
