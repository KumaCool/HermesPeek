from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

import uvicorn
from pydantic import ValidationError

from hermes_peek import __version__
from hermes_peek.app import create_app

from hermes_peek.config import Settings
from hermes_peek.lifecycle import (
    InstallPaths,
    LifecycleError,
    install as install_application,
    plan_purge,
    purge as purge_application,
    read_bot_token,
    rollback_transaction,
    uninstall as uninstall_application,
)
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import (
    CorruptPreviewError,
    PreviewNotFoundError,
    PreviewRegistry,
)
from hermes_peek.service import PreviewService, PublishError
from hermes_peek.lifecycle_ux import (
    doctor as lifecycle_doctor,
    setup_plan as lifecycle_setup_plan,
    status as lifecycle_status,
)
from hermes_peek.service_backend import SystemdUserBackend
from hermes_peek.setup_wizard import (
    discover_hermes_profiles,
    run_setup_wizard,
    select_hermes_profile,
    validate_allowed_roots,
    validate_https_origin,
    validate_secret_file,
)
from hermes_peek.telegram import TelegramClient, TelegramNotificationError
from hermes_peek.telegram_lifecycle import TelegramLifecycle


def telegram_transport():
    """Production uses httpx's default transport; tests inject MockTransport here."""
    return None


def telegram_lifecycle_transport():
    from hermes_peek.telegram_lifecycle import UrllibTelegramTransport
    return UrllibTelegramTransport()


