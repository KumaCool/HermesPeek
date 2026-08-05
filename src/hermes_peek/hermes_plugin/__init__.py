from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .collector import collect_tool_result


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
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("final_message_actions", _final_message_actions)
    from .preview_tool import send_preview
    ctx.register_tool(
        name="hermes_peek_send_preview",
        toolset="hermes-peek",
        description="Publish files and send one Preview to the current Telegram conversation.",
        emoji="🔎",
        schema={
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "entry": {"type": "string"},
                "title": {"type": "string", "minLength": 1, "maxLength": 120},
            },
            "required": ["files", "entry", "title"],
            "additionalProperties": False,
        },
        handler=lambda args, **_: send_preview(**args),
    )
