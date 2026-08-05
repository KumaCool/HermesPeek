from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from gateway.session_context import get_session_env
except ImportError:  # pragma: no cover - only outside Hermes runtime
    def get_session_env(name: str, default: str = "") -> str:
        return default


POINTER_FILE = Path(__file__).parent / ".hermes-peek-config.json"


class PreviewToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SessionRoute:
    chat_id: str
    user_id: str
    chat_type: str
    thread_id: str | None


@dataclass(frozen=True, slots=True)
class InstallConfig:
    config: dict
    token: str


SessionGetter = Callable[[str, str], str]


def resolve_route(getter: SessionGetter = get_session_env) -> SessionRoute:
    platform = getter("HERMES_SESSION_PLATFORM", "")
    chat_id = getter("HERMES_SESSION_CHAT_ID", "")
    user_id = getter("HERMES_SESSION_USER_ID", "")
    chat_type = getter("HERMES_SESSION_CHAT_TYPE", "")
    thread_id = getter("HERMES_SESSION_THREAD_ID", "")
    if platform != "telegram" or not chat_id or not user_id:
        raise PreviewToolError("route_unavailable", "current Telegram route is unavailable")
    if chat_type == "forum":
        if not thread_id:
            raise PreviewToolError("route_unavailable", "current Telegram topic route is unavailable")
        return SessionRoute(chat_id, user_id, "supergroup", thread_id)
    if chat_type in {"dm", "private"}:
        return SessionRoute(chat_id, user_id, "private", None)
    if chat_type in {"group", "supergroup"}:
        return SessionRoute(chat_id, user_id, "group", None)
    raise PreviewToolError("route_unavailable", "current Telegram route is unavailable")


def _load_json_file(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise PreviewToolError("configuration_unavailable", "HermesPeek installation configuration is unavailable") from exc
    if not isinstance(value, dict):
        raise PreviewToolError("configuration_unavailable", "HermesPeek installation configuration is unavailable")
    return value


def load_install_config(pointer_file: Path = POINTER_FILE) -> InstallConfig:
    pointer = _load_json_file(pointer_file)
    config_name = pointer.get("config_file")
    secret_name = pointer.get("env_file")
    if not isinstance(config_name, str) or not isinstance(secret_name, str):
        raise PreviewToolError("configuration_unavailable", "HermesPeek installation configuration is unavailable")
    config = _load_json_file(Path(config_name))
    secret = Path(secret_name)
    try:
        info = secret.lstat()
        if secret.is_symlink() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise OSError
        lines = secret.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PreviewToolError("secret_unavailable", "HermesPeek Telegram credential is unavailable") from exc
    token = ""
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key.strip() == "HERMES_PEEK_TELEGRAM_BOT_TOKEN":
            token = value.strip().strip('"').strip("'")
            break
    if not token:
        raise PreviewToolError("secret_unavailable", "HermesPeek Telegram credential is unavailable")
    return InstallConfig(config, token)
