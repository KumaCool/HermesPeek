from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hermes_peek.app import create_app
from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import PreviewRegistry
from hermes_peek.service import PreviewService


def test_preview_shell_is_a_mobile_telegram_app_with_auth_loading_and_error_states(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    document = root / "note.md"
    document.write_text("# Hello", encoding="utf-8")
    settings = Settings(
        allowed_roots=(root,), state_dir=tmp_path / "state", max_file_bytes=4096,
        default_ttl_seconds=3600, development=True,
    )
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=4096),
        default_ttl_seconds=3600, external_base_url=None,
    )
    preview_id = service.publish(
        (document,), entry=document, title="Mini Preview", owner_telegram_user_id="123"
    ).record.preview_id
    client = TestClient(create_app(settings, service=service))

    shell = client.get(f"/p/{preview_id}")
    script = client.get("/static/app.js")
    style = client.get("/static/app.css")

    assert shell.status_code == script.status_code == style.status_code == 200
    assert 'src="https://telegram.org/js/telegram-web-app.js"' in shell.text
    assert 'id="preview-app"' in shell.text
    assert 'data-preview-id="' + preview_id + '"' in shell.text
    assert "Mini Preview" in shell.text
    assert "fetch(`/api/auth/telegram`" in script.text
    assert "Telegram.WebApp.initData" in script.text
    assert ".expand(" not in script.text
    assert "loading" in script.text and "error" in script.text
    assert "rendered_html" in script.text and "/raw" in script.text
    assert "file-switcher" in script.text and "refresh" in script.text and "copy" in script.text
    assert "var(--tg-theme-bg-color" in style.text
    assert "@media" in style.text
    assert str(tmp_path) not in shell.text + script.text + style.text
