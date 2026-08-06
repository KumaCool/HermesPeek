from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .collector import collect_tool_result


_preview_delivery_lock = threading.Lock()
_preview_delivered_sessions: set[str] = set()


def _reset_preview_delivery_state(session_id: str = "", **_: Any) -> None:
    if not session_id:
        return
    with _preview_delivery_lock:
        _preview_delivered_sessions.discard(session_id)


def _record_successful_preview_delivery(
    tool_name: str = "", result: Any = None, session_id: str = "", **_: Any,
) -> None:
    if tool_name != "hermes_peek_send_preview" or not session_id:
        return
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return
    if not isinstance(payload, dict) or payload.get("success") is not True or payload.get("sent") is not True:
        return
    with _preview_delivery_lock:
        _preview_delivered_sessions.add(session_id)


def _suppress_confirmation_after_preview(
    response_text: str = "", session_id: str = "", **_: Any,
) -> str | None:
    if not response_text or not session_id:
        return None
    with _preview_delivery_lock:
        delivered = session_id in _preview_delivered_sessions
        _preview_delivered_sessions.discard(session_id)
    return "NO_REPLY" if delivered else None


def _shared_config() -> dict[str, Any]:
    filename = os.environ.get("HERMES_PEEK_CONFIG_FILE")
    if not filename:
        try:
            pointer = json.loads((Path(__file__).parent / ".hermes-peek-config.json").read_text(encoding="utf-8"))
            filename = pointer.get("config_file") if isinstance(pointer, dict) else None
        except (OSError, ValueError, TypeError):
            filename = None
    if not isinstance(filename, str) or not filename:
        return {}
    try:
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _configured_roots() -> tuple[Path, ...]:
    value = os.environ.get("HERMES_PEEK_ALLOWED_ROOTS", "")
    if not value:
        return tuple(Path(item) for item in _shared_config().get("allowed_roots", ()))
    return tuple(Path(item) for item in value.split(os.pathsep) if item)


def _configured_state_dir() -> Path | None:
    value = os.environ.get("HERMES_PEEK_STATE_DIR") or _shared_config().get("state_dir")
    return Path(value) if isinstance(value, str) and value else None


def _post_tool_call(tool_name: str = "", args: Any = None, result: Any = None,
                    session_id: str = "", task_id: str = "", **_: Any) -> None:
    _record_successful_preview_delivery(
        tool_name=tool_name, result=result, session_id=session_id,
    )
    roots = _configured_roots(); state_dir = _configured_state_dir()
    if not roots or state_dir is None:
        return
    try:
        collect_tool_result(tool_name=tool_name, args=args, result=result,
                            session_id=session_id, task_id=task_id,
                            spool_dir=state_dir / "collector", allowed_roots=roots)
    except Exception:
        return


def _final_message_actions(response_text: str = "", session_id: str = "",
                           platform: str = "", user_id: str = "", chat_type: str = "",
                           thread_id: str = "", **_: Any) -> dict[str, str] | None:
    if platform != "telegram" or not response_text or not session_id or not user_id:
        return None
    state_dir = _configured_state_dir()
    if state_dir is None:
        return None
    try:
        from .handler import publish_action
        if chat_type == "forum" and bool(thread_id):
            return publish_action(state_dir, session_id, user_id, topic=True)
        return publish_action(state_dir, session_id, user_id)
    except Exception:
        return None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", _reset_preview_delivery_state)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("transform_llm_output", _suppress_confirmation_after_preview)
    ctx.register_hook("final_message_actions", _final_message_actions)
    from .preview_tool import runtime_dependencies_available, send_preview
    runtime_dependencies_available()
    ctx.register_tool(
        name="hermes_peek_send_preview",
        toolset="hermes-peek",
        description="Publish files and send one Preview to the current Telegram conversation. On success, the Preview is the complete user-visible response; do not add confirmation text.",
        emoji="🔎",
        schema={
            "name": "hermes_peek_send_preview",
            "description": "Publish files and send one Preview to the current Telegram conversation. A successful send is the complete response and requires NO_REPLY, with no confirmation text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "entry": {"type": "string"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 120},
                },
                "required": ["files", "entry", "title"],
                "additionalProperties": False,
            },
        },
        handler=lambda args, **_: send_preview(**args),
    )
