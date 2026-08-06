from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

from .lifecycle import InstallPaths, LifecycleError
from .lifecycle_ux import setup_plan

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


def run_setup_wizard(
    paths: InstallPaths,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    https_probe: Callable[[str], dict[str, Any]],
    activate: bool = True,
) -> dict[str, Any]:
    root = Path(input_fn("Allowed preview directory: ").strip())
    roots = validate_allowed_roots((root,))
    origin = validate_https_origin(input_fn("External HTTPS origin: ").strip())
    health = https_probe(f"{origin}/healthz")
    if not health.get("reachable"):
        raise LifecycleError("external HTTPS origin is not reachable at /healthz")
    plan = setup_plan(paths, allowed_roots=list(roots), external_url=origin, activate=activate)
    output_fn("Setup plan (secrets are never displayed):")
    output_fn(__import__("json").dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    if input_fn("Apply this plan? [yes/no]: ").strip().lower() not in {"y", "yes"}:
        raise LifecycleError("setup cancelled; no changes were made")
    return {"paths": paths, "allowed_roots": roots, "external_url": origin}
