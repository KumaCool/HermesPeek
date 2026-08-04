from __future__ import annotations

from typing import Any, Protocol
from .lifecycle import LifecycleError

class Transport(Protocol):
    def call(self, method: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]: ...

class TelegramLifecycle:
    def __init__(self, transport: Transport) -> None: self.transport = transport
    def _call(self, method: str, token: str, payload=None):
        try: response = self.transport.call(method, token, payload)
        except Exception as exc: raise LifecycleError(f"Telegram {method} failed: [REDACTED]") from exc
        if not response.get("ok"): raise LifecycleError(f"Telegram {method} failed: [REDACTED]")
        return response.get("result")
    def inspect(self, token: str, *, expected_bot_id: int | None = None) -> dict[str, Any]:
        identity = self._call("getMe", token)
        if expected_bot_id is not None and identity.get("id") != expected_bot_id:
            raise LifecycleError("Telegram Bot identity mismatch")
        webhook = self._call("getWebhookInfo", token)
        return {"bot_id": identity.get("id"), "bot_username": identity.get("username"),
                "webhook_configured": bool(webhook.get("url")), "main_mini_app_requires_botfather": True}
    def set_menu(self, token: str, url: str) -> dict[str, Any]:
        old = self._call("getChatMenuButton", token)
        applied = {"type": "web_app", "text": "Preview", "web_app": {"url": url}}
        self._call("setChatMenuButton", token, {"menu_button": applied})
        return {"setting": "chat_menu_button", "before": old, "applied": applied}
    def rollback(self, token: str, change: dict[str, Any]) -> None:
        if change.get("setting") == "chat_menu_button":
            current = self._call("getChatMenuButton", token)
            if current == change.get("applied"):
                self._call("setChatMenuButton", token, {"menu_button": change["before"]})
