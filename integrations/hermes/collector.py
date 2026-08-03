from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

_PATCH_PATH = re.compile(r"^\*\*\* (?:Update|Add) File: (.+)$", re.MULTILINE)
_SENSITIVE_NAMES = {
    ".env", ".netrc", "auth.json", "credentials", "credentials.json",
    "id_rsa", "id_ed25519", "config.yaml",
}


def _successful(result: Any) -> bool:
    if isinstance(result, dict):
        return result.get("success") is not False and result.get("error") in (None, "")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            return False
        return isinstance(parsed, dict) and _successful(parsed)
    return False


def _candidate_paths(tool_name: str, args: dict[str, Any]) -> Iterable[str]:
    if tool_name == "write_file":
        path = args.get("path")
        if isinstance(path, str):
            yield path
    elif tool_name == "patch":
        path = args.get("path")
        if isinstance(path, str):
            yield path
        patch_text = args.get("patch")
        if isinstance(patch_text, str):
            yield from _PATCH_PATH.findall(patch_text)


def _safe_path(raw: str, roots: tuple[Path, ...]) -> Path | None:
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_file() or path.name.lower() in _SENSITIVE_NAMES:
        return None
    if any(part.lower() in {".git", ".ssh", ".gnupg"} for part in path.parts):
        return None
    if not any(path.is_relative_to(root) for root in roots):
        return None
    return path


def _key(session_id: str, task_id: str) -> str:
    raw = f"{session_id}\0{task_id}".encode()
    import hashlib
    return hashlib.sha256(raw).hexdigest()[:32]


def collect_tool_result(
    *,
    tool_name: str,
    args: Any,
    result: Any,
    session_id: str,
    task_id: str,
    spool_dir: Path,
    allowed_roots: tuple[Path, ...],
) -> None:
    if tool_name not in {"write_file", "patch"} or not isinstance(args, dict):
        return
    if not session_id or not _successful(result):
        return
    roots = tuple(root.expanduser().resolve() for root in allowed_roots)
    paths = {path for raw in _candidate_paths(tool_name, args) if (path := _safe_path(raw, roots))}
    if not paths:
        return

    spool_dir.mkdir(parents=True, exist_ok=True)
    target = spool_dir / f"{_key(session_id, task_id)}.json"
    existing: dict[str, Any] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    merged = sorted(set(existing.get("paths", [])) | {str(path) for path in paths})
    record = {"session_id": session_id, "task_id": task_id, "paths": merged}
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=spool_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
