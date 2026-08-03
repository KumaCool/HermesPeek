from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from hermes_peek.config import Settings
from hermes_peek.paths import PathPolicy, PathPolicyError
from hermes_peek.registry import (
    CorruptPreviewError,
    PreviewNotFoundError,
    PreviewRegistry,
)
from hermes_peek.service import PreviewService, PublishError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-peek")
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish", help="Publish files as a preview")
    publish.add_argument("files", nargs="+", type=Path)
    publish.add_argument("--entry", required=True, type=Path)
    publish.add_argument("--title", required=True)
    publish.add_argument("--owner", required=True)

    inspect = subparsers.add_parser("inspect", help="Inspect public preview metadata")
    inspect.add_argument("preview_id")

    revoke = subparsers.add_parser("revoke", help="Revoke a preview")
    revoke.add_argument("preview_id")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        settings = Settings.from_env()
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
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
