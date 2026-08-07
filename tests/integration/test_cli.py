from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def run_cli(project: Path, environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "hermes-peek", *arguments],
        cwd=project,
        env={**os.environ, **environment},
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_publish_inspect_revoke_real_subprocess_round_trip(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    root = tmp_path / "files"
    root.mkdir()
    document = root / "document.md"
    document.write_text("# CLI", encoding="utf-8")
    environment = {
        "HERMES_PEEK_ALLOWED_ROOTS": str(root),
        "HERMES_PEEK_STATE_DIR": str(tmp_path / "state"),
        "HERMES_PEEK_EXTERNAL_BASE_URL": "https://preview.example.test/",
    }

    published = run_cli(
        project,
        environment,
        "publish",
        str(document),
        "--entry",
        str(document),
        "--title",
        "CLI Example",
        "--owner",
        "123",
    )
    assert published.returncode == 0, published.stderr
    preview_match = re.search(r"Preview id: (\S+)", published.stdout)
    assert preview_match is not None
    preview_id = preview_match.group(1)
    assert f"Url: https://preview.example.test/p/{preview_id}" in published.stdout
    assert str(tmp_path) not in published.stdout
    assert not published.stderr

    inspected = run_cli(project, environment, "inspect", preview_id)
    assert inspected.returncode == 0, inspected.stderr
    assert "Title: CLI Example" in inspected.stdout
    assert "absolute_path" not in inspected.stdout
    assert str(tmp_path) not in inspected.stdout

    revoked = run_cli(project, environment, "revoke", preview_id)
    assert revoked.returncode == 0, revoked.stderr
    assert "Preview revoked" in revoked.stdout
    assert "Revoked at:" in revoked.stdout


def test_cli_errors_are_concise_and_do_not_traceback(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    environment = {
        "HERMES_PEEK_ALLOWED_ROOTS": str(tmp_path),
        "HERMES_PEEK_STATE_DIR": str(tmp_path / "state"),
    }

    result = run_cli(project, environment, "inspect", "pv_missing")

    assert result.returncode != 0
    assert "Preview not found" in result.stderr
    assert "Traceback" not in result.stderr