def lifecycle_runner(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _remove_uv_tool() -> tuple[bool, str]:
    """Remove this CLI when it is installed as the uv tool named hermes-peek."""
    uv = shutil.which("uv")
    if uv is None:
        return False, "uv 未找到，CLI 未删除"
    listed = subprocess.run([uv, "tool", "list"], text=True, capture_output=True, check=False)
    if listed.returncode != 0 or not any(line.startswith("hermes-peek ") for line in listed.stdout.splitlines()):
        return False, "当前 CLI 不是由 uv tool 管理，CLI 未删除"
    removed = subprocess.run([uv, "tool", "uninstall", "hermes-peek"], text=True, capture_output=True, check=False)
    if removed.returncode != 0:
        detail = (removed.stderr or removed.stdout).strip()
        return False, f"uv tool 卸载失败{': ' + detail if detail else ''}"
    return True, "已通过 uv tool 删除"


def _uninstall_message(result: dict[str, object], cli_status: str | None = None) -> str:
    lines = ["HermesPeek 卸载成功。", "- Hermes 集成：已删除"]
    lines.append("- HermesPeek 数据：已永久删除" if result.get("data_purged") or result.get("purged") else "- Preview 数据：已保留（使用 --purge 才会删除）")
    if cli_status:
        lines.append(f"- CLI：{cli_status}")
    if result.get("original_files_preserved") or result.get("state_preserved"):
        lines.append("- 原始项目文件：按安全策略保留")
    return "\n".join(lines)


def setup_https_probe(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return {"reachable": 200 <= response.status < 500, "status": response.status}
    except (OSError, urllib.error.URLError):
        return {"reachable": False, "status": None}


def _running_inside_gateway_session() -> bool:
    """Avoid restarting the Gateway from a turn currently served by it."""
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        if "hermes-gateway.service" in cgroup:
            return True
    except OSError:
        pass
    try:
        import importlib
        get_session_env = importlib.import_module("gateway.session_context").get_session_env
        return bool(get_session_env("HERMES_SESSION_PLATFORM", "")) or bool(os.environ.get("HERMES_SESSION_PLATFORM"))
    except (ImportError, AttributeError, RuntimeError):
        return bool(os.environ.get("HERMES_SESSION_PLATFORM"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-peek")
    parser.add_argument("--version", action="version", version=f"hermes-peek {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish", help="Publish files as a preview")
    publish.add_argument("files", nargs="+", type=Path)
    publish.add_argument("--entry", required=True, type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--owner", required=True)
    publish.add_argument("--notify", action="store_true")
    publish.add_argument("--chat-id")
    publish.add_argument("--thread-id", type=int)
    publish.add_argument("--chat-type", choices=("private", "group", "supergroup"))

    inspect = subparsers.add_parser("inspect", help="Inspect public preview metadata")
    inspect.add_argument("preview_id")

    revoke = subparsers.add_parser("revoke", help="Revoke a preview")
    revoke.add_argument("preview_id")

    serve = subparsers.add_parser("serve", help="Run the local preview service")
    serve.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    serve.add_argument("--port", default=8765, type=_port)

    setup = subparsers.add_parser("setup", help="Install and integrate HermesPeek")
    setup.add_argument("--allowed-root", action="append", type=Path)
    setup.add_argument("--external-url")
    setup.add_argument("--telegram-bot-username")
    setup.add_argument("--telegram-mini-app-short-name")
    setup.add_argument("--telegram-mini-app-mode", choices=("compact",), default="compact")
    setup.add_argument(
        "--telegram-env",
        type=Path,
        help="Credential file containing TELEGRAM_BOT_TOKEN (defaults to the active Hermes .env)",
    )
    setup.add_argument("--configure-telegram-menu", action="store_true")
    setup.add_argument("--hermes-home", type=Path)
    setup.add_argument("--no-activate", action="store_true")
    setup.add_argument("--plan", action="store_true", help="Print a read-only, redacted setup plan")

    uninstall = subparsers.add_parser("uninstall", help="Safely remove HermesPeek integration")
    uninstall.add_argument("--hermes-home", type=Path)
    uninstall.add_argument("--purge", "--purge-data", dest="purge", action="store_true")
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--yes", action="store_true")
    uninstall.add_argument("--no-deactivate", action="store_true")
    rollback = subparsers.add_parser("rollback", help="Rollback a committed setup transaction")
    rollback.add_argument("transaction_id")
    rollback.add_argument("--hermes-home", type=Path)
    status = subparsers.add_parser("status", help="Show lifecycle status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--hermes-home", type=Path)
    doctor = subparsers.add_parser("doctor", help="Run read-only lifecycle diagnostics")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--hermes-home", type=Path)
    service = subparsers.add_parser("service", help="Manage the local service")
    service.add_argument("action", choices=("start", "stop", "restart", "logs"))
    return parser


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _telegram_onboarding_checklist() -> list[dict[str, object]]:
    return [
        {
            "scope": "botfather",
            "status": "pending_owner_action",
            "action": "Configure and open the Main Mini App for this bot in BotFather.",
            "menu_button_is_not_main_mini_app_registration": True,
        },
        {"scope": "private_chat", "status": "pending_client_acceptance",
         "action": "Start a new private session, request one preview, and open it."},
        {"scope": "group", "status": "pending_client_acceptance",
         "action": "Mention the bot (or choose owner-approved Privacy Mode/admin settings) and verify the preview stays in the group."},
        {"scope": "forum_topic", "status": "pending_client_acceptance",
         "action": "Request and open one preview in the original chat and topic thread."},
    ]


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        if args.command in {"status", "doctor", "service"}:
            paths = InstallPaths.for_user(hermes_home=getattr(args, "hermes_home", None))
            if args.command == "status":
                output = lifecycle_status(paths, lifecycle_runner)
            elif args.command == "doctor":
                output = lifecycle_doctor(paths, lifecycle_runner)
            else:
                backend = SystemdUserBackend(lifecycle_runner)
                operation = getattr(backend, args.action)
                value = operation()
                if args.action == "stop":
                    backend.verify_stopped()
                output = {"action": args.action, "ok": True}
                if value is not None:
                    output["output"] = value
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "rollback":
            paths = InstallPaths.for_user(hermes_home=args.hermes_home)
            result = rollback_transaction(paths, args.transaction_id, runner=lifecycle_runner)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command in {"setup", "uninstall"}:
            if args.command == "setup" and (not args.allowed_root or not args.external_url):
                if not sys.stdin.isatty():
                    raise LifecycleError(
                        "non-interactive setup requires --allowed-root and --external-url"
                    )
                default_home = Path.home() / ".hermes"
                selected_home = args.hermes_home or select_hermes_profile(
                    discover_hermes_profiles(default_home)
                )
                paths = InstallPaths.for_user(hermes_home=selected_home)
                validate_secret_file(args.telegram_env or paths.hermes_home / ".env")
                wizard = run_setup_wizard(
                    paths,
                    input_fn=input,
                    https_probe=setup_https_probe,
                    activate=not args.no_activate,
                )
                args.allowed_root = list(wizard["allowed_roots"])
                args.external_url = wizard["external_url"]
            else:
                paths = InstallPaths.for_user(hermes_home=args.hermes_home)
            if args.command == "setup":
                args.allowed_root = list(validate_allowed_roots(args.allowed_root))
                args.external_url = validate_https_origin(args.external_url)
                if args.plan:
                    result = lifecycle_setup_plan(
                        paths,
                        allowed_roots=args.allowed_root,
                        external_url=args.external_url,
                        activate=not args.no_activate,
                    )
                    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                    return 0
                token_file = args.telegram_env or paths.hermes_home / ".env"
                executable_name = shutil.which("hermes-peek")
                if executable_name is None:
                    raise LifecycleError("hermes-peek executable was not found on PATH")
                result = install_application(
                    paths=paths,
                    integration_dir=Path(__file__).with_name("hermes_plugin"),
                    executable=Path(executable_name),
                    allowed_roots=tuple(args.allowed_root),
                    external_url=args.external_url,
                    bot_token=read_bot_token(token_file),
                    telegram_bot_username=args.telegram_bot_username,
                    telegram_mini_app_short_name=args.telegram_mini_app_short_name,
                    telegram_mini_app_mode=args.telegram_mini_app_mode,
                    activate=not args.no_activate,
                    telegram=TelegramLifecycle(telegram_lifecycle_transport()),
                    configure_telegram_menu=args.configure_telegram_menu,
                    defer_gateway_restart=_running_inside_gateway_session(),
                    runner=lifecycle_runner,
                )
                result["telegram_onboarding_checklist"] = _telegram_onboarding_checklist()
            else:
                if args.dry_run and not args.purge:
                    raise LifecycleError("--dry-run requires --purge")
                if args.purge and args.dry_run:
                    result = plan_purge(paths)
                elif args.purge:
                    if not args.yes:
                        if not sys.stdin.isatty():
                            raise LifecycleError("non-interactive purge requires --yes")
                        expected = json.loads(paths.manifest_file.read_text()).get("transaction_id") if paths.manifest_file.is_file() else "PURGE"
                        if input(f"Type {expected} to permanently purge HermesPeek data: ") != expected:
                            raise LifecycleError("purge confirmation did not match")
                    uninstall_application(paths=paths, purge_data=False,
                                          deactivate=not args.no_deactivate)
                    result = purge_application(paths, confirmed=True)
                    _, cli_status = _remove_uv_tool()
                    result["original_files_preserved"] = True
                    print(_uninstall_message(result, cli_status=cli_status))
                    return 0
                else:
                    result = uninstall_application(paths=paths, purge_data=False,
                                                   deactivate=not args.no_deactivate)
            if args.command == "uninstall" and not args.dry_run:
                print(_uninstall_message(result))
            else:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        settings = Settings.from_env()
        if args.command == "serve":
            token = os.environ.get("HERMES_PEEK_TELEGRAM_BOT_TOKEN")
            if not settings.development and not token:
                raise ValueError(
                    "serve requires HERMES_PEEK_TELEGRAM_BOT_TOKEN outside development"
                )
            uvicorn.run(
                create_app(settings, bot_token=token),
                host=args.host,
                port=args.port,
                log_level="info",
                access_log=False,
            )
            return 0
        service = PreviewService(
            registry=PreviewRegistry(settings.state_dir),
            path_policy=PathPolicy(
                settings.allowed_roots,
                max_file_bytes=settings.max_file_bytes,
            ),
            default_ttl_seconds=settings.default_ttl_seconds,
            external_base_url=(
                str(settings.external_base_url)
                if settings.external_base_url is not None
                else None
            ),
        )
        if args.command == "publish":
            result = service.publish(
                tuple(args.files),
                entry=args.entry,
                title=args.title,
                owner_telegram_user_id=args.owner,
            )
            output = {"preview_id": result.record.preview_id, "url": result.url}
            if args.notify:
                if not args.chat_id or not args.chat_type:
                    raise ValueError("--notify requires --chat-id and --chat-type")
                if result.url is None:
                    raise ValueError("--notify requires HERMES_PEEK_EXTERNAL_BASE_URL")
                token = os.environ.get("HERMES_PEEK_TELEGRAM_BOT_TOKEN")
                if not token:
                    raise ValueError(
                        "--notify requires HERMES_PEEK_TELEGRAM_BOT_TOKEN"
                    )
                try:
                    message = TelegramClient(
                        token, transport=telegram_transport()
                    ).send_preview(
                        chat_id=args.chat_id,
                        chat_type=args.chat_type,
                        preview_url=result.url,
                        title=args.title,
                        thread_id=args.thread_id,
                    )
                except TelegramNotificationError as exc:
                    print(
                        "error: Preview was published, but Telegram notification "
                        f"failed: {exc}",
                        file=sys.stderr,
                    )
                    return 3
                output.update(notified=True, message_id=message.get("message_id"))
        elif args.command == "inspect":
            output = service.inspect(args.preview_id).model_dump(mode="json")
        else:
            output = service.revoke(args.preview_id).model_dump(mode="json")
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        ValueError,
        ValidationError,
        PathPolicyError,
        PreviewNotFoundError,
        CorruptPreviewError,
        PublishError,
        LifecycleError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
