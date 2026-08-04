from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from .collector import collect_tool_result


def _configured_roots() -> tuple[Path, ...]:
    value = os.environ.get("HERMES_PEEK_ALLOWED_ROOTS", "")
    if not value and os.environ.get("HERMES_PEEK_CONFIG_FILE"):
        try:
            data = json.loads(Path(os.environ["HERMES_PEEK_CONFIG_FILE"]).read_text(encoding="utf-8"))
            return tuple(Path(item) for item in data.get("allowed_roots", ()))
        except (OSError, ValueError, TypeError):
            return ()
    return tuple(Path(item) for item in value.split(os.pathsep) if item)


def _post_tool_call(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    session_id: str = "",
    task_id: str = "",
    **_: Any,
) -> None:
    roots = _configured_roots()
    state_dir = os.environ.get("HERMES_PEEK_STATE_DIR")
    if not roots or not state_dir:
        return
    try:
        collect_tool_result(
            tool_name=tool_name,
            args=args,
            result=result,
            session_id=session_id,
            task_id=task_id,
            spool_dir=Path(state_dir) / "collector",
            allowed_roots=roots,
        )
    except Exception:
        # Plugin hooks must never disrupt normal Hermes tool execution.
        return


def _final_message_actions(
    response_text: str = "",
    session_id: str = "",
    platform: str = "",
    user_id: str = "",
    **_: Any,
) -> dict[str, str] | None:
    """Publish collected files and return an action for Hermes' final reply."""
    if platform != "telegram" or not response_text or not session_id or not user_id:
        return None
    state_dir = os.environ.get("HERMES_PEEK_STATE_DIR")
    if not state_dir:
        return None
    try:
        # Imported lazily so the post_tool_call collector remains lightweight.
        from .handler import publish_action

        return publish_action(Path(state_dir), session_id, user_id)
    except Exception:
        # Final response delivery must never depend on preview publication.
        return None


def register(ctx) -> None:
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("final_message_actions", _final_message_actions)
