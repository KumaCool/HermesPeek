from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from hermes_peek import cli


def _write_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_update_reinstalls_launcher_at_final_path_before_running_setup(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data" / "hermes-peek"
    installed = root / "hermes-peek" / "bin" / "hermes-peek"
    command_link = tmp_path / "bin" / "hermes-peek"
    _write_executable(installed, "#!/bin/sh\nexit 0\n")
    command_link.parent.mkdir(parents=True)
    command_link.symlink_to(installed)
    (root / "install-metadata.json").write_text(
        '{"install_root": "' + str(root) + '", "executable": "' + str(installed)
        + '", "command_link": "' + str(command_link) + '"}',
        encoding="utf-8",
    )

    log = tmp_path / "cli.log"
    fake_uv = _write_executable(
        tmp_path / "fake-bin" / "uv",
        """#!/bin/sh
set -eu
launcher="$UV_TOOL_DIR/hermes-peek/bin/hermes-peek"
interpreter="$UV_TOOL_DIR/hermes-peek/bin/python"
mkdir -p "$(dirname "$launcher")"
ln -sf /bin/sh "$interpreter"
printf '#!%s\\n' "$interpreter" > "$launcher"
cat >> "$launcher" <<'EOF'
printf 'base=%s\n' "${HERMES_PEEK_TEST_EXTERNAL_BASE_URL:-}" >> "$HERMES_PEEK_TEST_LOG"
if [ "${1:-}" = "setup" ]; then
  test "$(python3 -c 'import json,os; print(json.load(open(os.environ["HERMES_PEEK_TEST_CONFIG"]))["external_base_url"])')" = "$HERMES_PEEK_TEST_EXTERNAL_BASE_URL" || exit 93
fi
if [ "${1:-}" = "--version" ]; then printf 'hermes-peek 9.9.9\\n'; exit 0; fi
printf '%s\\n' "$1" >> "$HERMES_PEEK_TEST_LOG"
exit 0
EOF
chmod +x "$launcher"
""",
    )

    wheel_bytes = b"release wheel"
    digest = hashlib.sha256(wheel_bytes).hexdigest()

    def download(url: str, destination: Path) -> None:
        destination = Path(destination)
        if destination.name == "SHA256SUMS":
            destination.write_text(f"{digest}  hermes_peek-9.9.9-py3-none-any.whl\n", encoding="utf-8")
        else:
            destination.write_bytes(wheel_bytes)

    base_url = "https://preview.example.test/apps/hermespeek/"
    config = tmp_path / "config.json"
    config.write_text('{"external_base_url": "' + base_url + '"}\n', encoding="utf-8")
    monkeypatch.setenv("HERMES_PEEK_INSTALL_ROOT", str(root))
    monkeypatch.setenv("HERMES_PEEK_TEST_LOG", str(log))
    monkeypatch.setenv("HERMES_PEEK_TEST_EXTERNAL_BASE_URL", base_url)
    monkeypatch.setenv("HERMES_PEEK_TEST_CONFIG", str(config))
    monkeypatch.setattr(cli, "resolve_current_executable", lambda: installed.resolve())
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(fake_uv) if name == "uv" else None)
    monkeypatch.setattr(cli.urllib.request, "urlretrieve", download)
    original_run = cli.subprocess.run
    lifecycle_stdin = []

    def recording_run(command, *args, **kwargs):
        if len(command) > 1 and command[1] in {"setup", "status", "doctor"}:
            lifecycle_stdin.append(kwargs.get("stdin"))
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", recording_run)

    result = cli._update_cli("9.9.9", apply=True)

    assert result["updated"] is True
    assert log.read_text(encoding="utf-8").splitlines() == [
        f"base={base_url}",
        f"base={base_url}",
        f"base={base_url}",
        "setup",
        f"base={base_url}",
        "status",
        f"base={base_url}",
        "doctor",
    ]
    assert installed.read_text(encoding="utf-8").splitlines()[0] == f"#!{root}/hermes-peek/bin/python"
    assert command_link.resolve() == installed.resolve()
    assert lifecycle_stdin == [subprocess.DEVNULL, subprocess.DEVNULL, subprocess.DEVNULL]


def test_update_subprocess_error_names_phase_redacts_token_and_bounds_detail() -> None:
    token = "123456789:" + "A" * 35
    result = subprocess.CompletedProcess(
        ["hermes-peek", "setup"], 7, "", f"prompt failed for {token}\n" + "x" * 2000
    )

    message = str(cli._update_subprocess_error("setup", result))

    assert message.startswith("updated integration setup failed: prompt failed for [REDACTED]")
    assert token not in message
    assert len(message) <= 1040
