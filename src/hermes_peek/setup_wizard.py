from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

from .lifecycle import InstallPaths, LifecycleError

_SECRET_DIRECTORY_NAMES = {".ssh", ".gnupg", ".aws", ".config"}


def validate_allowed_roots(roots: Sequence[Path], *, home: Path | None = None) -> tuple[Path, ...]:
    home = (home or Path.home()).expanduser().resolve()
    validated: list[Path] = []
    for root in roots:
        expanded = root.expanduser()
        if expanded.is_symlink():
            raise LifecycleError("allowed root must not be a symlink")
        try:
            resolved = expanded.resolve(strict=True)
        except OSError as exc:
            raise LifecycleError("allowed root must be an existing directory") from exc
        if (
            not resolved.is_dir()
            or resolved == Path(resolved.anchor)
            or resolved == home
            or any(part in _SECRET_DIRECTORY_NAMES for part in resolved.parts)
        ):
            raise LifecycleError("allowed root is too broad or contains secrets")
        validated.append(resolved)
    if not validated:
        raise LifecycleError("at least one allowed root is required")
    return tuple(validated)


def validate_https_origin(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise LifecycleError("external URL must be an HTTPS origin without credentials, path, query, or fragment")
    return value.rstrip("/")


def validate_secret_file(path: Path) -> Path:
    path = path.expanduser()
    try:
        if path.is_symlink():
            raise LifecycleError("Telegram credential path must be a regular, non-symlink file")
        if not path.exists():
            raise LifecycleError("Telegram credential file was not found for the selected Hermes profile")
        if not path.is_file():
            raise LifecycleError("Telegram credential path must be a regular, non-symlink file")
    except OSError as exc:
        raise LifecycleError("cannot inspect Telegram credential file") from exc
    return path


def discover_hermes_profiles(default_home: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    profile_markers = ("config.yaml", "config.json", ".env", "plugins", "skills")
    if default_home.is_dir() and any((default_home / marker).exists() for marker in profile_markers):
        candidates.append(default_home.resolve())
    profiles_dir = default_home / "profiles"
    if profiles_dir.is_dir():
        candidates.extend(
            path.resolve()
            for path in profiles_dir.iterdir()
            if path.name != "default"
            and path.is_dir()
            and not path.is_symlink()
            and any((path / marker).exists() for marker in profile_markers)
        )
    return tuple(sorted(set(candidates), key=str))


def select_hermes_profile(
    profiles: Sequence[Path], *, input_fn: Callable[[str], str] = input
) -> Path:
    if not profiles:
        raise LifecycleError("no Hermes profiles were found")
    if len(profiles) == 1:
        return profiles[0].resolve()
    choices = "\n".join(
        f"  {index}. {'default' if path.name == '.hermes' else path.name}"
        for index, path in enumerate(profiles, 1)
    )
    answer = input_fn(f"Select Hermes profile:\n{choices}\nProfile number: ").strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(profiles):
        raise LifecycleError("multiple Hermes profiles require explicit profile selection")
    return profiles[int(answer) - 1].resolve()


def read_existing_setup(paths: InstallPaths) -> dict[str, Any]:
    """Read non-secret committed setup values for patch-style reconfiguration."""
    if not paths.config_file.is_file():
        return {}
    try:
        value = json.loads(paths.config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleError("existing HermesPeek configuration is unreadable") from exc
    if not isinstance(value, dict):
        raise LifecycleError("existing HermesPeek configuration is invalid")
    roots = value.get("allowed_roots")
    origin = value.get("external_base_url")
    if roots is not None and (
        not isinstance(roots, list)
        or not roots
        or any(not isinstance(item, str) or not item for item in roots)
    ):
        raise LifecycleError("existing HermesPeek configuration is invalid")
    return {
        "allowed_roots": tuple(Path(item) for item in roots) if isinstance(roots, list) else (),
        "external_url": origin.rstrip("/") if isinstance(origin, str) else None,
        "telegram_bot_username": value.get("telegram_bot_username"),
        "telegram_mini_app_short_name": value.get("telegram_mini_app_short_name"),
        "telegram_mini_app_mode": value.get("telegram_mini_app_mode", "compact"),
    }


def discover_installed_hermes_home(*, config_home: Path | None = None) -> Path | None:
    """Prefer the committed manifest/config target over profile guessing."""
    base = (config_home or Path.home() / ".config").expanduser().resolve() / "hermes-peek"
    for filename in ("install.json", "config.json"):
        path = base / filename
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            target = value.get("target", {})
            home = target.get("hermes_home") if isinstance(target, dict) else None
            if isinstance(home, str) and home:
                return Path(home).expanduser().resolve()
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return None


def run_setup_wizard(
    paths: InstallPaths,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    https_probe: Callable[[str], dict[str, Any]],
    activate: bool = True,
    existing: dict[str, Any] | None = None,
    prompt_allowed_roots: bool = True,
    prompt_external_url: bool = True,
) -> dict[str, Any]:
    current = existing or read_existing_setup(paths)
    current_roots = tuple(current.get("allowed_roots") or ())
    if prompt_allowed_roots:
        root_default = ", ".join(str(path) for path in current_roots)
        root_answer = input_fn(f"Allowed preview directories (comma-separated) [{root_default}]: ").strip()
        roots = (validate_allowed_roots(tuple(Path(value.strip()) for value in root_answer.split(",") if value.strip()))
                 if root_answer else validate_allowed_roots(current_roots))
    else:
        roots = validate_allowed_roots(current_roots)
    origin_default = current.get("external_url") or ""
    if prompt_external_url:
        origin_answer = input_fn(f"External HTTPS origin [{origin_default}]: ").strip()
        origin = validate_https_origin(origin_answer or origin_default)
    else:
        origin = validate_https_origin(origin_default)
    health = https_probe(f"{origin}/healthz")
    if not health.get("reachable"):
        output_fn(
            "Preflight note: external /healthz is not reachable yet; "
            "setup will verify it after the local service starts."
        )
    return {"paths": paths, "allowed_roots": roots, "external_url": origin}
