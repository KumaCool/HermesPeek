from __future__ import annotations

import pytest

from hermes_peek.urls import external_base_path, external_url, normalize_external_base_url


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("https://preview.example.test", "https://preview.example.test/"),
        ("https://preview.example.test/", "https://preview.example.test/"),
        ("https://preview.example.test/hermespeek", "https://preview.example.test/hermespeek/"),
        ("https://preview.example.test/apps/hermespeek/", "https://preview.example.test/apps/hermespeek/"),
        ("https://preview.example.test/app-v1_2.~", "https://preview.example.test/app-v1_2.~/"),
    ),
)
def test_normalize_external_base_url_canonicalizes_root_and_path(value: str, expected: str) -> None:
    assert normalize_external_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "",
        "http://preview.example.test/hermespeek",
        "https://user@preview.example.test/hermespeek",
        "https://preview.example.test/hermespeek?secret=value",
        "https://preview.example.test/hermespeek#fragment",
        "https://preview.example.test//hermespeek",
        "https://preview.example.test/./hermespeek",
        "https://preview.example.test/apps/../hermespeek",
        "https://preview.example.test/hermes%70eek",
        "https://preview.example.test/hermes\\peek",
        "https://preview.example.test/预览",
    ),
)
def test_normalize_external_base_url_rejects_unsafe_or_ambiguous_values(value: str) -> None:
    with pytest.raises(ValueError, match="external URL"):
        normalize_external_base_url(value)


@pytest.mark.parametrize(
    ("base", "expected"),
    (
        ("https://preview.example.test", "/"),
        ("https://preview.example.test/hermespeek/", "/hermespeek"),
        ("https://preview.example.test/apps/hermespeek", "/apps/hermespeek"),
    ),
)
def test_external_base_path_returns_cookie_and_browser_prefix(base: str, expected: str) -> None:
    assert external_base_path(base) == expected


def test_external_url_preserves_the_configured_base_path() -> None:
    base = "https://preview.example.test/apps/hermespeek"

    assert external_url(base, "healthz") == "https://preview.example.test/apps/hermespeek/healthz"
    assert external_url(base, "/p/pv_fixture") == "https://preview.example.test/apps/hermespeek/p/pv_fixture"
    assert external_url(base, "") == "https://preview.example.test/apps/hermespeek/"
