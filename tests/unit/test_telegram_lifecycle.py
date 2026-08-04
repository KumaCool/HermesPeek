import pytest

from hermes_peek.lifecycle import LifecycleError
from hermes_peek.telegram_lifecycle import TelegramLifecycle

TOKEN = "123456789:" + "T" * 35

class FakeTransport:
    def __init__(self, responses): self.responses, self.calls = responses, []
    def call(self, method, token, payload=None):
        self.calls.append((method, payload))
        return self.responses[method]

def test_get_me_and_webhook_checks_are_read_only():
    transport = FakeTransport({"getMe": {"ok": True, "result": {"id": 7, "username": "peek_bot"}},
                               "getWebhookInfo": {"ok": True, "result": {"url": "https://hook.invalid"}}})
    result = TelegramLifecycle(transport).inspect(TOKEN, expected_bot_id=7)
    assert result["bot_username"] == "peek_bot"
    assert [call[0] for call in transport.calls] == ["getMe", "getWebhookInfo"]

def test_wrong_bot_fails_without_settings_side_effect_and_redacts_token():
    transport = FakeTransport({"getMe": {"ok": True, "result": {"id": 8, "username": "other"}}})
    with pytest.raises(LifecycleError) as error:
        TelegramLifecycle(transport).inspect(TOKEN, expected_bot_id=7)
    assert TOKEN not in str(error.value)
    assert transport.calls == [("getMe", None)]

def test_menu_change_records_old_value_and_can_rollback():
    transport = FakeTransport({"getChatMenuButton": {"ok": True, "result": {"type": "default"}},
                               "setChatMenuButton": {"ok": True, "result": True}})
    lifecycle = TelegramLifecycle(transport)
    change = lifecycle.set_menu(TOKEN, "https://preview.example.test")
    transport.responses["getChatMenuButton"] = {"ok": True, "result": change["applied"]}
    lifecycle.rollback(TOKEN, change)
    assert [x[0] for x in transport.calls] == ["getChatMenuButton", "setChatMenuButton", "getChatMenuButton", "setChatMenuButton"]


def test_rollback_preserves_a_later_external_menu_change():
    transport = FakeTransport({"getChatMenuButton": {"ok": True, "result": {"type": "default"}},
                               "setChatMenuButton": {"ok": True, "result": True}})
    lifecycle = TelegramLifecycle(transport)
    change = lifecycle.set_menu(TOKEN, "https://preview.example.test")
    transport.responses["getChatMenuButton"] = {
        "ok": True,
        "result": {"type": "web_app", "text": "Other", "web_app": {"url": "https://other.example.test"}},
    }

    lifecycle.rollback(TOKEN, change)

    assert [x[0] for x in transport.calls].count("setChatMenuButton") == 1
