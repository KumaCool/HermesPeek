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
    assert "fetch(appUrl('api/auth/telegram')" in script.text
    assert "Telegram.WebApp.initData" in script.text
    assert ".expand(" not in script.text
    assert "loading" in script.text and "error" in script.text
    assert "rendered_html" in script.text and "/raw" in script.text
    assert "file-switcher" in script.text and "refresh" in script.text and "copy" in script.text
    assert "var(--tg-theme-bg-color" in style.text
    assert "@media" in style.text
    assert str(tmp_path) not in shell.text + script.text + style.text


def test_home_is_a_telegram_startapp_router_without_trusting_user_identity(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    settings = Settings(
        allowed_roots=(root,), state_dir=tmp_path / "state", max_file_bytes=4096,
        default_ttl_seconds=3600, development=True,
    )
    client = TestClient(create_app(settings))

    home = client.get("/")

    assert home.status_code == 200
    assert 'src="https://telegram.org/js/telegram-web-app.js"' in home.text
    assert "tgWebAppStartParam" in home.text
    assert "initDataUnsafe?.start_param" in home.text
    assert "^lr_[A-Za-z0-9_-]{20,64}$" in home.text
    assert "location.replace(`/p/${previewId}`)" in home.text
    assert "user.id" not in home.text


def test_base_path_is_rendered_in_shell_assets_launch_auth_and_redirects(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    document = root / "note.md"
    document.write_text("# Hello", encoding="utf-8")
    settings = Settings(
        allowed_roots=(root,),
        state_dir=tmp_path / "state",
        max_file_bytes=4096,
        default_ttl_seconds=3600,
        development=True,
        external_base_url="https://preview.example.test/apps/hermespeek/",
    )
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=4096),
        default_ttl_seconds=3600,
        external_base_url=str(settings.external_base_url),
    )
    preview_id = service.publish(
        (document,), entry=document, title="Base Path Preview", owner_telegram_user_id="123"
    ).record.preview_id
    client = TestClient(create_app(settings, service=service))

    home = client.get("/")
    shell = client.get(f"/p/{preview_id}")

    assert home.status_code == shell.status_code == 200
    assert "fetch('/apps/hermespeek/api/auth/telegram/launch'" in home.text
    assert "location.replace(`/apps/hermespeek/p/${previewId}`)" in home.text
    assert 'href="/apps/hermespeek/static/app.css"' in shell.text
    assert 'src="/apps/hermespeek/static/app.js"' in shell.text
    assert 'data-base-path="/apps/hermespeek"' in shell.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "function appUrl(path)" in script.text
    assert "root?.dataset.basePath" in script.text
    assert "fetch(appUrl('api/auth/telegram')" in script.text
    assert "request(appUrl(`api/previews/${previewId}`))" in script.text
    assert "appUrl(`api/previews/${previewId}/files/${file.id}/raw`)" in script.text
    assert "fetch('/api" not in script.text
    assert "fetch(`/api" not in script.text
    assert "src = '/api" not in script.text
    assert "src = `/api" not in script.text
    assert str(tmp_path) not in home.text + shell.text + script.text
