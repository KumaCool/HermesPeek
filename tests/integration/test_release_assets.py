from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "scripts" / "build_release_assets.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_release_assets.py"
OFFLINE_SCRIPT = ROOT / "scripts" / "offline_linux_acceptance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "linux-release.yml"


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def build_assets(tmp_path: Path) -> Path:
    output = tmp_path / "release"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def test_release_builder_emits_version_aligned_complete_assets(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    version = project_version()
    expected = {
        f"hermes_peek-{version}-py3-none-any.whl",
        f"hermes_peek-{version}.tar.gz",
        "SHA256SUMS",
    }

    assert {path.name for path in output.iterdir()} == expected



def test_checksum_manifest_round_trips_every_release_payload(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    lines = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    entries = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in lines}

    assert set(entries) == {path.name for path in output.iterdir() if path.name != "SHA256SUMS"}
    for name, expected in entries.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected


def test_wheel_and_sdist_contain_runtime_release_resources(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    version = project_version()
    wheel = output / f"hermes_peek-{version}-py3-none-any.whl"
    sdist = output / f"hermes_peek-{version}.tar.gz"

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "hermes_peek/hermes_plugin/plugin.yaml" in names
        assert "hermes_peek/hermes_plugin/preview_tool.py" in names
        metadata = archive.read(f"hermes_peek-{version}.dist-info/METADATA").decode()
        assert f"Version: {version}" in metadata
    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        prefix = f"hermes_peek-{version}"
        assert f"{prefix}/skills/hermes-peek-preview/SKILL.md" in names
        assert f"{prefix}/deploy/systemd/hermes-peek.service" in names


def test_local_release_verifier_accepts_built_assets_and_rejects_tampering(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    valid = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(output)], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr

    wheel = next(output.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    invalid = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(output)], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert invalid.returncode != 0
    assert "checksum" in (invalid.stdout + invalid.stderr).lower()


def test_repository_installer_uses_the_exact_wheel_name_produced_by_builder(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    wheel = next(output.glob("*.whl"))
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert f'ASSET="{wheel.name}"' in installer


def test_project_package_installer_and_tag_version_contract_are_identical() -> None:
    version = project_version()
    package_text = (ROOT / "src/hermes_peek/__init__.py").read_text(encoding="utf-8")
    installer_text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert f'__version__ = "{version}"' in package_text
    assert f'INSTALLER_VERSION="{version}"' in installer_text
    valid = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(ROOT / "dist/release"), "--tag", f"v{version}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if (ROOT / "dist/release").is_dir() and any((ROOT / "dist/release").glob("*0.2.2*")):
        assert valid.returncode == 0, valid.stdout + valid.stderr


def test_offline_fresh_home_acceptance_uses_built_wheel_and_fake_transports(tmp_path: Path) -> None:
    output = build_assets(tmp_path)
    fresh = tmp_path / "fresh"
    result = subprocess.run(
        [sys.executable, str(OFFLINE_SCRIPT), "--assets", str(output), "--root", str(fresh)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OFFLINE_LINUX_ACCEPTANCE_OK" in result.stdout
    assert "PENDING_REAL_GATEWAY" in result.stdout
    assert "PENDING_REAL_TELEGRAM" in result.stdout
    assert (fresh / "evidence" / "acceptance.json").is_file()
    assert not (fresh / "home" / ".hermes").exists()


def test_linux_release_workflow_builds_and_verifies_but_publishes_only_tags() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow[True]

    assert "push" in triggers and "tags" in triggers["push"]
    assert "workflow_dispatch" in triggers
    assert "scripts/build_release_assets.py" in text
    assert "scripts/verify_release_assets.py" in text
    assert "scripts/offline_linux_acceptance.py" in text
    assert "actions/upload-artifact@" in text
    assert "softprops/action-gh-release@" in text
    assert "generate_release_notes: true" in text
    assert "startsWith(github.ref, 'refs/tags/v')" in text
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["publish-tag"]["permissions"] == {"contents": "write"}
    assert "secrets:" not in text
    assert "contents: write" in text
