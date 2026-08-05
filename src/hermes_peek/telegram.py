from __future__ import annotations

from typing import Any, Literal
import re
from urllib.parse import urlencode

import httpx

ChatType = Literal["private", "group", "supergroup"]
_BOT_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_SHORT_NAME = re.compile(r"^[A-Za-z0-9_]{3,30}$")
_LAUNCH_REF = re.compile(r"^lr_[A-Za-z0-9_-]{20,64}$")


def build_mini_app_direct_link(
    bot_username: str,
    launch_ref: str,
    *,
    short_name: str | None = None,
    mode: str = "compact",
) -> str:
    username = bot_username.removeprefix("@").strip()
    if not _BOT_USERNAME.fullmatch(username) or not _LAUNCH_REF.fullmatch(launch_ref):
        raise ValueError("bot username and launch reference are required")
    if short_name is not None and not _SHORT_NAME.fullmatch(short_name):
        raise ValueError("invalid Mini App short name")
    if mode not in {"", "compact"}:
        raise ValueError("unsupported Mini App mode")
    path = f"https://t.me/{username}"
    if short_name:
        path += f"/{short_name}"
    query = {"startapp": launch_ref}
    if mode:
        query["mode"] = mode
    return f"{path}?{urlencode(query)}"


class TelegramNotificationError(RuntimeError):
    """A safe, actionable Telegram notification failure."""


def build_notification_payload(
    *,
    chat_id: str,
    chat_type: ChatType | str,
    preview_url: str,
    title: str,
    thread_id: int | None = None,
    mini_app_url: str | None = None,
) -> dict[str, Any]:
    if chat_type not in {"private", "group", "supergroup"}:
        raise ValueError("chat_type must be private, group, or supergroup")
    if thread_id is not None and (chat_type != "supergroup" or type(thread_id) is not int):
        raise ValueError("thread_id must be an integer and is only valid for supergroups")
    if not preview_url.startswith("https://"):
        raise ValueError("preview_url must use HTTPS")

    button: dict[str, Any] = {"text": "Open preview"}
    if chat_type == "private":
        button["web_app"] = {"url": preview_url}
    else:
        button["url"] = mini_app_url or preview_url

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": f"Preview ready: {title}",
        "reply_markup": {"inline_keyboard": [[button]]},
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    return payload


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not token:
            raise ValueError("Telegram Bot Token is required")
        self._token = token
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def send_preview(
        self,
        *,
        chat_id: str,
        chat_type: ChatType | str,
        preview_url: str,
        title: str,
        thread_id: int | None = None,
        mini_app_url: str | None = None,
    ) -> dict[str, Any]:
        payload = build_notification_payload(
            chat_id=chat_id,
            chat_type=chat_type,
            preview_url=preview_url,
            title=title,
            thread_id=thread_id,
            mini_app_url=mini_app_url,
        )
        endpoint = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout_seconds,
            ) as client:
                response = client.post(endpoint, json=payload)
        except httpx.HTTPError as exc:
            raise TelegramNotificationError("Telegram API request failed") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramNotificationError("Telegram API returned an invalid response") from exc
        if response.status_code >= 400 or body.get("ok") is not True:
            raise TelegramNotificationError(
                f"Telegram API rejected the notification (HTTP {response.status_code})"
            )
        result = body.get("result")
        if not isinstance(result, dict):
            raise TelegramNotificationError("Telegram API returned an invalid result")
        return result
