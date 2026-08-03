from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from hermes_peek.config import Settings
from hermes_peek.models import FileEntry, PreviewRecord
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import CorruptPreviewError, PreviewNotFoundError, PreviewRegistry
from hermes_peek.service import PreviewService


def create_app(settings: Settings, *, service: PreviewService | None = None) -> FastAPI:
    preview_service = service or PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=(
            str(settings.external_base_url) if settings.external_base_url is not None else None
        ),
    )
    application = FastAPI(title="HermesPeek", version="0.1.0")

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "hermes-peek"}

    @application.get("/", response_class=HTMLResponse)
    def home() -> str:
        return "<!doctype html><title>HermesPeek</title><h1>HermesPeek</h1>"

    @application.get("/p/{preview_id}", response_class=HTMLResponse)
    def preview_shell(preview_id: str) -> str:
        record = _available_record(preview_service, preview_id)
        return (
            "<!doctype html><html lang=\"zh-CN\"><head>"
            '<meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"<title>{_escape(record.title)}</title></head>"
            f"<body><main><h1>{_escape(record.title)}</h1>"
            '<div id="preview-app"></div></main></body></html>'
        )

    @application.get("/api/previews/{preview_id}")
    def preview_metadata(preview_id: str) -> dict[str, object]:
        record = _available_record(preview_service, preview_id)
        return record.to_public().model_dump(mode="json")

    @application.get("/api/previews/{preview_id}/files/{file_id}")
    def preview_file(preview_id: str, file_id: str) -> dict[str, object]:
        record = _available_record(preview_service, preview_id)
        entry = _file_entry(record, file_id)
        inspected = _inspect_live_file(preview_service, entry)
        if inspected.kind.value in {"image", "pdf"}:
            raise HTTPException(status_code=415, detail="Binary preview is not available")
        return {
            "id": entry.id,
            "display_path": entry.display_path,
            "kind": inspected.kind.value,
            "mime_type": inspected.mime_type,
            "content": inspected.resolved_path.read_text(encoding="utf-8"),
        }

    return application


def _available_record(service: PreviewService, preview_id: str) -> PreviewRecord:
    try:
        record = service.registry.get(preview_id)
    except PreviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Preview not found") from exc
    except CorruptPreviewError as exc:
        raise HTTPException(status_code=404, detail="Preview not found") from exc
    if record.revoked_at is not None:
        raise HTTPException(status_code=410, detail="Preview revoked")
    if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=410, detail="Preview expired")
    return record


def _file_entry(record: PreviewRecord, file_id: str) -> FileEntry:
    entry = next((item for item in record.files if item.id == file_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="File not found")
    return entry


def _inspect_live_file(service: PreviewService, entry: FileEntry):
    try:
        return service.path_policy.inspect(entry.absolute_path)
    except PathPolicyError as exc:
        status = 404 if exc.code == "NOT_FOUND" else 422
        raise HTTPException(status_code=status, detail="File is not available") from exc


def _escape(value: str) -> str:
    import html

    return html.escape(value)


def _default_app() -> FastAPI:
    try:
        return create_app(Settings.from_env())
    except ValueError:
        fallback = Settings(
            allowed_roots=(__import__("pathlib").Path.cwd().resolve(),),
            state_dir=__import__("pathlib").Path.cwd().resolve() / ".hermes-peek-state",
            development=True,
        )
        return create_app(fallback)


app = _default_app()
