from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from hermes_peek.app import create_app
from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import PreviewRegistry
from hermes_peek.service import PreviewService


def client_and_service(tmp_path: Path) -> tuple[TestClient, PreviewService]:
    root = tmp_path / "files"
    root.mkdir()
    settings = Settings(
        allowed_roots=(root,), state_dir=tmp_path / "state", max_file_bytes=4096,
        default_ttl_seconds=3600, development=True,
    )
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=3600, external_base_url=None,
    )
    return TestClient(create_app(settings, service=service)), service


def publish(service: PreviewService, path: Path) -> tuple[str, str]:
    record = service.publish(
        (path,), entry=path, title=path.name, owner_telegram_user_id="123"
    ).record
    return record.preview_id, record.entry_file_id


def test_image_and_pdf_are_streamed_inline_with_nosniff(tmp_path: Path) -> None:
    client, service = client_and_service(tmp_path)
    image = tmp_path / "files" / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"image-data")
    pdf = tmp_path / "files" / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\nminimal")

    image_id, image_file = publish(service, image)
    pdf_id, pdf_file = publish(service, pdf)
    image_response = client.get(f"/api/previews/{image_id}/files/{image_file}/raw")
    pdf_response = client.get(f"/api/previews/{pdf_id}/files/{pdf_file}/raw")

    assert image_response.content == image.read_bytes()
    assert image_response.headers["content-type"].startswith("image/png")
    assert pdf_response.content == pdf.read_bytes()
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    for response in (image_response, pdf_response):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("inline")
        assert str(tmp_path) not in str(response.headers)


def test_html_is_returned_as_sandboxed_srcdoc_not_an_executable_response(tmp_path: Path) -> None:
    client, service = client_and_service(tmp_path)
    document = tmp_path / "files" / "unsafe.html"
    document.write_text(
        '<script>alert(1)</script><a href="javascript:alert(2)">bad</a><h1>Safe</h1>',
        encoding="utf-8",
    )
    preview_id, file_id = publish(service, document)

    response = client.get(f"/api/previews/{preview_id}/files/{file_id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["kind"] == "html"
    assert "<script" not in payload["rendered_html"].lower()
    assert "javascript:" not in payload["rendered_html"].lower()
    assert "<h1>Safe</h1>" in payload["rendered_html"]
    assert payload["sandbox"] == ""
    assert client.get(f"/api/previews/{preview_id}/files/{file_id}/raw").status_code == 415
