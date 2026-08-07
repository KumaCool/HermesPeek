from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/release_notes.py"
SPEC = importlib.util.spec_from_file_location("release_notes", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
changelog_section = MODULE.changelog_section


def write_changelog(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_extracts_only_requested_version_notes(tmp_path: Path):
    path = write_changelog(tmp_path, """# Changelog

## [Unreleased]

## [1.2.3] - 2026-08-07

### Added

- Stable installed-user lifecycle.

### Fixed

- Release notes enforcement.

## [1.2.2] - 2026-08-06

### Fixed

- Older fix.
""")
    notes = changelog_section("1.2.3", path)
    assert notes.startswith("# HermesPeek 1.2.3")
    assert "Stable installed-user lifecycle" in notes
    assert "Older fix" not in notes


@pytest.mark.parametrize("text, message", [
    ("# Changelog\n\n## [1.2.3] - 2026-08-07\n", "Keep a Changelog categories"),
    ("# Changelog\n\n## [1.2.3]\n\n### Fixed\n\n- Fix.\n", "release date"),
    ("# Changelog\n\n## [1.2.2] - 2026-08-07\n\n### Fixed\n\n- Fix.\n", "no section"),
])
def test_rejects_missing_or_empty_version_changelog(tmp_path: Path, text: str, message: str):
    with pytest.raises(ValueError, match=message):
        changelog_section("1.2.3", write_changelog(tmp_path, text))


def test_release_workflow_publishes_extracted_changelog():
    workflow = Path(".github/workflows/linux-release.yml").read_text(encoding="utf-8")
    assert "scripts/release_notes.py" in workflow
    assert "body_path: dist/RELEASE_NOTES.md" in workflow
    assert "generate_release_notes: true" not in workflow
