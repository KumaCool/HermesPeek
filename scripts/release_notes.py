#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HEADING = re.compile(r"^## \[([^]]+)](?: - (\d{4}-\d{2}-\d{2}))?\s*$", re.MULTILINE)
_CHANGE_SECTIONS = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def changelog_section(version: str, changelog: Path | None = None) -> str:
    path = changelog or ROOT / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADING.finditer(text))
    match = next((item for item in matches if item.group(1) == version), None)
    if match is None:
        raise ValueError(f"CHANGELOG.md has no section for version {version}")
    if not match.group(2):
        raise ValueError(f"CHANGELOG.md section {version} must include a release date")
    next_start = next((item.start() for item in matches if item.start() > match.start()), len(text))
    body = text[match.end():next_start].strip()
    headings = re.findall(r"^### ([A-Za-z]+)\s*$", body, re.MULTILINE)
    if not headings or any(heading not in _CHANGE_SECTIONS for heading in headings):
        raise ValueError(f"CHANGELOG.md section {version} must use Keep a Changelog categories")
    if not re.search(r"^- \S.+$", body, re.MULTILINE):
        raise ValueError(f"CHANGELOG.md section {version} must contain at least one change entry")
    return f"# HermesPeek {version}\n\n{body}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and extract release notes from CHANGELOG.md")
    parser.add_argument("--version", default=project_version())
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.tag and args.tag != f"v{args.version}":
        raise SystemExit(f"release notes verification failed: tag {args.tag} does not match version {args.version}")
    try:
        notes = changelog_section(args.version)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"release notes verification failed: {exc}") from exc
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(notes, encoding="utf-8")
        print(f"RELEASE_NOTES_WRITTEN version={args.version} output={args.output}")
    else:
        print(notes, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
