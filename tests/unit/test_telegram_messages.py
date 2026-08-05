from __future__ import annotations

import json

import httpx
import pytest

from hermes_peek.telegram import TelegramClient, TelegramNotificationError, build_mini_app_direct_link, build_notification_payload


PREVIEW_URL = "https://preview.example/p/pv_opaque"


def test_main_mini_app_direct_link_uses_opaque_reference() -> None:
    reference = "lr_" + "a" * 32
    url = build_mini_app_direct_link("@KumaHermes666_bot", reference)
    assert url == f"https://t.me/KumaHermes666_bot?startapp={reference}&mode=compact"


def test_named_mini_app_short_name_uses_official_three_to_thirty_character_contract() -> None:
    reference = "lr_" + "a" * 32
    assert f"/{'a' * 30}?" in build_mini_app_direct_link(
        "KumaHermes666_bot", reference, short_name="a" * 30
    )
    with pytest.raises(ValueError, match="short name"):
        build_mini_app_direct_link("KumaHermes666_bot", reference, short_name="a" * 31)


@pytest.mark.parametrize("reference", ["lr_short", "lr_../../etc/passwd", "pv_" + "a" * 32])
def test_direct_link_rejects_invalid_launch_reference(reference: str) -> None:
    with pytest.raises(ValueError):
        build_mini_app_direct_link("KumaHermes666_bot", reference)


def test_private_chat_uses_web_app_button() -> None:
    payload = build_notification_payload(
        chat_id="123", chat_type="private", preview_url=PREVIEW_URL, title="Result"
    )
    assert payload["chat_id"] == "123"
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Open preview", "web_app": {"url": PREVIEW_URL}}
    assert "message_thread_id" not in payload


def test_group_and_topic_use_direct_link_and_integer_thread_id() -> None:
    group = build_notification_payload(
        chat_id="-1001", chat_type="group", preview_url=PREVIEW_URL, title="Result"
    )
    topic = build_notification_payload(
        chat_id="-1002", chat_type="supergroup", preview_url=PREVIEW_URL,
        title="Result", thread_id=6030,
    )
    assert group["reply_markup"]["inline_keyboard"][0][0]["url"] == PREVIEW_URL
    assert "web_app" not in group["reply_markup"]["inline_keyboard"][0][0]
    assert topic["message_thread_id"] == 6030
    assert isinstance(topic["message_thread_id"], int)
    assert topic["reply_markup"]["inline_keyboard"][0][0]["url"] == PREVIEW_URL


@pytest.mark.parametrize(
    ("chat_type", "thread_id"),
    [("private", 1), ("group", 1), ("supergroup", "6030"), ("channel", None)],
)
def test_invalid_chat_and_thread_combinations_are_rejected(chat_type: str, thread_id: object) -> None:
    with pytest.raises(ValueError):
        build_notification_payload(
            chat_id="1", chat_type=chat_type, preview_url=PREVIEW_URL,
            title="Result", thread_id=thread_id,  # type: ignore[arg-type]
        )


def test_mock_transport_receives_send_message_without_token_leak() -> None:
    token = "123456:[REDACTED]"
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = TelegramClient(token, transport=httpx.MockTransport(handler))
    result = client.send_preview(
        chat_id="123", chat_type="private", preview_url=PREVIEW_URL, title="Result"
    )

    assert result == {"message_id": 42}
    assert str(captured["url"]).endswith("/sendMessage")
    assert captured["payload"] == build_notification_payload(
        chat_id="123", chat_type="private", preview_url=PREVIEW_URL, title="Result"
    )


def test_api_and_network_errors_are_actionable_and_redact_token() -> None:
    token = "123456:[REDACTED]"

    def api_error(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": f"bad {token}"})

    with pytest.raises(TelegramNotificationError) as api_exc:
        TelegramClient(token, transport=httpx.MockTransport(api_error)).send_preview(
            chat_id="1", chat_type="private", preview_url=PREVIEW_URL, title="Result"
        )
    assert token not in str(api_exc.value)
    assert "Telegram API rejected" in str(api_exc.value)

    def network_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed at {request.url}", request=request)

    with pytest.raises(TelegramNotificationError) as network_exc:
        TelegramClient(token, transport=httpx.MockTransport(network_error)).send_preview(
            chat_id="1", chat_type="private", preview_url=PREVIEW_URL, title="Result"
        )
    assert token not in str(network_exc.value)
    assert "Telegram API request failed" in str(network_exc.value)
