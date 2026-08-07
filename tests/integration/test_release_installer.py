from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "install.sh"
VERSION = "0.2.13"
ASSET = f"hermes_peek-{VERSION}-py3-none-any.whl"


def write_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)
    return path


def release_assets(tmp_path: Path, *, checksum: str | None = None) -> Path:
    release = tmp_path / "release"
    release.mkdir()
    wheel = release / ASSET
    wheel.write_bytes(b"fixed release wheel")
    digest = checksum or hashlib.sha256(wheel.read_bytes()).hexdigest()
    (release / "SHA256SUMS").write_text(f"{digest}  {ASSET}\n")
    return release


def fake_uv(tmp_path: Path) -> Path:
    return write_executable(
        tmp_path / "fake-bin" / "uv",
        """#!/bin/sh
set -eu
if [ "${1:-}" = "--version" ]; then exit 0; fi
printf 'UV_TOOL_DIR=%s UV_TOOL_BIN_DIR=%s %s\\n' "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" "$*" >> "$HERMES_PEEK_TEST_LOG"
case " $* " in
  *" --force "*) ;;
  *) printf 'missing --force\\n' >&2; exit 91 ;;
esac
mkdir -p "$HERMES_PEEK_INSTALL_BIN"
cat > "$HERMES_PEEK_INSTALL_BIN/hermes-peek" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "--version" ]; then printf 'hermes-peek 0.2.13\\n'; exit 0; fi
if [ "${1:-}" = "setup" ] && [ "$(command -v hermes-peek || true)" != "$0" ]; then
  printf 'installed CLI was not added to PATH before setup\\n' >&2
  exit 92
fi
printf 'hermes-peek %s\\n' "$*" >> "$HERMES_PEEK_TEST_LOG"
if [ "${1:-}" = "setup" ]; then printf 'HermesPeek 0.2.13 installed successfully\\n'; fi
EOF
chmod +x "$HERMES_PEEK_INSTALL_BIN/hermes-peek"
""",
    )


def installer_environment(tmp_path: Path, release: Path) -> dict[str, str]:
    install_bin = tmp_path / "data" / "hermes-peek" / "bin"
    return {
        "HERMES_PEEK_RELEASE_BASE_URL": release.as_uri(),
        "HERMES_PEEK_UV": str(fake_uv(tmp_path)),
        "HERMES_PEEK_INSTALL_BIN": str(install_bin),
        "HERMES_PEEK_BIN": str(install_bin / "hermes-peek"),
        "HERMES_PEEK_TEST_LOG": str(tmp_path / "commands.log"),
    }


def run_installer(tmp_path: Path, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(tmp_path / "home"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "HERMES_PEEK_UNAME": "Linux",
            "HERMES_PEEK_SYSTEMCTL": "true",
            "HERMES_PEEK_HERMES": "true",
            "HERMES_PEEK_PYTHON": "python3",
            "HERMES_PEEK_UV": "true",
        }
    )
    if env:
        environment.update(env)
    return subprocess.run(
        ["sh", str(INSTALLER), *arguments],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def test_version_and_dry_run_are_read_only(tmp_path: Path) -> None:
    version = run_installer(tmp_path, "--version")
    dry_run = run_installer(tmp_path, "--dry-run", "--non-interactive")

    assert version.returncode == 0 and version.stdout.strip() == f"HermesPeek installer {VERSION}"
    assert dry_run.returncode == 0
    assert "channel=release" in dry_run.stdout
    assert f"version={VERSION}" in dry_run.stdout
    assert "setup <provided arguments>" in dry_run.stdout
    assert not (tmp_path / "home").exists()


def test_cli_reports_package_version(capsys) -> None:
    from hermes_peek import __version__
    from hermes_peek.cli import build_parser

    with pytest.raises(SystemExit) as result:
        build_parser().parse_args(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == f"hermes-peek {__version__}"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"HERMES_PEEK_UNAME": "Darwin"}, "UNSUPPORTED"),
        ({"HERMES_PEEK_SYSTEMCTL": "false"}, "PENDING_BACKEND"),
    ],
)
def test_unsupported_platform_is_rejected_before_writes(
    tmp_path: Path, environment: dict[str, str], message: str
) -> None:
    result = run_installer(tmp_path, env=environment)

    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "home").exists()
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"HERMES_PEEK_HERMES": "false"}, "Hermes Agent"),
        ({"HERMES_PEEK_PYTHON": "false"}, "Python 3.11"),
        ({"HERMES_PEEK_UV": "false"}, "uv"),
    ],
)
def test_missing_prerequisite_has_actionable_error_before_download(
    tmp_path: Path, environment: dict[str, str], message: str
) -> None:
    result = run_installer(tmp_path, env=environment)

    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "data").exists()


