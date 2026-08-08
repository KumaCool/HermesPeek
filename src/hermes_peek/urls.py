from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]+$")


def normalize_external_base_url(value: str) -> str:
    """Validate and canonicalize the configured public HTTPS base URL."""
    if not isinstance(value, str) or not value:
        raise ValueError("external URL must be a non-empty HTTPS base URL")

    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in parsed.path
        or "%" in parsed.path
    ):
        raise ValueError(
            "external URL must be an HTTPS base URL without credentials, query, fragment, or encoded path"
        )

    path = parsed.path or "/"
    segments = path.split("/")[1:]
    if path.endswith("/"):
        segments = segments[:-1]
    if any(not segment or segment in {".", ".."} or not _SAFE_SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("external URL path contains an unsafe or ambiguous segment")

    normalized_path = "/" if not segments else f"/{'/'.join(segments)}/"
    return urlunsplit(("https", parsed.netloc, normalized_path, "", ""))


def external_base_path(value: str) -> str:
    """Return '/' for root deployments or a slash-prefixed path without a trailing slash."""
    path = urlsplit(normalize_external_base_url(value)).path
    return "/" if path == "/" else path.rstrip("/")


def external_url(base: str, relative: str) -> str:
    """Append an application-relative path without discarding the configured base path."""
    normalized = normalize_external_base_url(base)
    suffix = relative.lstrip("/")
    return normalized if not suffix else normalized + suffix
