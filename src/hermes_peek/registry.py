from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from hermes_peek.models import PreviewRecord

_PREVIEW_ID_PATTERN = re.compile(r"^pv_[A-Za-z0-9_-]{20,}$")


class PreviewNotFoundError(LookupError):
    pass


class CorruptPreviewError(RuntimeError):
    pass


class PreviewRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir.expanduser().resolve()
        self.previews_dir = self.state_dir / "previews"
        self.previews_dir.mkdir(parents=True, exist_ok=True)

    def create(self, record: PreviewRecord) -> PreviewRecord:
        destination = self._record_path(record.preview_id)
        if destination.exists():
            raise RuntimeError("Preview ID collision")
        self._write_atomic(destination, record.model_dump_json(indent=2))
        return record

    def get(self, preview_id: str) -> PreviewRecord:
        path = self._record_path(preview_id)
        try:
            payload = path.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError, OSError) as exc:
            raise PreviewNotFoundError("Preview not found") from exc
        try:
            return PreviewRecord.model_validate_json(payload)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptPreviewError("Preview record is corrupt") from exc

    def revoke(
        self,
        preview_id: str,
        *,
        revoked_at: datetime | None = None,
    ) -> PreviewRecord:
        record = self.get(preview_id)
        if record.revoked_at is not None:
            return record
        updated = record.model_copy(
            update={"revoked_at": revoked_at or datetime.now(UTC)}
        )
        self._write_atomic(self._record_path(preview_id), updated.model_dump_json(indent=2))
        return updated

    def _record_path(self, preview_id: str) -> Path:
        if not _PREVIEW_ID_PATTERN.fullmatch(preview_id):
            raise PreviewNotFoundError("Preview not found")
        return self.previews_dir / f"{preview_id}.json"

    @staticmethod
    def _write_atomic(destination: Path, content: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.stem}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(destination.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
