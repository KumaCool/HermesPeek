from __future__ import annotations

import json
from pathlib import Path

import httpx

from hermes_peek.cli import main
from hermes_peek.registry import PreviewRegistry


def environment(monkeypatch, tmp_path: Path) -> Path:
    root = tmp_path / "files"
    root.mkdir()
    monkeypatch.setenv("HERMES_PEEK_ALLOWED_ROOTS", str(root))
    monkeypatch.setenv("HERMES_PEEK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HERMES_PEEK_EXTERNAL_BASE_URL", "https://preview.example.test/")
    monkeypatch.setenv("HERMES_PEEK_TELEGRAM_BOT_TOKEN", "[REDACTED]")
    return root


def test_publish_notify_sends_mock_message(monkeypatch, tmp_path: Path, capsys) -> None:
    root = environment(monkeypatch, tmp_path)
    document = root / "result.md"
    document.write_text("# Result", encoding="utf-8")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    monkeypatch.setattr(
        "hermes_peek.cli.telegram_transport",
        lambda: httpx.MockTransport(handler),
    )
    result = main([
        "publish", str(document), "--entry", str(document), "--title", "Result",
        "--owner", "123", "--notify", "--chat-id", "-1001",
        "--chat-type", "supergroup", "--thread-id", "6030",
    ])

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["notified"] is True
    assert output["message_id"] == 9
    assert output["url"].startswith("https://preview.example.test/p/")
    sent = captured["payload"]
    assert isinstance(sent, dict)
    assert sent["message_thread_id"] == 6030
    assert sent["reply_markup"]["inline_keyboard"][0][0]["url"] == output["url"]
    assert str(tmp_path) not in json.dumps(output)


def test_notification_failure_keeps_preview_and_returns_nonzero(monkeypatch, tmp_path: Path, capsys) -> None:
    root = environment(monkeypatch, tmp_path)
    document = root / "result.md"
    document.write_text("# Result", encoding="utf-8")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "description": "failure"})

    monkeypatch.setattr(
        "hermes_peek.cli.telegram_transport",
        lambda: httpx.MockTransport(handler),
    )
    result = main([
        "publish", str(document), "--entry", str(document), "--title", "Result",
        "--owner", "123", "--notify", "--chat-id", "123", "--chat-type", "private",
    ])
    captured = capsys.readouterr()

    assert result != 0
    assert "Preview was published, but Telegram notification failed" in captured.err
    assert "[REDACTED]" not in captured.err
    records = list(PreviewRegistry(tmp_path / "state").previews_dir.glob("*.json"))
    assert len(records) == 1


def test_notify_requires_routing_token_and_external_url(monkeypatch, tmp_path: Path, capsys) -> None:
    root = environment(monkeypatch, tmp_path)
    document = root / "result.md"
    document.write_text("# Result", encoding="utf-8")

    for missing in (
        ["--chat-type", "private"],
        ["--chat-id", "123"],
    ):
        result = main([
            "publish", str(document), "--entry", str(document), "--title", "Result",
            "--owner", "123", "--notify", *missing,
        ])
        assert result != 0
        capsys.readouterr()
