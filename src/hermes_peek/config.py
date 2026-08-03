from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

_DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


class Settings(BaseModel):
    """Validated, non-secret HermesPeek behavior settings."""

    model_config = ConfigDict(frozen=True)

    allowed_roots: tuple[Path, ...]
    state_dir: Path
    max_file_bytes: int = Field(default=_DEFAULT_MAX_FILE_BYTES, gt=0)
    default_ttl_seconds: int = Field(default=_DEFAULT_TTL_SECONDS, gt=0)
    external_base_url: HttpUrl | None = None
    development: bool = False

    @field_validator("allowed_roots")
    @classmethod
    def require_allowed_roots(cls, roots: tuple[Path, ...]) -> tuple[Path, ...]:
        if not roots:
            raise ValueError("HERMES_PEEK_ALLOWED_ROOTS must contain at least one path")
        return roots

    @field_validator("external_base_url")
    @classmethod
    def require_https_base_url(cls, url: HttpUrl | None) -> HttpUrl | None:
        if url is not None and url.scheme != "https":
            raise ValueError("HERMES_PEEK_EXTERNAL_BASE_URL must use HTTPS")
        return url

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        cwd: Path | None = None,
    ) -> Self:
        """Build settings from an explicit environment mapping.

        Passing a mapping isolates tests and callers from the process environment.
        Omitting it intentionally reads ``os.environ``.
        """

        env = os.environ if environment is None else environment
        base = (Path.cwd() if cwd is None else cwd).expanduser().resolve()
        raw_roots = env.get("HERMES_PEEK_ALLOWED_ROOTS", "")
        if not raw_roots.strip():
            raise ValueError("HERMES_PEEK_ALLOWED_ROOTS is required")

        roots = tuple(
            _resolve_path(item, base)
            for item in raw_roots.split(os.pathsep)
            if item.strip()
        )
        state_dir = _state_dir(env, base)
        data: dict[str, Any] = {
            "allowed_roots": roots,
            "state_dir": state_dir,
            "max_file_bytes": env.get(
                "HERMES_PEEK_MAX_FILE_BYTES", str(_DEFAULT_MAX_FILE_BYTES)
            ),
            "default_ttl_seconds": env.get(
                "HERMES_PEEK_DEFAULT_TTL_SECONDS", str(_DEFAULT_TTL_SECONDS)
            ),
            "external_base_url": env.get("HERMES_PEEK_EXTERNAL_BASE_URL") or None,
            "development": _parse_bool(env.get("HERMES_PEEK_DEVELOPMENT", "false")),
        }
        return cls.model_validate(data)


def _resolve_path(raw: str, base: Path) -> Path:
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _state_dir(environment: Mapping[str, str], base: Path) -> Path:
    configured = environment.get("HERMES_PEEK_STATE_DIR")
    if configured:
        return _resolve_path(configured, base)
    xdg = environment.get("XDG_STATE_HOME")
    if xdg:
        return _resolve_path(xdg, base) / "hermes-peek"
    return Path.home().resolve() / ".local" / "state" / "hermes-peek"


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError("HERMES_PEEK_DEVELOPMENT must be a boolean")
