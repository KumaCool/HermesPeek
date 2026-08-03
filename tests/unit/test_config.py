from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from hermes_peek.config import Settings


def test_settings_require_explicit_allowed_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HERMES_PEEK_ALLOWED_ROOTS"):
        Settings.from_env({}, cwd=tmp_path)


def test_settings_parse_multiple_allowed_roots_and_resolve_paths(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    settings = Settings.from_env(
        {
            "HERMES_PEEK_ALLOWED_ROOTS": os.pathsep.join(("first", str(second))),
            "HERMES_PEEK_STATE_DIR": "state",
            "HERMES_PEEK_MAX_FILE_BYTES": "4096",
            "HERMES_PEEK_DEFAULT_TTL_SECONDS": "900",
            "HERMES_PEEK_EXTERNAL_BASE_URL": "https://preview.example.test/base/",
            "HERMES_PEEK_DEVELOPMENT": "true",
        },
        cwd=tmp_path,
    )

    assert settings.allowed_roots == (first.resolve(), second.resolve())
    assert settings.state_dir == (tmp_path / "state").resolve()
    assert settings.max_file_bytes == 4096
    assert settings.default_ttl_seconds == 900
    assert str(settings.external_base_url) == "https://preview.example.test/base/"
    assert settings.development is True


def test_settings_use_xdg_state_default_without_reading_real_environment(tmp_path: Path) -> None:
    xdg = tmp_path / "xdg"
    root = tmp_path / "root"
    root.mkdir()

    settings = Settings.from_env(
        {
            "HERMES_PEEK_ALLOWED_ROOTS": str(root),
            "XDG_STATE_HOME": str(xdg),
        },
        cwd=tmp_path,
    )

    assert settings.state_dir == (xdg / "hermes-peek").resolve()
    assert settings.max_file_bytes == 2 * 1024 * 1024
    assert settings.default_ttl_seconds == 7 * 24 * 60 * 60
    assert settings.external_base_url is None
    assert settings.development is False


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HERMES_PEEK_MAX_FILE_BYTES", "0"),
        ("HERMES_PEEK_DEFAULT_TTL_SECONDS", "-1"),
        ("HERMES_PEEK_EXTERNAL_BASE_URL", "http://preview.example.test"),
        ("HERMES_PEEK_DEVELOPMENT", "sometimes"),
    ],
)
def test_settings_reject_invalid_values(tmp_path: Path, name: str, value: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    environment = {"HERMES_PEEK_ALLOWED_ROOTS": str(root), name: value}

    with pytest.raises((ValueError, ValidationError)):
        Settings.from_env(environment, cwd=tmp_path)
