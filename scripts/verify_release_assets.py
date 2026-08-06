#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"release verification failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a local HermesPeek release asset directory")
    parser.add_argument("assets", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args()
    assets = args.assets.resolve()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if args.tag and args.tag != f"v{version}":
        fail(f"tag {args.tag} does not match project version {version}")
    expected = {
        f"hermes_peek-{version}-py3-none-any.whl",
        f"hermes_peek-{version}.tar.gz",
        "SHA256SUMS",
    }
    present = {path.name for path in assets.iterdir()} if assets.is_dir() else set()
    if present != expected:
        fail(f"asset set mismatch: expected {sorted(expected)}, got {sorted(present)}")
    lines = (assets / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    entries: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match:
            fail("invalid checksum manifest format")
        assert match is not None
        entries[match.group(2)] = match.group(1)
    payloads = expected - {"SHA256SUMS"}
    if set(entries) != payloads:
        fail("checksum manifest does not name every payload exactly once")
    for name, digest in entries.items():
        if hashlib.sha256((assets / name).read_bytes()).hexdigest() != digest:
            fail(f"checksum mismatch for {name}")
    wheel_name = f"hermes_peek-{version}-py3-none-any.whl"
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    if f'INSTALLER_VERSION="{version}"' not in installer or f'ASSET="{wheel_name}"' not in installer:
        fail("repository installer version or wheel filename mismatch")
    with zipfile.ZipFile(assets / wheel_name) as archive:
        names = set(archive.namelist())
        required = {"hermes_peek/hermes_plugin/plugin.yaml", "hermes_peek/hermes_plugin/preview_tool.py"}
        if not required <= names:
            fail("wheel is missing packaged Hermes integration resources")
        metadata = archive.read(f"hermes_peek-{version}.dist-info/METADATA").decode()
        if f"Version: {version}" not in metadata:
            fail("wheel metadata version mismatch")
    with tarfile.open(assets / f"hermes_peek-{version}.tar.gz") as archive:
        names = set(archive.getnames())
        prefix = f"hermes_peek-{version}"
        required = {f"{prefix}/skills/hermes-peek-preview/SKILL.md", f"{prefix}/deploy/systemd/hermes-peek.service"}
        if not required <= names:
            fail("sdist is missing release resources")
    print(f"VERIFIED_RELEASE_ASSETS version={version} assets={assets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
