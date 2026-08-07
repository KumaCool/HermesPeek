from __future__ import annotations

import hashlib
import os
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

    monkeypatch.setenv("HERMES_PEEK_INSTALL_ROOT", str(root))
    monkeypatch.setenv("HERMES_PEEK_TEST_LOG", str(log))
    monkeypatch.setattr(cli, "resolve_current_executable", lambda: installed.resolve())
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(fake_uv) if name == "uv" else None)
    monkeypatch.setattr(cli.urllib.request, "urlretrieve", download)

    result = cli._update_cli("9.9.9", apply=True)

    assert result["updated"] is True
    assert log.read_text(encoding="utf-8").splitlines() == ["setup", "status", "doctor"]
    assert installed.read_text(encoding="utf-8").splitlines()[0] == f"#!{root}/hermes-peek/bin/python"
    assert command_link.resolve() == installed.resolve()
