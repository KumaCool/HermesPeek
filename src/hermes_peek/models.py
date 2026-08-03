from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class FileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_path: str
    absolute_path: Path
    kind: str
    mime_type: str

    @field_serializer("absolute_path")
    def serialize_path(self, value: Path) -> str:
        return str(value)


class PublicFileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_path: str
    kind: str
    mime_type: str


class PublicPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    preview_id: str
    title: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    entry_file_id: str
    files: tuple[PublicFileEntry, ...]


class PreviewRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(default=1, ge=1)
    preview_id: str
    title: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    owner_telegram_user_id: str
    source_chat_id: str | None = None
    source_thread_id: str | None = None
    source_session_id: str | None = None
    entry_file_id: str
    files: tuple[FileEntry, ...]

    @field_validator("preview_id")
    @classmethod
    def validate_preview_id(cls, value: str) -> str:
        if not value.startswith("pv_") or not value[3:].replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid preview ID")
        return value

    @field_validator("created_at", "expires_at", "revoked_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @classmethod
    def new(
        cls,
        *,
        title: str,
        owner_telegram_user_id: str,
        entry_file_id: str,
        files: tuple[FileEntry, ...],
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        source_chat_id: str | None = None,
        source_thread_id: str | None = None,
        source_session_id: str | None = None,
    ) -> Self:
        return cls(
            preview_id=f"pv_{secrets.token_urlsafe(32)}",
            title=title,
            created_at=created_at or datetime.now(UTC),
            expires_at=expires_at,
            owner_telegram_user_id=owner_telegram_user_id,
            source_chat_id=source_chat_id,
            source_thread_id=source_thread_id,
            source_session_id=source_session_id,
            entry_file_id=entry_file_id,
            files=files,
        )

    def is_available(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > current
        )

    def to_public(self) -> PublicPreview:
        return PublicPreview(
            preview_id=self.preview_id,
            title=self.title,
            created_at=self.created_at,
            expires_at=self.expires_at,
            revoked_at=self.revoked_at,
            entry_file_id=self.entry_file_id,
            files=tuple(
                PublicFileEntry(
                    id=file.id,
                    display_path=file.display_path,
                    kind=file.kind,
                    mime_type=file.mime_type,
                )
                for file in self.files
            ),
        )
