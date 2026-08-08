from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from hermes_peek.app import create_app
from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import LaunchRegistry, PreviewRegistry
from hermes_peek.service import PreviewService


def signed_init_data(
    bot_token: str,
    *,
    user_id: str,
    auth_date: datetime,
) -> str:
    values = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": "query-1",
        "user": json.dumps({"id": int(user_id), "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def build_client(
    tmp_path: Path,
    *,
    bot_token: str = "test:token",
    external_base_url: str = "https://preview.example.test/",
) -> tuple[TestClient, PreviewService]:
    root = tmp_path / "files"
    root.mkdir()
    settings = Settings(
        allowed_roots=(root,),
        state_dir=tmp_path / "state",
        max_file_bytes=1024,
        default_ttl_seconds=3600,
        external_base_url=external_base_url,
        development=False,
    )
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=str(settings.external_base_url),
    )
    return TestClient(
        create_app(settings, service=service, bot_token=bot_token),
        base_url="https://testserver",
    ), service


def publish(service: PreviewService, path: Path, *, owner: str = "123") -> str:
    return service.publish(
        (path,), entry=path, title="Private", owner_telegram_user_id=owner
    ).record.preview_id


def test_auth_api_sets_secure_session_and_protects_preview_routes(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    client, service = build_client(tmp_path)
    document = tmp_path / "files" / "private.md"
    document.write_text("private", encoding="utf-8")
    preview_id = publish(service, document)

    before = client.get(f"/api/previews/{preview_id}")
    authenticated = client.post(
        "/api/auth/telegram",
        json={"preview_id": preview_id, "init_data": signed_init_data("test:token", auth_date=now, user_id="123")},
    )
    after = client.get(f"/api/previews/{preview_id}")

    assert before.status_code == 401
    assert authenticated.status_code == 204
    cookie = authenticated.headers["set-cookie"]
    cookie_lower = cookie.lower()
    assert "httponly" in cookie_lower and "secure" in cookie_lower and "samesite=lax" in cookie_lower
    assert "Path=/" in cookie
    assert "test:token" not in authenticated.text + cookie
    assert after.status_code == 200

    logout = client.delete("/api/auth/session")
    assert logout.status_code == 204
    assert client.get(f"/api/previews/{preview_id}").status_code == 401


def test_launch_auth_resolves_opaque_reference_and_rejects_path_traversal(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    client, service = build_client(tmp_path)
    document = tmp_path / "files" / "private.md"
    document.write_text("private", encoding="utf-8")
    preview_id = publish(service, document)
    record = service.registry.get(preview_id)
    reference = LaunchRegistry(tmp_path / "state").create(
        preview_id=preview_id, owner_telegram_user_id="123", expires_at=record.expires_at or (now + __import__("datetime").timedelta(hours=1)),
    )
    init_data = signed_init_data("test:token", auth_date=now, user_id="123")

    authenticated = client.post(
        "/api/auth/telegram/launch", json={"launch_ref": reference, "init_data": init_data}
    )
    traversal = client.post(
        "/api/auth/telegram/launch",
        json={"launch_ref": "lr_../../etc/passwd", "init_data": init_data},
    )

    assert authenticated.status_code == 204
    assert authenticated.headers["X-HermesPeek-Preview-Id"] == preview_id
    assert traversal.status_code == 404


def test_base_path_scopes_both_login_cookies_and_logout_deletion(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    client, service = build_client(
        tmp_path, external_base_url="https://preview.example.test/apps/hermespeek/"
    )
    document = tmp_path / "files" / "private.md"
    document.write_text("private", encoding="utf-8")
    preview_id = publish(service, document)
    record = service.registry.get(preview_id)
    reference = LaunchRegistry(tmp_path / "state").create(
        preview_id=preview_id,
        owner_telegram_user_id="123",
        expires_at=record.expires_at or (now + __import__("datetime").timedelta(hours=1)),
    )
    init_data = signed_init_data("test:token", auth_date=now, user_id="123")

    direct = client.post(
        "/api/auth/telegram", json={"preview_id": preview_id, "init_data": init_data}
    )
    launch = client.post(
        "/api/auth/telegram/launch", json={"launch_ref": reference, "init_data": init_data}
    )
    logout = client.delete("/api/auth/session")

    assert "Path=/apps/hermespeek" in direct.headers["set-cookie"]
    assert "Path=/apps/hermespeek" in launch.headers["set-cookie"]
    assert "Path=/apps/hermespeek" in logout.headers["set-cookie"]


def test_auth_api_rejects_wrong_owner_unknown_and_revoked_preview(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    client, service = build_client(tmp_path)
    document = tmp_path / "files" / "private.md"
    document.write_text("private", encoding="utf-8")
    preview_id = publish(service, document, owner="999")
    payload = signed_init_data("test:token", auth_date=now, user_id="123")

    wrong_owner = client.post(
        "/api/auth/telegram", json={"preview_id": preview_id, "init_data": payload}
    )
    unknown = client.post(
        "/api/auth/telegram", json={"preview_id": "pv_" + "z" * 43, "init_data": payload}
    )
    service.revoke(preview_id)
    revoked = client.post(
        "/api/auth/telegram", json={"preview_id": preview_id, "init_data": payload}
    )

    assert wrong_owner.status_code == 403
    assert unknown.status_code == 404
    assert revoked.status_code == 410
    combined = wrong_owner.text + unknown.text + revoked.text
    assert "test:token" not in combined
    assert payload not in combined
    assert str(tmp_path) not in combined
