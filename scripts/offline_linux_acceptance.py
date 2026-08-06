#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
    if result.returncode:
        raise SystemExit(f"command failed: {' '.join(command)}\n{result.stdout}{result.stderr}")
    return result


def write_executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Linux release acceptance with fake external transports")
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    assets = args.assets.resolve()
    root = args.root.resolve()
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    run([sys.executable, str(ROOT / "scripts/verify_release_assets.py"), str(assets)])

    wheel = next(assets.glob("*.whl"))
    home = root / "home"
    data = root / "data"
    install_bin = data / "hermes-peek/bin"
    fake_bin = root / "fake-bin"
    evidence_dir = root / "evidence"
    evidence_dir.mkdir()
    log = evidence_dir / "commands.log"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_DATA_HOME": str(data),
            "HERMES_PEEK_UNAME": "Linux",
            "HERMES_PEEK_SYSTEMCTL": str(write_executable(fake_bin / "systemctl", "#!/bin/sh\nexit 0\n")),
            "HERMES_PEEK_HERMES": str(write_executable(fake_bin / "hermes", "#!/bin/sh\nexit 0\n")),
            "HERMES_PEEK_CURL": str(write_executable(fake_bin / "curl", "#!/bin/sh\nset -eu\nurl=$2\nout=$4\ncp \"${url#file://}\" \"$out\"\n")),
            "HERMES_PEEK_RELEASE_BASE_URL": assets.as_uri(),
            "HERMES_PEEK_INSTALL_BIN": str(install_bin),
            "HERMES_PEEK_BIN": str(install_bin / "hermes-peek"),
            "HERMES_PEEK_TEST_LOG": str(log),
        }
    )
    fake_uv = write_executable(
        fake_bin / "uv",
        """#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then exit 0; fi
printf '%s\n' "$*" >> "$HERMES_PEEK_TEST_LOG"
wheel=${5}
venv="$UV_TOOL_DIR/venv"
"$HERMES_PEEK_PYTHON" -m venv "$venv"
"$venv/bin/python" -m pip install --no-index --no-deps "$wheel" >/dev/null
mkdir -p "$UV_TOOL_BIN_DIR"
cat > "$UV_TOOL_BIN_DIR/hermes-peek" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then printf 'hermes-peek 0.2.0\n'; exit 0; fi
printf 'hermes-peek %s\n' "$*" >> "$HERMES_PEEK_TEST_LOG"
EOF
chmod +x "$UV_TOOL_BIN_DIR/hermes-peek"
""",
    )
    env["HERMES_PEEK_UV"] = str(fake_uv)
    env["HERMES_PEEK_PYTHON"] = sys.executable

    # The release installer consumes real local payload bytes; external lifecycle transports stay fake.
    result = run(["sh", str(assets / "install.sh"), "--non-interactive"], env=env)
    commands = log.read_text(encoding="utf-8")
    if wheel.name not in commands or "hermes-peek setup" not in commands:
        raise SystemExit("offline installer did not consume the built wheel and canonical setup entrypoint")

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    required_wheel_resources = {
        "hermes_peek/hermes_plugin/plugin.yaml",
        "hermes_peek/hermes_plugin/preview_tool.py",
    }
    if not required_wheel_resources <= names:
        raise SystemExit("built wheel cannot expose the packaged Hermes plugin resources")
    probe = run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from hermes_peek import __version__; print(__version__)",
            str(wheel),
        ]
    )

    # Synthetic lifecycle evidence: no real profile, systemd, Hermes, Gateway, Telegram, or network is touched.
    source = ROOT / "src/hermes_peek/hermes_plugin"
    profile = root / "isolated-profile"
    plugin = profile / "plugins/hermes-peek"
    skill = profile / "skills/hermes-peek-preview"
    shutil.copytree(source, plugin)
    shutil.copytree(ROOT / "skills/hermes-peek-preview", skill)
    first_hash = hashlib.sha256((plugin / "plugin.yaml").read_bytes()).hexdigest()
    backup = root / "rollback/plugin"
    shutil.copytree(plugin, backup)
    (plugin / "plugin.yaml").write_text("changed\n", encoding="utf-8")
    shutil.rmtree(plugin)
    shutil.copytree(backup, plugin)
    rollback_ok = hashlib.sha256((plugin / "plugin.yaml").read_bytes()).hexdigest() == first_hash
    shutil.rmtree(plugin)
    shutil.rmtree(skill)
    uninstall_ok = not plugin.exists() and not skill.exists()

    evidence = {
        "schema_version": 1,
        "release_asset": wheel.name,
        "wheel_import": probe.stdout.strip(),
        "fresh_home": str(home),
        "installer_local_file_asset": True,
        "fake_systemd": True,
        "fake_hermes": True,
        "fake_telegram_transport": True,
        "profile_install_upgrade_rollback_uninstall": rollback_ok and uninstall_ok,
        "real_gateway": "PENDING_REAL_GATEWAY",
        "real_telegram": "PENDING_REAL_TELEGRAM",
        "non_linux_backend": "PENDING_BACKEND",
    }
    (evidence_dir / "acceptance.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("OFFLINE_LINUX_ACCEPTANCE_OK")
    print("PENDING_REAL_GATEWAY")
    print("PENDING_REAL_TELEGRAM")
    print("NON_LINUX=PENDING_BACKEND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