def test_verified_release_with_non_interactive_flag_calls_setup_without_prompting(tmp_path: Path) -> None:
    release = release_assets(tmp_path)
    environment = installer_environment(tmp_path, release)

    result = run_installer(tmp_path, "--non-interactive", env=environment)

    assert result.returncode == 0, result.stderr
    log = (tmp_path / "commands.log").read_text().splitlines()
    assert f"UV_TOOL_DIR={tmp_path / 'data' / 'hermes-peek'}" in log[0]
    assert f"UV_TOOL_BIN_DIR={tmp_path / 'data' / 'hermes-peek' / 'bin'}" in log[0]
    assert "tool install --force --python " in log[0]
    assert log[-1] == "hermes-peek setup"
    assert "sudo" not in "\n".join(log)
    assert result.stdout.count(f"HermesPeek {VERSION} installed successfully") == 1
    assert result.stdout.index("Checking installation requirements...") < result.stdout.index(
        f"Downloading HermesPeek {VERSION}..."
    )
    assert result.stdout.index("Downloading HermesPeek") < result.stdout.index("Verifying package...")
    assert result.stdout.index("Verifying package...") < result.stdout.index("Installing HermesPeek CLI...")


def test_setup_arguments_are_forwarded_without_prompting(tmp_path: Path) -> None:
    release = release_assets(tmp_path)
    environment = installer_environment(tmp_path, release)

    result = run_installer(
        tmp_path,
        "--",
        "--allowed-root",
        "/tmp/workspace",
        "--external-url",
        "https://preview.example.test",
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "commands.log").read_text().splitlines()[-1] == (
        "hermes-peek setup --allowed-root /tmp/workspace --external-url https://preview.example.test"
    )


@pytest.mark.parametrize("shell", ["sh", "bash", "dash"])
def test_installer_is_accepted_by_common_posix_shells(tmp_path: Path, shell: str) -> None:
    result = subprocess.run([shell, "-n", str(INSTALLER)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_checksum_failure_executes_neither_install_nor_setup(tmp_path: Path) -> None:
    release = release_assets(tmp_path, checksum="0" * 64)
    environment = installer_environment(tmp_path, release)

    result = run_installer(tmp_path, env=environment)

    assert result.returncode != 0
    assert "checksum verification failed" in result.stderr
    assert not (tmp_path / "commands.log").exists()
    assert not (tmp_path / "data").exists()


def test_download_failure_leaves_no_partial_install(tmp_path: Path) -> None:
    release = tmp_path / "missing-release"
    environment = installer_environment(tmp_path, release)

    result = run_installer(tmp_path, env=environment)

    assert result.returncode != 0
    assert "failed to download fixed release asset" in result.stderr
    assert not (tmp_path / "commands.log").exists()
    assert not (tmp_path / "data").exists()


def test_same_version_is_idempotent_without_network_or_setup(tmp_path: Path) -> None:
    release = release_assets(tmp_path)
    environment = installer_environment(tmp_path, release)
    first = run_installer(
        tmp_path,
        "--",
        "--allowed-root",
        "/tmp/workspace",
        "--external-url",
        "https://preview.example.test",
        env=environment,
    )
    before = (tmp_path / "commands.log").read_text()
    for asset in release.iterdir():
        asset.unlink()
    release.rmdir()

    environment["HERMES_PEEK_BIN"] = str(tmp_path / "data" / "hermes-peek" / "bin" / "hermes-peek")
    second = run_installer(tmp_path, env=environment)

    assert first.returncode == 0
    assert second.returncode == 0, second.stderr
    assert "already installed" in second.stdout
    assert (tmp_path / "commands.log").read_text() == before


def test_interactive_install_requires_a_terminal(tmp_path: Path) -> None:
    release = release_assets(tmp_path)
    environment = installer_environment(tmp_path, release)

    result = run_installer(tmp_path, env=environment)

    assert result.returncode != 0
    assert "interactive setup requires a terminal" in result.stderr
