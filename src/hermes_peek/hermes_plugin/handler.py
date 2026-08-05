from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy
from hermes_peek.registry import LaunchRegistry, PreviewRegistry
from hermes_peek.service import PreviewService
from hermes_peek.telegram import TelegramClient, build_mini_app_direct_link


def telegram_transport():
    return None


def _spool_for(state_dir: Path, session_id: str) -> Path | None:
    directory = state_dir / "collector"
    if not directory.is_dir():
        return None
    for candidate in directory.glob("*.json"):
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("session_id") == session_id:
            return candidate
    return None


def publish_action(state_dir: Path, session_id: str, user_id: str, *, topic: bool = False) -> dict[str, str] | None:
    """Publish one session spool and consume it after action creation."""
    settings = Settings.from_env()
    spool = _spool_for(state_dir, session_id)
    if spool is None:
        return None
    record = json.loads(spool.read_text(encoding="utf-8"))
    files = tuple(Path(item) for item in record.get("paths", []))
    if not files:
        return None
    service = PreviewService(
        registry=PreviewRegistry(settings.state_dir),
        path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
        default_ttl_seconds=settings.default_ttl_seconds,
        external_base_url=str(settings.external_base_url) if settings.external_base_url else None,
    )
    published = service.publish(
        files, entry=files[0], title="Hermes files", owner_telegram_user_id=user_id,
    )
    if published.url is None:
        return None
    action_url = published.url
    if topic and settings.telegram_bot_username:
        launch_expires = published.record.created_at + timedelta(
            seconds=settings.launch_ref_ttl_seconds
        )
        if published.record.expires_at is not None:
            launch_expires = min(launch_expires, published.record.expires_at)
        launch_ref = LaunchRegistry(state_dir).create(
            preview_id=published.record.preview_id,
            owner_telegram_user_id=user_id,
            expires_at=launch_expires,
        )
        action_url = build_mini_app_direct_link(
            settings.telegram_bot_username,
            launch_ref,
            short_name=settings.telegram_mini_app_short_name,
            mode=settings.telegram_mini_app_mode,
        )
    if action_url is None:
        return None
    action = {"type": "url", "label": "Open preview", "url": action_url}
    spool.unlink()
    return action


def handle(event_type: str, context: dict[str, Any]) -> None:
    if event_type != "agent:end" or context.get("platform") != "telegram":
        return
    session_id = str(context.get("session_id") or "")
    user_id = str(context.get("user_id") or "")
    chat_id = str(context.get("chat_id") or "")
    if not session_id or not user_id or not chat_id:
        return
    try:
        settings = Settings.from_env()
        spool = _spool_for(settings.state_dir, session_id)
        if spool is None:
            return
        record = json.loads(spool.read_text(encoding="utf-8"))
        files = tuple(Path(item) for item in record.get("paths", []))
        if not files:
            return
        service = PreviewService(
            registry=PreviewRegistry(settings.state_dir),
            path_policy=PathPolicy(settings.allowed_roots, max_file_bytes=settings.max_file_bytes),
            default_ttl_seconds=settings.default_ttl_seconds,
            external_base_url=str(settings.external_base_url) if settings.external_base_url else None,
        )
        published = service.publish(
            files, entry=files[0], title="Hermes files", owner_telegram_user_id=user_id,
        )
        if published.url is None:
            return
        token = os.environ.get("HERMES_PEEK_TELEGRAM_BOT_TOKEN")
        if not token:
            return
        chat_type = str(context.get("chat_type") or "")
        thread = str(context.get("thread_id") or "")
        mini_app_url = None
        if chat_type == "forum" and settings.telegram_bot_username:
            launch_ref = LaunchRegistry(settings.state_dir).create(
                preview_id=published.record.preview_id,
                owner_telegram_user_id=user_id,
                expires_at=published.record.expires_at or (
                    published.record.created_at + timedelta(seconds=settings.launch_ref_ttl_seconds)
                ),
            )
            mini_app_url = build_mini_app_direct_link(
                settings.telegram_bot_username, launch_ref,
                short_name=settings.telegram_mini_app_short_name,
                mode=settings.telegram_mini_app_mode,
            )
        TelegramClient(token, transport=telegram_transport()).send_preview(
            chat_id=chat_id,
            chat_type="private" if chat_type == "dm" else "supergroup" if chat_type == "forum" else "group",
            preview_url=published.url,
            mini_app_url=mini_app_url,
            title="Hermes files",
            thread_id=int(thread) if chat_type == "forum" and thread else None,
        )
        spool.unlink()
    except Exception:
        # Gateway hooks must never affect delivery of the normal agent response.
        return
