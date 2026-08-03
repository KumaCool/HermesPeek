from __future__ import annotations

from pathlib import Path

import pytest

from hermes_peek.paths import FileKind, PathPolicy, PathPolicyError


def policy(root: Path, *, max_file_bytes: int = 64) -> PathPolicy:
    return PathPolicy((root,), max_file_bytes=max_file_bytes)


def assert_rejected(path_policy: PathPolicy, path: Path, code: str) -> None:
    with pytest.raises(PathPolicyError) as caught:
        path_policy.inspect(path)
    assert caught.value.code == code
    assert str(path) not in str(caught.value)


def test_accepts_utf8_text_and_classifies_kind(tmp_path: Path) -> None:
    document = tmp_path / "notes.md"
    document.write_text("# hello", encoding="utf-8")

    inspected = policy(tmp_path).inspect(document)

    assert inspected.resolved_path == document.resolve()
    assert inspected.kind is FileKind.MARKDOWN
    assert inspected.mime_type == "text/markdown"
    assert inspected.size_bytes == len("# hello")


def test_accepts_supported_binary_image(tmp_path: Path) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 8)

    inspected = policy(tmp_path).inspect(image)

    assert inspected.kind is FileKind.IMAGE
    assert inspected.mime_type == "image/png"


def test_rejects_outside_root_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("no", encoding="utf-8")

    assert_rejected(policy(root), outside, "OUTSIDE_ALLOWED_ROOT")
    assert_rejected(policy(root), root / ".." / "outside.md", "OUTSIDE_ALLOWED_ROOT")


@pytest.mark.parametrize(
    "relative",
    [
        ".env",
        ".git/config.md",
        ".ssh/readme.txt",
        ".hermes/note.md",
        "credentials.json",
        "id_rsa.txt",
        "access-token.md",
    ],
)
def test_rejects_sensitive_paths(tmp_path: Path, relative: str) -> None:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret material", encoding="utf-8")

    assert_rejected(policy(tmp_path), target, "SENSITIVE_PATH")


def test_rejects_symlink_even_when_target_is_inside_root(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("hello", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)

    assert_rejected(policy(tmp_path), link, "SYMLINK_NOT_ALLOWED")


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("no", encoding="utf-8")
    link = root / "escape.md"
    link.symlink_to(outside)

    assert_rejected(policy(root), link, "SYMLINK_NOT_ALLOWED")


def test_rejects_missing_directory_unsupported_and_oversized(tmp_path: Path) -> None:
    path_policy = policy(tmp_path, max_file_bytes=4)
    assert_rejected(path_policy, tmp_path / "missing.md", "NOT_FOUND")
    assert_rejected(path_policy, tmp_path, "NOT_REGULAR_FILE")

    unsupported = tmp_path / "program.exe"
    unsupported.write_bytes(b"MZ")
    assert_rejected(path_policy, unsupported, "UNSUPPORTED_TYPE")

    oversized = tmp_path / "large.txt"
    oversized.write_text("12345", encoding="utf-8")
    assert_rejected(path_policy, oversized, "FILE_TOO_LARGE")


def test_rejects_invalid_utf8_and_mime_spoofing(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff\xfe")
    assert_rejected(policy(tmp_path), invalid, "INVALID_UTF8")

    fake_png = tmp_path / "fake.png"
    fake_png.write_text("not a png", encoding="utf-8")
    assert_rejected(policy(tmp_path), fake_png, "MIME_MISMATCH")
