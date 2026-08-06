#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def version() -> str:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]["version"]
    package_tree = ast.parse((ROOT / "src/hermes_peek/__init__.py").read_text(encoding="utf-8"))
    versions = [
        ast.literal_eval(node.value)
        for node in package_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    ]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise SystemExit("package __version__ is missing or ambiguous")
    package = versions[0]
    installer_line = f'INSTALLER_VERSION="{project}"'
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")
    if project != package or installer_line not in installer:
        raise SystemExit("version mismatch between pyproject, package, and installer")
    return project


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic HermesPeek release payload set")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    args = parser.parse_args()
    release_version = version()
    output = args.output.resolve()
    build_dir = output.parent / ".package-build"
    shutil.rmtree(output, ignore_errors=True)
    shutil.rmtree(build_dir, ignore_errors=True)
    output.mkdir(parents=True)
    build_dir.mkdir(parents=True)
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--sdist", "--out-dir", str(build_dir)],
            cwd=ROOT,
            check=True,
        )
        expected = (
            build_dir / f"hermes_peek-{release_version}-py3-none-any.whl",
            build_dir / f"hermes_peek-{release_version}.tar.gz",
        )
        for asset in expected:
            if not asset.is_file():
                raise SystemExit(f"missing expected build asset: {asset.name}")
            shutil.copy2(asset, output / asset.name)
        payloads = sorted(path for path in output.iterdir() if path.name != "SHA256SUMS")
        manifest = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in payloads)
        (output / "SHA256SUMS").write_text(manifest, encoding="utf-8")
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    print(f"BUILT_RELEASE_ASSETS version={release_version} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
