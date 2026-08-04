from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import uvicorn
from pydantic import ValidationError

from hermes_peek.app import create_app

from hermes_peek.config import Settings
from hermes_peek.lifecycle import (
    InstallPaths,
    LifecycleError,
    install as install_application,
    read_bot_token,
    uninstall as uninstall_application,
)
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import (
    CorruptPreviewError,
    PreviewNotFoundError,
    PreviewRegistry,
)
from hermes_peek.service import PreviewService, PublishError
from hermes_peek.lifecycle_ux import status as lifecycle_status, doctor as lifecycle_doctor
from hermes_peek.service_backend import SystemdUserBackend
from hermes_peek.telegram import TelegramClient, TelegramNotificationError


def telegram_transport():
    """Production uses httpx's default transport; tests inject MockTransport here."""
    return None


def lifecycle_runner(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-peek")
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
    setup.add_argument("--allowed-root", action="append", required=True, type=Path)
    setup.add_argument("--external-url", required=True)
    setup.add_argument(
        "--telegram-env",
        type=Path,
        help="Credential file containing TELEGRAM_BOT_TOKEN (defaults to the active Hermes .env)",
    )
    setup.add_argument("--hermes-home", type=Path)
    setup.add_argument("--no-activate", action="store_true")

    uninstall = subparsers.add_parser("uninstall", help="Safely remove HermesPeek integration")
    uninstall.add_argument("--hermes-home", type=Path)
    uninstall.add_argument("--purge-data", action="store_true")
    uninstall.add_argument("--no-deactivate", action="store_true")
    status = subparsers.add_parser("status", help="Show lifecycle status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--hermes-home", type=Path)
    doctor = subparsers.add_parser("doctor", help="Run read-only lifecycle diagnostics")
    doctor.add_argument("--hermes-home", type=Path)
    service = subparsers.add_parser("service", help="Manage the local service")
    service.add_argument("action", choices=("start", "stop", "restart", "logs"))
    return parser


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


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
                output = {"action": args.action, "ok": True}
                if value is not None:
                    output["output"] = value
            print(json.dumps(output, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command in {"setup", "uninstall"}:
            paths = InstallPaths.for_user(hermes_home=args.hermes_home)
            if args.command == "setup":
                token_file = args.telegram_env or paths.hermes_home / ".env"
                executable_name = shutil.which("hermes-peek")
                if executable_name is None:
                    raise LifecycleError("hermes-peek executable was not found on PATH")
                result = install_application(
                    paths=paths,
                    integration_dir=Path(__file__).with_name("hermes_plugin"),
                    executable=Path(executable_name),
                    allowed_roots=args.allowed_root,
                    external_url=args.external_url,
                    bot_token=read_bot_token(token_file),
                    activate=not args.no_activate,
                )
            else:
                result = uninstall_application(
                    paths=paths,
                    purge_data=args.purge_data,
                    deactivate=not args.no_deactivate,
                )
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
