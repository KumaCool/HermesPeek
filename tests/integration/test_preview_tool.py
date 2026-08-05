from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
PREVIEW_TOOL = ROOT / "integrations" / "hermes" / "preview_tool.py"


def load_preview_tool():
    spec = importlib.util.spec_from_file_location("preview_tool_contract", PREVIEW_TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def session_getter(values: dict[str, str]):
    return lambda name, default="": values.get(name, default)


def test_route_uses_request_scoped_dm_group_and_topic_context() -> None:
    tool = load_preview_tool()
    dm = tool.resolve_route(session_getter({
        "HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "6229635708",
        "HERMES_SESSION_USER_ID": "dm-owner",
    }))
    group = tool.resolve_route(session_getter({
        "HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "-1001234567890",
        "HERMES_SESSION_USER_ID": "group-owner",
    }))
    topic = tool.resolve_route(session_getter({
        "HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "-1001234567890",
        "HERMES_SESSION_USER_ID": "topic-owner", "HERMES_SESSION_THREAD_ID": "topic-thread",
    }))
    assert (dm.chat_id, dm.user_id, dm.chat_type, dm.thread_id) == ("6229635708", "dm-owner", "private", None)
    assert (group.chat_id, group.user_id, group.chat_type, group.thread_id) == ("-1001234567890", "group-owner", "group", None)
    assert (topic.chat_id, topic.user_id, topic.chat_type, topic.thread_id) == (
        "-1001234567890", "topic-owner", "supergroup", "topic-thread",
    )


@pytest.mark.parametrize("values", [
    {},
    {"HERMES_SESSION_PLATFORM": "discord", "HERMES_SESSION_CHAT_ID": "route", "HERMES_SESSION_USER_ID": "owner"},
    {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_USER_ID": "owner"},
    {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": "route"},
])
def test_route_rejects_missing_or_uncertain_context_without_environment_fallback(monkeypatch, values) -> None:
    tool = load_preview_tool()
    monkeypatch.setenv("HERMES_SESSION_CHAT_ID", "stale-home-route")
    with pytest.raises(tool.PreviewToolError) as caught:
        tool.resolve_route(session_getter(values))
    assert caught.value.code == "route_unavailable"
    assert "stale-home-route" not in str(caught.value)


def write_pointer(tmp_path: Path, *, mode: int = 0o600, symlink: bool = False, token: str | None = None):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"allowed_roots": [str(tmp_path / "files")], "state_dir": str(tmp_path / "state"),
                                  "external_base_url": "https://preview.example.test/",
                                  "telegram_bot_username": "PreviewFixtureBot"}))
    secret = tmp_path / "secrets.env"
    content = "OTHER_SECRET=ignored\n"
    if token is not None:
        content += f'HERMES_PEEK_TELEGRAM_BOT_TOKEN="{token}"\n'
    if symlink:
        target = tmp_path / "actual.env"; target.write_text(content); target.chmod(mode); secret.symlink_to(target)
    else:
        secret.write_text(content); secret.chmod(mode)
    pointer = tmp_path / "pointer.json"
    pointer.write_text(json.dumps({"config_file": str(config), "env_file": str(secret)}))
    return pointer, token


def test_secret_loader_reads_only_token_from_owned_private_regular_file(tmp_path: Path) -> None:
    tool = load_preview_tool()
    token = "fixture-token-value"
    pointer, _ = write_pointer(tmp_path, token=token)
    loaded = tool.load_install_config(pointer)
    assert loaded.token == token
    assert "OTHER_SECRET" not in repr(loaded)


@pytest.mark.parametrize("mode,symlink,token", [(0o644, False, "fixture-token"), (0o600, True, "fixture-token"), (0o600, False, None)])
def test_secret_loader_rejects_unsafe_or_missing_secret_without_leaking_values(tmp_path: Path, mode, symlink, token) -> None:
    tool = load_preview_tool()
    pointer, sentinel = write_pointer(tmp_path, mode=mode, symlink=symlink, token=token)
    with pytest.raises(tool.PreviewToolError) as caught:
        tool.load_install_config(pointer)
    assert caught.value.code == "secret_unavailable"
    assert not sentinel or sentinel not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def configured_delivery(tmp_path: Path, monkeypatch, *, chat_type="dm", thread=""):
    tool = load_preview_tool()
    files = tmp_path / "files"; files.mkdir(); document = files / "result.md"; document.write_text("# Result")
    pointer, token = write_pointer(tmp_path, token="fixture-token")
    chat_id = "-1001234567890" if chat_type == "forum" else "6229635708"
    values = {"HERMES_SESSION_PLATFORM": "telegram", "HERMES_SESSION_CHAT_ID": chat_id,
              "HERMES_SESSION_USER_ID": "request-owner", "HERMES_SESSION_THREAD_ID": thread}
    monkeypatch.setattr(tool, "get_session_env", session_getter(values))
    monkeypatch.setattr(tool, "POINTER_FILE", pointer)
    return tool, document, token


def test_handler_sends_exactly_once_and_returns_redacted_success(tmp_path: Path, monkeypatch) -> None:
    tool, document, token = configured_delivery(tmp_path, monkeypatch)
    requests = []
    monkeypatch.setattr(tool, "telegram_transport", lambda: httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, json={"ok": True, "result": {"message_id": 17}})
    ))
    result = json.loads(tool.send_preview(files=[str(document)], entry=str(document), title="Result"))
    assert result == {"success": True, "sent": True, "message_id": 17, "button_type": "mini_app"}
    assert len(requests) == 1
    serialized = json.dumps(result)
    for sentinel in (token, str(document), "request-route", "request-owner"):
        assert sentinel not in serialized


def test_topic_preserves_thread_and_owner_and_telegram_failure_is_safe(tmp_path: Path, monkeypatch) -> None:
    tool, document, token = configured_delivery(tmp_path, monkeypatch, chat_type="forum", thread="42")
    captured = []
    monkeypatch.setattr(tool, "telegram_transport", lambda: httpx.MockTransport(
        lambda request: captured.append(json.loads(request.content)) or httpx.Response(503, json={"ok": False})
    ))
    result = json.loads(tool.send_preview(files=[str(document)], entry=str(document), title="Result"))
    assert result["success"] is False and result["sent"] is False
    assert result["error_code"] == "delivery_failed"
    assert captured[0]["message_thread_id"] == 42
    record = next((tmp_path / "state" / "previews").glob("*.json")).read_text()
    assert "request-owner" in record
    assert token not in json.dumps(result) and str(document) not in json.dumps(result)


def test_invalid_input_fails_before_send(tmp_path: Path, monkeypatch) -> None:
    tool, document, _ = configured_delivery(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(tool, "telegram_transport", lambda: calls.append(True))
    result = json.loads(tool.send_preview(files=["relative.md"], entry=str(document), title=""))
    assert result["success"] is False and result["error_code"] == "invalid_input"
    assert calls == []
