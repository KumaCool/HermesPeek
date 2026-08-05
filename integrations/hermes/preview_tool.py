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


def telegram_transport():
    return None


def _failure(code: str, message: str) -> dict:
    return {"success": False, "sent": False, "error_code": code, "error": message}


def send_preview(*, files, entry, title) -> dict:
    """Publish and send one request-scoped Preview without leaking inputs."""
    from datetime import timedelta

    from hermes_peek.paths import PathPolicy
    from hermes_peek.registry import LaunchRegistry, PreviewRegistry
    from hermes_peek.service import PreviewService
    from hermes_peek.telegram import TelegramClient, build_mini_app_direct_link

    try:
        if (
            not isinstance(files, list)
            or not files
            or any(not isinstance(item, str) or not Path(item).is_absolute() for item in files)
            or not isinstance(entry, str)
            or entry not in files
            or not isinstance(title, str)
            or not title.strip()
            or len(title) > 120
        ):
            raise PreviewToolError("invalid_input", "preview files, entry, and title are invalid")
        route = resolve_route(get_session_env)
        installed = load_install_config(POINTER_FILE)
        config = installed.config
        roots = config.get("allowed_roots")
        state_name = config.get("state_dir")
        external_url = config.get("external_base_url")
        if not isinstance(roots, list) or not roots or not isinstance(state_name, str) or not isinstance(external_url, str):
            raise PreviewToolError("configuration_unavailable", "HermesPeek installation configuration is unavailable")
        state_dir = Path(state_name)
        service = PreviewService(
            registry=PreviewRegistry(state_dir),
            path_policy=PathPolicy(
                tuple(Path(item) for item in roots),
                max_file_bytes=int(config.get("max_file_bytes", 10 * 1024 * 1024)),
            ),
            default_ttl_seconds=int(config.get("default_ttl_seconds", 3600)),
            external_base_url=external_url,
        )
        published = service.publish(
            tuple(Path(item) for item in files), entry=Path(entry), title=title.strip(),
            owner_telegram_user_id=route.user_id,
        )
        if published.url is None:
            raise PreviewToolError("publication_failed", "preview publication is unavailable")
        mini_app_url = None
        if route.chat_type != "private":
            username = config.get("telegram_bot_username")
            if not isinstance(username, str) or not username:
                raise PreviewToolError("configuration_unavailable", "HermesPeek Telegram Mini App is unavailable")
            expiry = published.record.expires_at or (
                published.record.created_at + timedelta(seconds=int(config.get("launch_ref_ttl_seconds", 300)))
            )
            launch_ref = LaunchRegistry(state_dir).create(
                preview_id=published.record.preview_id,
                owner_telegram_user_id=route.user_id,
                expires_at=expiry,
            )
            mini_app_url = build_mini_app_direct_link(
                username, launch_ref,
                short_name=config.get("telegram_mini_app_short_name"),
                mode=str(config.get("telegram_mini_app_mode", "compact")),
            )
        result = TelegramClient(installed.token, transport=telegram_transport()).send_preview(
            chat_id=route.chat_id,
            chat_type=route.chat_type,
            preview_url=published.url,
            mini_app_url=mini_app_url,
            title=title.strip(),
            thread_id=int(route.thread_id) if route.thread_id is not None else None,
        )
        message_id = result.get("message_id")
        return {"success": True, "sent": True, "message_id": message_id,
                "button_type": "mini_app" if route.chat_type == "private" else "direct_link"}
    except PreviewToolError as exc:
        return _failure(exc.code, str(exc))
    except Exception:
        return _failure("delivery_failed", "preview could not be delivered")
