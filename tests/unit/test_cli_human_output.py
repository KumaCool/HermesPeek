from __future__ import annotations

import pytest

from hermes_peek import cli


def _healthy_status() -> dict[str, object]:
    return {
        "manifest": {"present": True},
        "service": {"active": True, "enabled": True, "health": {"ok": True}},
        "plugin": {
            "installed": True,
            "enabled": True,
            "loaded": True,
            "runtime": {"available": True},
        },
        "gateway": {"active": True},
        "https": {"reachable": True},
        "drift": {"detected": False},
    }


def test_update_check_defaults_to_human_readable_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_latest_release_version", lambda: "9.9.9")
    monkeypatch.setattr(
        cli,
        "_update_cli",
        lambda target, *, apply, progress=None: {
            "current_version": "1.2.3",
            "target_version": target,
            "update_available": True,
            "changes": ["download release", "verify integration"],
        },
    )

    assert cli.main(["update", "--check"]) == 0
    output = capsys.readouterr().out
    assert "HermesPeek update available: 1.2.3 → 9.9.9" in output
    assert "Update actions:" in output
    assert not output.lstrip().startswith("{")


@pytest.mark.parametrize(
    "arguments",
    [
        ["update", "--check", "--json"],
        ["status", "--json"],
        ["doctor", "--json"],
        ["service", "restart", "--json"],
        ["inspect", "preview-id", "--json"],
    ],
)
def test_json_flag_is_not_part_of_the_cli(arguments) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(arguments)
    assert exc.value.code == 2


def test_status_and_doctor_human_formatters_are_clear() -> None:
    status = cli._format_status(_healthy_status())
    doctor = cli._format_doctor(
        {
            "checks": [
                {"name": "service_health", "ok": True, "suggestion": "restart service"},
                {"name": "https", "ok": False, "suggestion": "check HTTPS origin"},
            ]
        }
    )

    assert "HermesPeek status" in status
    assert "✓ Service health" in status
    assert "✓ Configuration drift" in status
    assert "HermesPeek diagnostics" in doctor
    assert "✗ Https" in doctor
    assert "Suggestion: check HTTPS origin" in doctor


def test_generic_human_output_handles_nested_results(capsys) -> None:
    cli._print_result(
        {"action": "restart", "ok": True, "details": {"active": True}},
        kind="service",
    )
    output = capsys.readouterr().out
    assert "Service command completed" in output
    assert "Action: restart" in output
    assert "Active: Yes" in output
    assert not output.lstrip().startswith("{")
