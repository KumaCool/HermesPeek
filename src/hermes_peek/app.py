from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="HermesPeek", version="0.1.0")

MAX_FILE_BYTES = 2 * 1024 * 1024
DENIED_NAMES = {".env", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
DENIED_PARTS = {".git", ".ssh", ".hermes", "node_modules", "__pycache__"}
TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".xml", ".csv",
}


def allowed_roots() -> tuple[Path, ...]:
    raw = os.getenv("HERMES_PEEK_ALLOWED_ROOTS", str(Path.cwd()))
    return tuple(Path(item).expanduser().resolve() for item in raw.split(os.pathsep) if item)


def resolve_preview_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not any(path == root or root in path.parents for root in allowed_roots()):
        raise HTTPException(status_code=403, detail="File is outside allowed roots")
    if path.name.lower() in DENIED_NAMES or any(part.lower() in DENIED_PARTS for part in path.parts):
        raise HTTPException(status_code=403, detail="Sensitive path is not previewable")
    if path.suffix.lower() not in TEXT_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported file type")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")
    return path


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; color: var(--tg-theme-text-color, #222); background: var(--tg-theme-bg-color, #fff); }}
    header {{ position: sticky; top: 0; padding: 12px 16px; font-weight: 650; background: var(--tg-theme-secondary-bg-color, #f2f3f5); }}
    main {{ padding: 16px; }}
    pre {{ margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.55 ui-monospace, monospace; }}
    .tag {{ color: var(--tg-theme-hint-color, #777); font-size: 12px; }}
  </style>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
</head>
<body><header>{html.escape(title)}</header><main>{body}</main>
<script>window.Telegram?.WebApp?.ready();</script></body></html>"""


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "hermes-peek"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return page("HermesPeek", "<h1>Hermes 写完，Telegram 里看。</h1><p>最小预览服务运行正常。</p>")


@app.get("/preview", response_class=HTMLResponse)
def preview(path: str = Query(..., description="Absolute path under an allowed root")) -> str:
    resolved = resolve_preview_path(path)
    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="File is not UTF-8 text") from exc
    body = f'<div class="tag">{html.escape(resolved.suffix.lower() or "text")}</div><pre>{html.escape(content)}</pre>'
    return page(resolved.name, body)
