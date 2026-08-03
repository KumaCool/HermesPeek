from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_peek.app import create_app
from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import PreviewRegistry
from hermes_peek.service import PreviewService


def build_client(tmp_path: Path) -> tuple[TestClient, PreviewService]:
    root = tmp_path / "files"
    root.mkdir()
    settings = Settings(
        allowed_roots=(root,),
        state_dir=tmp_path / "state",
        max_file_bytes=1024,
        default_ttl_seconds=3600,
        external_base_url="https://preview.example.test/",
        development=True,
    )
    registry = PreviewRegistry(settings.state_dir)
    service = PreviewService(
        registry=registry,
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=str(settings.external_base_url),
    )
    return TestClient(create_app(settings, service=service)), service


def publish(service: PreviewService, path: Path, *, now: datetime | None = None) -> str:
    result = service.publish(
        (path,),
        entry=path,
        title="Example",
        owner_telegram_user_id="123",
        now=now,
    )
    return result.record.preview_id


def test_app_factory_exposes_shell_metadata_and_live_file_content(tmp_path: Path) -> None:
    client, service = build_client(tmp_path)
    document = tmp_path / "files" / "note.md"
    document.write_text("first", encoding="utf-8")
    preview_id = publish(service, document)
    file_id = service.inspect(preview_id).entry_file_id

    shell = client.get(f"/p/{preview_id}")
    metadata = client.get(f"/api/previews/{preview_id}")
    first = client.get(f"/api/previews/{preview_id}/files/{file_id}")
    document.write_text("second", encoding="utf-8")
    second = client.get(f"/api/previews/{preview_id}/files/{file_id}")

    assert shell.status_code == 200
    assert "Example" in shell.text
    assert "first" not in shell.text
    assert metadata.status_code == 200
    assert metadata.json()["files"][0]["display_path"] == "note.md"
    assert first.json()["content"] == "first"
    assert second.json()["content"] == "second"
    combined = shell.text + metadata.text + first.text + second.text
    assert str(tmp_path) not in combined
    assert "absolute_path" not in combined


def test_preview_api_returns_non_disclosing_statuses(tmp_path: Path) -> None:
    client, service = build_client(tmp_path)
    root = tmp_path / "files"
    active_file = root / "active.md"
    expired_file = root / "expired.md"
    revoked_file = root / "revoked.md"
    for path in (active_file, expired_file, revoked_file):
        path.write_text(path.stem, encoding="utf-8")

    active_id = publish(service, active_file)
    expired_id = publish(
        service,
        expired_file,
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    revoked_id = publish(service, revoked_file)
    service.revoke(revoked_id)
    unknown_id = "pv_" + "z" * 43

    unknown = client.get(f"/api/previews/{unknown_id}")
    expired = client.get(f"/api/previews/{expired_id}")
    revoked = client.get(f"/api/previews/{revoked_id}")
    missing_file = client.get(f"/api/previews/{active_id}/files/f_missing")

    assert (unknown.status_code, unknown.json()) == (404, {"detail": "Preview not found"})
    assert (expired.status_code, expired.json()) == (410, {"detail": "Preview expired"})
    assert (revoked.status_code, revoked.json()) == (410, {"detail": "Preview revoked"})
    assert (missing_file.status_code, missing_file.json()) == (404, {"detail": "File not found"})
    assert str(tmp_path) not in unknown.text + expired.text + revoked.text + missing_file.text
