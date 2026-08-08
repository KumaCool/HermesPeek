from __future__ import annotations

from pathlib import Path

import pytest

from hermes_peek.cli import build_parser, main
from hermes_peek.lifecycle import LifecycleError


def test_setup_accepts_no_arguments_but_fails_fast_without_tty(monkeypatch, capsys):
    args = build_parser().parse_args(["setup"])
    assert args.allowed_root is None
    assert args.external_url is None

    monkeypatch.setattr("hermes_peek.cli.sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("hermes_peek.cli.discover_installed_hermes_home", lambda: None)
    monkeypatch.setattr("hermes_peek.cli.discover_hermes_profiles", lambda home: ())
    monkeypatch.setattr("hermes_peek.cli.read_existing_setup", lambda paths: {})

    assert main(["setup"]) == 2
    assert "first setup requires --allowed-root and --external-url" in capsys.readouterr().err


def test_profile_discovery_selects_single_profile_and_requires_explicit_choice(tmp_path: Path):
    from hermes_peek.setup_wizard import discover_hermes_profiles, select_hermes_profile

    default = tmp_path / ".hermes"
    profile = default / "profiles" / "work"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("model: fixture\n")

    assert discover_hermes_profiles(default) == (profile.resolve(),)
    assert select_hermes_profile((profile,), input_fn=lambda _: pytest.fail("must not prompt")) == profile.resolve()

    default.mkdir(exist_ok=True)
    with pytest.raises(LifecycleError, match="explicit profile selection"):
        select_hermes_profile((default, profile), input_fn=lambda _: "")


def test_profile_discovery_uses_root_as_default_and_ignores_default_state_directory(tmp_path: Path):
    from hermes_peek.setup_wizard import discover_hermes_profiles, select_hermes_profile

    root = tmp_path / ".hermes"
    root.mkdir()
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=fixture")
    pseudo_default = root / "profiles" / "default"
    pseudo_default.mkdir(parents=True)
    (pseudo_default / "pairing").mkdir()
    heavy = root / "profiles" / "heavy"
    heavy.mkdir()
    (heavy / "config.yaml").write_text("model: fixture\n")
    prompts: list[str] = []

    profiles = discover_hermes_profiles(root)

    assert profiles == (root.resolve(), heavy.resolve())
    assert select_hermes_profile(
        profiles, input_fn=lambda prompt: prompts.append(prompt) or "1"
    ) == root.resolve()
    assert "1. default" in prompts[0]
    assert "profiles/default" not in prompts[0]


def test_setup_inputs_reject_unsafe_roots_and_invalid_external_base_urls(tmp_path: Path):
    from hermes_peek.setup_wizard import validate_allowed_roots, validate_https_origin

    home = tmp_path / "home"
    home.mkdir()
    safe = home / "workspace"
    safe.mkdir()
    secret = home / ".ssh"
    secret.mkdir()
    link = home / "linked"
    link.symlink_to(safe, target_is_directory=True)

    assert validate_allowed_roots((safe,), home=home) == (safe.resolve(),)
    for unsafe in (Path("/"), home, secret, link):
        with pytest.raises(LifecycleError, match="allowed root"):
            validate_allowed_roots((unsafe,), home=home)

    assert validate_https_origin("https://preview.example.test") == "https://preview.example.test/"
    assert validate_https_origin("https://preview.example.test/hermespeek") == (
        "https://preview.example.test/hermespeek/"
    )
    for invalid in (
        "http://preview.example.test",
        "https://user@preview.example.test",
        "https://preview.example.test?secret=value",
        "https://preview.example.test/#fragment",
        "https://preview.example.test//hermespeek",
        "https://preview.example.test/hermes%70eek",
    ):
        with pytest.raises(LifecycleError, match="external URL"):
            validate_https_origin(invalid)


def test_wizard_checks_https_and_continues_without_plan_or_confirmation(tmp_path: Path):
    from hermes_peek.lifecycle import InstallPaths
    from hermes_peek.setup_wizard import run_setup_wizard

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    token = "123456789:" + "S" * 35
    (hermes_home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = InstallPaths(hermes_home, tmp_path / "config", tmp_path / "state", tmp_path / "systemd")
    answers = iter((str(workspace), "https://preview.example.test"))
    output: list[str] = []
    probes: list[str] = []

    result = run_setup_wizard(
        paths,
        input_fn=lambda _: next(answers),
        output_fn=output.append,
        https_probe=lambda url: probes.append(url) or {"reachable": True, "status": 200},
    )

    rendered = "\n".join(output)
    assert probes == ["https://preview.example.test/healthz"]
    assert result["allowed_roots"] == (workspace.resolve(),)
    assert result["external_url"] == "https://preview.example.test/"
    assert "Setup plan" not in rendered
    assert "Apply this plan" not in rendered
    assert token not in rendered
    assert not paths.config_dir.exists()


def test_wizard_defers_unreachable_https_until_after_service_start(tmp_path: Path):
    from hermes_peek.lifecycle import InstallPaths
    from hermes_peek.setup_wizard import run_setup_wizard

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / ".env").write_text("TELEGRAM_BOT_TOKEN=123456789:" + "T" * 35)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    answers = iter((str(workspace), "https://preview.example.test"))
    output: list[str] = []

    run_setup_wizard(
        InstallPaths(hermes_home, tmp_path / "config", tmp_path / "state", tmp_path / "systemd"),
        input_fn=lambda _: next(answers),
        output_fn=output.append,
        https_probe=lambda _: {"reachable": False, "status": None},
    )
    assert any("verify it after the local service starts" in line for line in output)
    assert all("Setup plan" not in line for line in output)


def test_interactive_cli_discovers_profile_and_executes_without_confirmation(tmp_path: Path, monkeypatch, capsys):
    import hermes_peek.cli as cli

    home = tmp_path / "home"
    profile = home / ".hermes" / "profiles" / "work"
    profile.mkdir(parents=True)
    token = "123456789:" + "U" * 35
    (profile / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    (profile / ".env").chmod(0o600)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher")
    answers = iter((str(workspace), "https://preview.example.test"))
    captured = {}

    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(cli.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(cli, "setup_https_probe", lambda _: {"reachable": True, "status": 200})
    monkeypatch.setattr(cli, "install_application", lambda **kwargs: captured.update(kwargs) or {"installed": True})

    assert main(["setup", "--no-activate"]) == 0
    output = capsys.readouterr().out
    assert captured["paths"].hermes_home == profile.resolve()
    assert captured["allowed_roots"] == (workspace.resolve(),)
    assert captured["external_url"] == "https://preview.example.test/"
    assert captured["bot_token"] == token
    assert captured["final_verify"] is None
    assert callable(captured["progress"])
    assert "Setup plan" not in output
    assert "Apply this plan" not in output
    assert "HermesPeek " in output and " installed successfully" in output
    assert "transaction_id" not in output
    assert token not in output


def test_interactive_cli_verifies_external_health_after_activated_install(
    tmp_path: Path, monkeypatch, capsys
):
    import hermes_peek.cli as cli

    home = tmp_path / "home"
    hermes_home = home / ".hermes"
    hermes_home.mkdir(parents=True)
    token = "123456789:" + "W" * 35
    (hermes_home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={token}\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher")
    answers = iter((str(workspace), "https://preview.example.test"))
    probes: list[str] = []

    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(cli.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(
        cli,
        "setup_https_probe",
        lambda url: probes.append(url) or {"reachable": len(probes) > 1, "status": 200},
    )

    def install(**kwargs):
        kwargs["progress"]("validating_setup")
        kwargs["progress"]("starting_service")
        kwargs["progress"]("verifying_installation")
        kwargs["final_verify"]()
        return {"installed": True}

    monkeypatch.setattr(cli, "_plugin_runtime_probe", lambda paths: {"available": True, "error": None})
    monkeypatch.setattr(cli, "install_application", install)

    assert main(["setup"]) == 0
    assert probes == [
        "https://preview.example.test/healthz",
        "https://preview.example.test/healthz",
    ]
    assert "verify it after the local service starts" in capsys.readouterr().out


def test_setup_prints_only_critical_pending_action_after_success(tmp_path: Path, monkeypatch, capsys):
    import hermes_peek.cli as cli

    paths = cli.InstallPaths(tmp_path / "hermes", tmp_path / "config", tmp_path / "state", tmp_path / "systemd")
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    executable = tmp_path / "hermes-peek"
    executable.write_text("launcher")
    token_file = tmp_path / "telegram.env"
    token_file.write_text("TELEGRAM_BOT_TOKEN=123456789:" + "Z" * 35)
    monkeypatch.setattr(cli.InstallPaths, "for_user", classmethod(lambda cls, **kwargs: paths))
    monkeypatch.setattr(cli, "resolve_current_executable", lambda: executable)
    monkeypatch.setattr(
        cli,
        "install_application",
        lambda **kwargs: {
            "installed": True,
            "activation_pending_gateway_restart": True,
            "transaction_id": "hidden",
        },
    )

    assert cli.main([
        "setup", "--allowed-root", str(allowed),
        "--external-url", "https://preview.example.test",
        "--telegram-env", str(token_file),
    ]) == 0
    output = capsys.readouterr().out
    assert output.count("installed successfully") == 1
    assert "Gateway restart required: hermes gateway restart" in output
    assert "transaction_id" not in output
    assert "telegram_onboarding_checklist" not in output


def test_external_health_failure_after_startup_is_a_lifecycle_error(monkeypatch):
    import hermes_peek.cli as cli

    monkeypatch.setattr(cli, "setup_https_probe", lambda _: {"reachable": False, "status": None})

    with pytest.raises(LifecycleError, match="after service startup"):
        cli.verify_external_https_health("https://preview.example.test")


def test_current_executable_falls_back_to_absolute_invocation_when_path_is_missing(
    tmp_path: Path, monkeypatch
):
    import hermes_peek.cli as cli

    executable = tmp_path / "hermes-peek"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    monkeypatch.setattr(cli.sys, "argv", [str(executable), "setup"])

    assert cli.resolve_current_executable() == executable.resolve()


def test_external_bot_token_file_permissions_are_not_modified(tmp_path: Path):
    from hermes_peek.setup_wizard import validate_secret_file

    secret = tmp_path / "telegram.env"
    secret.write_text("TELEGRAM_BOT_TOKEN=123456789:" + "V" * 35)
    secret.chmod(0o644)

    assert validate_secret_file(secret) == secret
    assert secret.stat().st_mode & 0o777 == 0o644


def test_bot_token_file_must_be_regular_and_not_a_symlink(tmp_path: Path):
    from hermes_peek.setup_wizard import validate_secret_file

    secret = tmp_path / "telegram.env"
    secret.write_text("TELEGRAM_BOT_TOKEN=123456789:" + "V" * 35)
    link = tmp_path / "telegram-link.env"
    link.symlink_to(secret)

    with pytest.raises(LifecycleError, match="regular, non-symlink"):
        validate_secret_file(link)


def test_missing_bot_token_file_reports_selected_profile_error(tmp_path: Path):
    from hermes_peek.setup_wizard import validate_secret_file

    with pytest.raises(LifecycleError, match="not found for the selected Hermes profile"):
        validate_secret_file(tmp_path / "missing.env")


def test_terminal_progress_replaces_spinner_with_success_on_one_tty_line(monkeypatch, capsys):
    import hermes_peek.cli as cli

    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    progress = cli._TerminalProgress({"work": ("Working...", "Work complete")})

    progress("work")
    progress.finish()

    output = capsys.readouterr().out
    assert "Working..." in output
    assert "\r\033[2K✓ Work complete\n" in output
    assert "Working...\n" not in output


def test_terminal_progress_is_silent_when_stdout_is_not_a_tty(monkeypatch, capsys):
    import hermes_peek.cli as cli

    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: False)
    progress = cli._TerminalProgress({"work": ("Working...", "Work complete")})

    progress("work")
    progress.finish()

    assert capsys.readouterr().out == ""
