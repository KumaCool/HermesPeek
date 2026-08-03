from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hermes_peek.models import FileEntry, PreviewRecord
from hermes_peek.registry import (
    CorruptPreviewError,
    PreviewNotFoundError,
    PreviewRegistry,
)


def make_record(path: Path, *, now: datetime, expires_at: datetime | None = None) -> PreviewRecord:
    return PreviewRecord.new(
        title="Example",
        owner_telegram_user_id="123",
        entry_file_id="f_entry",
        files=(
            FileEntry(
                id="f_entry",
                display_path="docs/example.md",
                absolute_path=path,
                kind="markdown",
                mime_type="text/markdown",
            ),
        ),
        created_at=now,
        expires_at=expires_at,
    )


def test_create_and_read_record_with_opaque_random_id(tmp_path: Path) -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    registry = PreviewRegistry(tmp_path / "state")
    record = registry.create(make_record(tmp_path / "example.md", now=now))

    assert record.preview_id.startswith("pv_")
    assert len(record.preview_id) >= 40
    assert registry.get(record.preview_id) == record
    assert (tmp_path / "state" / "previews" / f"{record.preview_id}.json").is_file()


def test_public_model_never_serializes_absolute_path(tmp_path: Path) -> None:
    record = make_record(tmp_path / "private" / "example.md", now=datetime.now(UTC))

    public_json = record.to_public().model_dump_json()

    assert "absolute_path" not in public_json
    assert str(tmp_path) not in public_json
    assert "docs/example.md" in public_json


def test_revoke_persists_timestamp_and_is_idempotent(tmp_path: Path) -> None:
    registry = PreviewRegistry(tmp_path / "state")
    record = registry.create(make_record(tmp_path / "example.md", now=datetime.now(UTC)))
    revoked_at = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)

    first = registry.revoke(record.preview_id, revoked_at=revoked_at)
    second = registry.revoke(record.preview_id, revoked_at=revoked_at + timedelta(hours=1))

    assert first.revoked_at == revoked_at
    assert second.revoked_at == revoked_at
    assert registry.get(record.preview_id).revoked_at == revoked_at


def test_record_reports_expiry_and_revocation(tmp_path: Path) -> None:
    now = datetime(2026, 8, 4, tzinfo=UTC)
    active = make_record(tmp_path / "a.md", now=now, expires_at=now + timedelta(seconds=1))
    expired = active.model_copy(update={"expires_at": now - timedelta(seconds=1)})
    revoked = active.model_copy(update={"revoked_at": now})

    assert active.is_available(now) is True
    assert expired.is_available(now) is False
    assert revoked.is_available(now) is False


def test_unknown_and_invalid_preview_ids_are_non_disclosing(tmp_path: Path) -> None:
    registry = PreviewRegistry(tmp_path / "state")

    for preview_id in ("pv_unknown", "../secret", "/absolute/path"):
        with pytest.raises(PreviewNotFoundError, match="Preview not found"):
            registry.get(preview_id)


def test_corrupt_record_isolated_from_other_records(tmp_path: Path) -> None:
    registry = PreviewRegistry(tmp_path / "state")
    good = registry.create(make_record(tmp_path / "good.md", now=datetime.now(UTC)))
    corrupt_id = "pv_" + "a" * 43
    corrupt = tmp_path / "state" / "previews" / f"{corrupt_id}.json"
    corrupt.write_text("{broken", encoding="utf-8")

    with pytest.raises(CorruptPreviewError, match="Preview record is corrupt"):
        registry.get(corrupt_id)
    assert registry.get(good.preview_id) == good


def test_concurrent_creates_leave_complete_independent_records(tmp_path: Path) -> None:
    registry = PreviewRegistry(tmp_path / "state")
    now = datetime.now(UTC)

    def create(index: int) -> PreviewRecord:
        return registry.create(make_record(tmp_path / f"{index}.md", now=now))

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(executor.map(create, range(40)))

    assert len({record.preview_id for record in records}) == 40
    assert all(registry.get(record.preview_id) == record for record in records)
    assert not list((tmp_path / "state" / "previews").glob("*.tmp"))
