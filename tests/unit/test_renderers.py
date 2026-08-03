from __future__ import annotations

from pathlib import Path

import pytest

from hermes_peek.renderers import RenderError, render_text_preview


def test_plain_text_and_code_are_html_escaped() -> None:
    plain = render_text_preview(
        kind="text", mime_type="text/plain", display_path="note.txt", content="<script>x</script>"
    )
    code = render_text_preview(
        kind="text", mime_type="text/x-python", display_path="main.py", content="print('<ok>')"
    )

    assert "<script>" not in plain.html
    assert "&lt;script&gt;x&lt;/script&gt;" in plain.html
    assert "language-python" in code.html
    assert "&lt;ok&gt;" in code.html


def test_markdown_supports_common_content_but_strips_active_html() -> None:
    rendered = render_text_preview(
        kind="markdown",
        mime_type="text/markdown",
        display_path="readme.md",
        content="# Title\n\n**bold** [bad](javascript:alert(1))\n\n<script>alert(1)</script>",
    )

    assert "<h1>Title</h1>" in rendered.html
    assert "<strong>bold</strong>" in rendered.html
    assert "javascript:" not in rendered.html
    assert "<script>" not in rendered.html


@pytest.mark.parametrize(
    ("display_path", "content", "expected"),
    [
        ("data.json", '{"b":1,"a":[2]}', '"a": [\n    2\n  ]'),
        ("data.yaml", "name: peek\nitems:\n  - one\n", "name: peek"),
        ("data.toml", '[app]\nname="peek"\n', '[app]'),
    ],
)
def test_structured_text_is_validated_and_presented(display_path: str, content: str, expected: str) -> None:
    rendered = render_text_preview(
        kind="structured",
        mime_type="application/octet-stream",
        display_path=display_path,
        content=content,
    )
    assert expected in rendered.text
    assert "<pre" in rendered.html


def test_invalid_structured_text_returns_safe_error() -> None:
    with pytest.raises(RenderError, match="Invalid structured document"):
        render_text_preview(
            kind="structured",
            mime_type="application/json",
            display_path="broken.json",
            content="{broken",
        )
