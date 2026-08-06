from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hermes_peek.auth import TelegramAuthError, verify_telegram_init_data

from hermes_peek.config import Settings
from hermes_peek.models import FileEntry, PreviewRecord
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import CorruptPreviewError, LaunchRefNotFoundError, LaunchRegistry, PreviewNotFoundError, PreviewRegistry
from hermes_peek.renderers import RenderError, render_text_preview
from hermes_peek.service import PreviewService


class TelegramAuthRequest(BaseModel):
    preview_id: str
    init_data: str


class TelegramLaunchAuthRequest(BaseModel):
    launch_ref: str
    init_data: str


def create_app(
    settings: Settings,
    *,
    service: PreviewService | None = None,
    bot_token: str | None = None,
) -> FastAPI:
    preview_service = service or PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=(
            str(settings.external_base_url) if settings.external_base_url is not None else None
        ),
    )
    application = FastAPI(title="HermesPeek", version="0.2.0")
    application.mount(
        "/static",
        StaticFiles(directory=Path(__file__).with_name("static")),
        name="static",
    )
    sessions: dict[str, tuple[str, str, datetime]] = {}
    launches = LaunchRegistry(settings.state_dir)

    def require_session(
        preview_id: str,
        session_token: str | None = Cookie(default=None, alias="hermes_peek_session"),
    ) -> PreviewRecord:
        if settings.development and bot_token is None:
            return _available_record(preview_service, preview_id)
        if session_token is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        stored = sessions.get(_token_hash(session_token))
        if stored is None or stored[0] != preview_id or stored[2] <= datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Authentication required")
        record = _available_record(preview_service, preview_id)
        if record.owner_telegram_user_id != stored[1]:
            raise HTTPException(status_code=403, detail="Access denied")
        return record

    @application.post("/api/auth/telegram", status_code=204)
    def telegram_auth(payload: TelegramAuthRequest, response: Response) -> Response:
        if bot_token is None:
            raise HTTPException(status_code=503, detail="Telegram authentication unavailable")
        record = _available_record(preview_service, payload.preview_id)
        try:
            identity = verify_telegram_init_data(payload.init_data, bot_token=bot_token)
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail="Invalid Telegram authentication") from exc
        if identity.user_id != record.owner_telegram_user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        token = secrets.token_urlsafe(32)
        sessions[_token_hash(token)] = (
            record.preview_id,
            identity.user_id,
            datetime.now(UTC) + timedelta(minutes=15),
        )
        response.set_cookie(
            "hermes_peek_session",
            token,
            max_age=900,
            httponly=True,
            secure=not settings.development,
            samesite="lax",
            path="/",
        )
        response.status_code = 204
        return response

    @application.post("/api/auth/telegram/launch", status_code=204)
    def telegram_launch_auth(payload: TelegramLaunchAuthRequest, response: Response) -> Response:
        if bot_token is None:
            raise HTTPException(status_code=503, detail="Telegram authentication unavailable")
        try:
            launch = launches.resolve(payload.launch_ref)
            record = _available_record(preview_service, launch["preview_id"])
            identity = verify_telegram_init_data(payload.init_data, bot_token=bot_token)
        except LaunchRefNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Launch reference not found") from exc
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail="Invalid Telegram authentication") from exc
        if identity.user_id != launch["owner_telegram_user_id"] or identity.user_id != record.owner_telegram_user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        token = secrets.token_urlsafe(32)
        sessions[_token_hash(token)] = (
            record.preview_id, identity.user_id, datetime.now(UTC) + timedelta(minutes=15)
        )
        response.set_cookie(
            "hermes_peek_session", token, max_age=900, httponly=True,
            secure=not settings.development, samesite="lax", path="/",
        )
        response.headers["X-HermesPeek-Preview-Id"] = record.preview_id
        response.status_code = 204
        return response

    @application.delete("/api/auth/session", status_code=204)
    def logout(
        response: Response,
        session_token: str | None = Cookie(default=None, alias="hermes_peek_session"),
    ) -> Response:
        if session_token is not None:
            sessions.pop(_token_hash(session_token), None)
        response.delete_cookie("hermes_peek_session", path="/")
        response.status_code = 204
        return response

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "hermes-peek"}

    @application.get("/", response_class=HTMLResponse)
    def home() -> str:
        return """<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>HermesPeek</title><script src="https://telegram.org/js/telegram-web-app.js"></script></head>
<body><main><h1>HermesPeek</h1><p id="launch-state">正在打开预览…</p></main>
<script>
(() => {
  const tg = window.Telegram?.WebApp;
  tg?.ready();
  const query = new URLSearchParams(window.location.search);
  const fromQuery = query.get('tgWebAppStartParam');
  const fromTelegram = tg?.initDataUnsafe?.start_param;
  const launchRef = fromTelegram || fromQuery;
  const state = document.querySelector('#launch-state');
  if (!launchRef) {
    state.textContent = '请从 Hermes 消息中的 Open preview 按钮打开预览。';
    return;
  }
  if (fromTelegram && fromQuery && fromTelegram !== fromQuery) {
    state.textContent = '预览参数无效，请返回 Telegram 后重试。';
    return;
  }
  if (!/^lr_[A-Za-z0-9_-]{20,64}$/.test(launchRef) || !tg?.initData) {
    state.textContent = '请在 Telegram Mini App 中打开此链接。';
    return;
  }
  fetch('/api/auth/telegram/launch', {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({launch_ref: launchRef, init_data: tg.initData}),
  }).then(response => {
    if (!response.ok) throw new Error('launch authentication failed');
    const previewId = response.headers.get('X-HermesPeek-Preview-Id');
    if (!previewId) throw new Error('missing preview');
    location.replace(`/p/${previewId}`);
  }).catch(() => { state.textContent = '预览无效、已过期或无权访问。'; });
})();
</script></body></html>"""

    @application.get("/p/{preview_id}", response_class=HTMLResponse)
    def preview_shell(preview_id: str) -> str:
        record = _available_record(preview_service, preview_id)
        return (
            "<!doctype html><html lang=\"zh-CN\"><head>"
            '<meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f"<title>{_escape(record.title)}</title>"
            '<link rel="stylesheet" href="/static/app.css">'
            '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
            '<script src="/static/app.js" defer></script></head>'
            f"<body><header><h1>{_escape(record.title)}</h1></header><main>"
            f'<div id="preview-app" class="state loading" data-preview-id="{_escape(record.preview_id)}">'
            "<p>正在加载预览…</p></div></main></body></html>"
        )

    @application.get("/api/previews/{preview_id}")
    def preview_metadata(record: PreviewRecord = Depends(require_session)) -> dict[str, object]:
        return record.to_public().model_dump(mode="json")

    @application.get("/api/previews/{preview_id}/files/{file_id}")
    def preview_file(
        file_id: str,
        record: PreviewRecord = Depends(require_session),
    ) -> dict[str, object]:
        entry = _file_entry(record, file_id)
        inspected = _inspect_live_file(preview_service, entry)
        if inspected.kind.value in {"image", "pdf"}:
            raise HTTPException(status_code=415, detail="Binary preview is not available")
        content = inspected.resolved_path.read_text(encoding="utf-8")
        try:
            rendered = render_text_preview(
                kind=inspected.kind.value,
                mime_type=inspected.mime_type,
                display_path=entry.display_path,
                content=content,
            )
        except RenderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "id": entry.id,
            "display_path": entry.display_path,
            "kind": inspected.kind.value,
            "mime_type": inspected.mime_type,
            "content": content,
            "rendered_html": rendered.html,
            **({"sandbox": ""} if inspected.kind.value == "html" else {}),
        }

    @application.get("/api/previews/{preview_id}/files/{file_id}/raw")
    def preview_raw_file(
        file_id: str,
        record: PreviewRecord = Depends(require_session),
    ) -> FileResponse:
        entry = _file_entry(record, file_id)
        inspected = _inspect_live_file(preview_service, entry)
        if inspected.kind.value not in {"image", "pdf"}:
            raise HTTPException(status_code=415, detail="Raw preview is not available")
        return FileResponse(
            inspected.resolved_path,
            media_type=inspected.mime_type,
            filename=entry.display_path.rsplit("/", 1)[-1],
            content_disposition_type="inline",
            headers={"X-Content-Type-Options": "nosniff"},
        )

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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
