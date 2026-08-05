from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx


HANDLER = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "handler.py"


def load_handler():
    spec = importlib.util.spec_from_file_location("hermes_peek_hook", HANDLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_plugin():
    plugin = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_peek_plugin",
        plugin,
        submodule_search_locations=[str(plugin.parent)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_spool(state: Path, session: str, paths: list[Path], name: str = "item") -> Path:
    directory = state / "collector"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.json"
    target.write_text(json.dumps({"session_id": session, "task_id": "", "paths": [str(p) for p in paths]}))
    return target


def test_non_telegram_and_empty_collector_are_silent(monkeypatch, tmp_path: Path) -> None:
    hook = load_handler()
    monkeypatch.setenv("HERMES_PEEK_STATE_DIR", str(tmp_path / "state"))
    assert hook.handle("agent:end", {"platform": "discord", "session_id": "s"}) is None
    assert hook.handle("agent:end", {"platform": "telegram", "session_id": "s"}) is None


def test_agent_end_publishes_sends_to_topic_and_consumes_spool(monkeypatch, tmp_path: Path) -> None:
    hook = load_handler()
    root = tmp_path / "files"
    root.mkdir()
    document = root / "result.md"
    document.write_text("# Result")
    state = tmp_path / "state"
    spool = write_spool(state, "session-1", [document])
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("HERMES_PEEK_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_PEEK_EXTERNAL_BASE_URL", "https://preview.example/")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_USERNAME", "ExamplePreviewBot")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_TOKEN", "[REDACTED]")
    sent = {}

    def transport():
        def handler(request: httpx.Request) -> httpx.Response:
            sent.update(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
        return httpx.MockTransport(handler)

    monkeypatch.setattr(hook, "telegram_transport", transport)
    hook.handle("agent:end", {
        "platform": "telegram", "session_id": "session-1", "user_id": "123",
        "chat_id": "-1001", "chat_type": "forum", "thread_id": "6030",
    })
    assert sent["message_thread_id"] == 6030
    button_url = sent["reply_markup"]["inline_keyboard"][0][0]["url"]
    assert button_url.startswith("https://t.me/ExamplePreviewBot?startapp=lr_")
    assert "preview.example" not in button_url and str(document) not in button_url
    assert not spool.exists()


def test_failure_keeps_spool_and_duplicate_delivery_is_suppressed(monkeypatch, tmp_path: Path) -> None:
    hook = load_handler()
    root = tmp_path / "files"
    root.mkdir()
    document = root / "result.md"
    document.write_text("x")
    state = tmp_path / "state"
    spool = write_spool(state, "s", [document])
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("HERMES_PEEK_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_PEEK_EXTERNAL_BASE_URL", "https://preview.example/")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_USERNAME", "ExamplePreviewBot")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_TOKEN", "[REDACTED]")
    monkeypatch.setattr(hook, "telegram_transport", lambda: httpx.MockTransport(
        lambda _: httpx.Response(500, json={"ok": False})
    ))
    context = {"platform": "telegram", "session_id": "s", "user_id": "1", "chat_id": "1", "chat_type": "dm", "thread_id": ""}
    hook.handle("agent:end", context)
    assert spool.exists()

    calls = 0
    def success_transport():
        def send(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.MockTransport(send)
    monkeypatch.setattr(hook, "telegram_transport", success_transport)
    hook.handle("agent:end", context)
    hook.handle("agent:end", context)
    assert calls == 1


def test_final_message_action_publishes_preview_without_bot_send(monkeypatch, tmp_path: Path) -> None:
    plugin = load_plugin()
    root = tmp_path / "files"
    root.mkdir()
    document = root / "result.md"
    document.write_text("# Result")
    state = tmp_path / "state"
    spool = write_spool(state, "session-action", [document])
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("HERMES_PEEK_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_PEEK_EXTERNAL_BASE_URL", "https://preview.example/")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_USERNAME", "ExamplePreviewBot")
    monkeypatch.delenv("HERMES_PEEK_TELEGRAM_BOT_TOKEN", raising=False)

    action = plugin._final_message_actions(
        session_id="session-action",
        platform="telegram",
        user_id="123",
        chat_id="-1001",
        thread_id="6030",
        chat_type="forum",
        response_text="Done.",
    )

    assert action == {
        "type": "url",
        "label": "Open preview",
        "url": action["url"],
    }
    assert action["url"].startswith("https://t.me/ExamplePreviewBot?startapp=lr_")
    assert "preview.example" not in action["url"] and str(document) not in action["url"]
    assert not spool.exists()


def test_plugin_registers_collector_final_action_and_preview_tool() -> None:
    plugin = load_plugin()
    hooks = []
    tools = []

    class Context:
        def register_hook(self, name, callback):
            hooks.append((name, callback))

        def register_tool(self, **kwargs):
            tools.append(kwargs)

    plugin.register(Context())

    assert [name for name, _ in hooks] == ["post_tool_call", "final_message_actions"]
    assert len(tools) == 1
    registered = tools[0]
    assert registered["name"] == "hermes_peek_send_preview"
    schema = registered["schema"]
    assert schema["name"] == "hermes_peek_send_preview"
    assert set(schema["parameters"]["properties"]) == {"files", "entry", "title"}
    assert set(schema["parameters"]["required"]) == {"files", "entry", "title"}
    assert registered["handler"]
