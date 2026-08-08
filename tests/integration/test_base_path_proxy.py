from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient
from starlette.responses import Response

from hermes_peek.app import create_app
from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import LaunchRegistry, PreviewRegistry
from hermes_peek.service import PreviewService


class StrippedPrefixProxy:
    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send) -> None:
        path = scope["path"]
        if path == self.prefix:
            upstream_path = "/"
        elif path.startswith(f"{self.prefix}/"):
            upstream_path = path[len(self.prefix) :]
        else:
            await Response(status_code=404)(scope, receive, send)
            return
        upstream_scope = dict(scope, path=upstream_path, raw_path=upstream_path.encode("ascii"))
        await self.app(upstream_scope, receive, send)


def signed_init_data(bot_token: str, *, user_id: str) -> str:
    values = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "query_id": "proxy-contract",
        "user": json.dumps({"id": int(user_id), "first_name": "Proxy"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_stripped_prefix_proxy_exposes_complete_public_preview_chain(tmp_path: Path) -> None:
    prefix = "/apps/hermespeek"
    bot_token = "test:token"
    owner = "123"
    root = tmp_path / "files"
    root.mkdir()
    document = root / "note.md"
    document.write_text("# Through proxy", encoding="utf-8")
    image = root / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nproxy")
    settings = Settings(
        allowed_roots=(root,),
        state_dir=tmp_path / "state",
        max_file_bytes=4096,
        default_ttl_seconds=3600,
        external_base_url="https://preview.example.test/apps/hermespeek/",
        development=False,
    )
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=str(settings.external_base_url),
    )
    published = service.publish(
        (document, image), entry=document, title="Proxy Preview", owner_telegram_user_id=owner
    )
    preview_id = published.record.preview_id
    text_id = next(item.id for item in published.record.files if item.display_path == "note.md")
    image_id = next(item.id for item in published.record.files if item.display_path == "pixel.png")
    launch_ref = LaunchRegistry(settings.state_dir).create(
        preview_id=preview_id,
        owner_telegram_user_id=owner,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    upstream = create_app(settings, service=service, bot_token=bot_token)
    public = TestClient(
        StrippedPrefixProxy(upstream, prefix), base_url="https://preview.example.test"
    )

    health = public.get(f"{prefix}/healthz")
    home = public.get(f"{prefix}/")
    shell = public.get(f"{prefix}/p/{preview_id}")
    script = public.get(f"{prefix}/static/app.js")
    launch = public.post(
        f"{prefix}/api/auth/telegram/launch",
        json={"launch_ref": launch_ref, "init_data": signed_init_data(bot_token, user_id=owner)},
    )
    metadata = public.get(f"{prefix}/api/previews/{preview_id}")
    text = public.get(f"{prefix}/api/previews/{preview_id}/files/{text_id}")
    raw = public.get(f"{prefix}/api/previews/{preview_id}/files/{image_id}/raw")
    internal_health = TestClient(upstream).get("/healthz")

    assert (health.status_code, health.json()) == (
        200,
        {"status": "ok", "service": "hermes-peek"},
    )
    assert home.status_code == shell.status_code == script.status_code == 200
    assert f"fetch('{prefix}/api/auth/telegram/launch'" in home.text
    assert f"location.replace(`{prefix}/p/${{previewId}}`)" in home.text
    assert f'href="{prefix}/static/app.css"' in shell.text
    assert f'src="{prefix}/static/app.js"' in shell.text
    assert f'data-base-path="{prefix}"' in shell.text
    assert launch.status_code == 204
    assert launch.headers["X-HermesPeek-Preview-Id"] == preview_id
    assert metadata.status_code == 200 and metadata.json()["preview_id"] == preview_id
    assert text.status_code == 200 and text.json()["content"] == "# Through proxy"
    assert raw.status_code == 200 and raw.content == image.read_bytes()
    assert internal_health.status_code == 200
    assert public.get("/healthz").status_code == 404
