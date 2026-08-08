from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

try:
    from .models import FileEntry, PreviewRecord, PublicPreview
    from .paths import InspectedFile, PathPolicy
    from .registry import PreviewRegistry
    from .urls import external_url
except ImportError:  # pragma: no cover - direct script compatibility
    from hermes_peek.models import FileEntry, PreviewRecord, PublicPreview
    from hermes_peek.paths import InspectedFile, PathPolicy
    from hermes_peek.registry import PreviewRegistry
    from hermes_peek.urls import external_url


class PublishError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublishResult:
    record: PreviewRecord
    url: str | None


class PreviewService:
    def __init__(
        self,
        *,
        registry: PreviewRegistry,
        path_policy: PathPolicy,
        default_ttl_seconds: int,
        external_base_url: str | None,
    ) -> None:
        self.registry = registry
        self.path_policy = path_policy
        self.default_ttl_seconds = default_ttl_seconds
        self.external_base_url = external_base_url

    def publish(
        self,
        files: tuple[Path, ...],
        *,
        entry: Path,
        title: str,
        owner_telegram_user_id: str,
        now: datetime | None = None,
    ) -> PublishResult:
        if not files:
            raise PublishError("publish requires at least one file")
        inspected = tuple(self.path_policy.inspect(path) for path in files)
        resolved_paths = tuple(item.resolved_path for item in inspected)
        if len(set(resolved_paths)) != len(resolved_paths):
            raise PublishError("duplicate files are not allowed")

        entry_inspected = self.path_policy.inspect(entry)
        if entry_inspected.resolved_path not in resolved_paths:
            raise PublishError("entry must be one of the published files")

        common_root = self._common_root(resolved_paths)
        entries = tuple(self._file_entry(item, common_root) for item in inspected)
        entry_index = resolved_paths.index(entry_inspected.resolved_path)
        created_at = now or datetime.now(UTC)
        record = PreviewRecord.new(
            title=title,
            owner_telegram_user_id=owner_telegram_user_id,
            entry_file_id=entries[entry_index].id,
            files=entries,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self.default_ttl_seconds),
        )
        created = self.registry.create(record)
        return PublishResult(created, self._preview_url(created.preview_id))

    def inspect(self, preview_id: str) -> PublicPreview:
        return self.registry.get(preview_id).to_public()

    def revoke(self, preview_id: str) -> PublicPreview:
        return self.registry.revoke(preview_id).to_public()

    def _common_root(self, paths: tuple[Path, ...]) -> Path:
        matching_roots = [
            root
            for root in self.path_policy.allowed_roots
            if all(path == root or root in path.parents for path in paths)
        ]
        if matching_roots:
            return max(matching_roots, key=lambda root: len(root.parts))
        return Path(paths[0].anchor)

    @staticmethod
    def _file_entry(inspected: InspectedFile, root: Path) -> FileEntry:
        display_path = inspected.resolved_path.relative_to(root).as_posix()
        digest = hashlib.sha256(display_path.encode("utf-8")).hexdigest()[:24]
        return FileEntry(
            id=f"f_{digest}",
            display_path=display_path,
            absolute_path=inspected.resolved_path,
            kind=inspected.kind.value,
            mime_type=inspected.mime_type,
        )

    def _preview_url(self, preview_id: str) -> str | None:
        if self.external_base_url is None:
            return None
        return external_url(self.external_base_url, f"p/{preview_id}")
