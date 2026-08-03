from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hermes_peek.paths import PathPolicy
from hermes_peek.registry import PreviewRegistry
from hermes_peek.service import PreviewService, PublishError


def service(tmp_path: Path) -> PreviewService:
    return PreviewService(
        registry=PreviewRegistry(tmp_path / "state"),
        path_policy=PathPolicy((tmp_path / "files",), max_file_bytes=1024),
        default_ttl_seconds=3600,
        external_base_url="https://preview.example.test/root/",
    )


def test_publish_validates_files_builds_display_paths_and_url(tmp_path: Path) -> None:
    root = tmp_path / "files"
    document = root / "docs" / "readme.md"
    source = root / "src" / "main.py"
    document.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    document.write_text("# Readme", encoding="utf-8")
    source.write_text("print('ok')", encoding="utf-8")
    preview_service = service(tmp_path)
    now = datetime(2026, 8, 4, tzinfo=UTC)

    result = preview_service.publish(
        (document, source),
        entry=document,
        title="Example",
        owner_telegram_user_id="123",
        now=now,
    )

    assert result.url == f"https://preview.example.test/root/p/{result.record.preview_id}"
    assert result.record.expires_at is not None
    assert [item.display_path for item in result.record.files] == [
        "docs/readme.md",
        "src/main.py",
    ]
    assert result.record.entry_file_id == result.record.files[0].id


def test_publish_rejects_missing_entry_duplicate_and_unpublished_entry(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    first = root / "first.md"
    second = root / "second.md"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    preview_service = service(tmp_path)

    with pytest.raises(PublishError, match="at least one"):
        preview_service.publish((), entry=first, title="x", owner_telegram_user_id="1")
    with pytest.raises(PublishError, match="duplicate"):
        preview_service.publish((first, first), entry=first, title="x", owner_telegram_user_id="1")
    with pytest.raises(PublishError, match="entry must be one"):
        preview_service.publish((first,), entry=second, title="x", owner_telegram_user_id="1")


def test_inspect_and_revoke_return_public_metadata_only(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    document = root / "note.md"
    document.write_text("hello", encoding="utf-8")
    preview_service = service(tmp_path)
    published = preview_service.publish(
        (document,), entry=document, title="Note", owner_telegram_user_id="123"
    )

    inspected = preview_service.inspect(published.record.preview_id)
    revoked = preview_service.revoke(published.record.preview_id)

    assert str(tmp_path) not in inspected.model_dump_json()
    assert revoked.revoked_at is not None
    assert str(tmp_path) not in revoked.model_dump_json()
