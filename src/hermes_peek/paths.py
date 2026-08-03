from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class FileKind(StrEnum):
    MARKDOWN = "markdown"
    TEXT = "text"
    STRUCTURED = "structured"
    HTML = "html"
    IMAGE = "image"
    PDF = "pdf"


@dataclass(frozen=True, slots=True)
class InspectedFile:
    resolved_path: Path
    kind: FileKind
    mime_type: str
    size_bytes: int


class PathPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_TEXT_TYPES = {
    ".txt": (FileKind.TEXT, "text/plain"),
    ".py": (FileKind.TEXT, "text/x-python"),
    ".js": (FileKind.TEXT, "text/javascript"),
    ".ts": (FileKind.TEXT, "text/typescript"),
    ".tsx": (FileKind.TEXT, "text/typescript"),
    ".jsx": (FileKind.TEXT, "text/javascript"),
    ".css": (FileKind.TEXT, "text/css"),
    ".sh": (FileKind.TEXT, "text/x-shellscript"),
    ".sql": (FileKind.TEXT, "text/x-sql"),
    ".xml": (FileKind.TEXT, "application/xml"),
    ".csv": (FileKind.TEXT, "text/csv"),
}
_STRUCTURED_TYPES = {
    ".json": (FileKind.STRUCTURED, "application/json"),
    ".yaml": (FileKind.STRUCTURED, "application/yaml"),
    ".yml": (FileKind.STRUCTURED, "application/yaml"),
    ".toml": (FileKind.STRUCTURED, "application/toml"),
}
_BINARY_TYPES = {
    ".png": (FileKind.IMAGE, "image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": (FileKind.IMAGE, "image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": (FileKind.IMAGE, "image/jpeg", b"\xff\xd8\xff"),
    ".gif": (FileKind.IMAGE, "image/gif", (b"GIF87a", b"GIF89a")),
    ".webp": (FileKind.IMAGE, "image/webp", b"RIFF"),
    ".pdf": (FileKind.PDF, "application/pdf", b"%PDF-"),
}
_SPECIAL_TEXT_TYPES = {
    ".md": (FileKind.MARKDOWN, "text/markdown"),
    ".markdown": (FileKind.MARKDOWN, "text/markdown"),
    ".html": (FileKind.HTML, "text/html"),
    ".htm": (FileKind.HTML, "text/html"),
}
_DENIED_PARTS = {
    ".git",
    ".ssh",
    ".hermes",
    "node_modules",
    "__pycache__",
    ".venv",
}
_DENIED_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
_DENIED_FRAGMENTS = (
    "credential",
    "cookie",
    "private-key",
    "private_key",
    "token",
    "id_rsa",
    "id_ed25519",
)


class PathPolicy:
    def __init__(self, allowed_roots: tuple[Path, ...], *, max_file_bytes: int) -> None:
        if not allowed_roots:
            raise ValueError("allowed_roots must not be empty")
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.allowed_roots = tuple(root.expanduser().resolve() for root in allowed_roots)
        self.max_file_bytes = max_file_bytes

    def inspect(self, raw_path: str | os.PathLike[str]) -> InspectedFile:
        submitted = Path(raw_path).expanduser()
        if self._contains_symlink(submitted):
            raise PathPolicyError("SYMLINK_NOT_ALLOWED", "Symbolic links are not previewable")
        try:
            resolved = submitted.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PathPolicyError("NOT_FOUND", "Preview file does not exist") from exc
        except OSError as exc:
            raise PathPolicyError("NOT_FOUND", "Preview file cannot be resolved") from exc

        if not self._inside_allowed_root(resolved):
            raise PathPolicyError("OUTSIDE_ALLOWED_ROOT", "Preview file is outside allowed roots")
        if not resolved.is_file():
            raise PathPolicyError("NOT_REGULAR_FILE", "Preview target is not a regular file")
        if self._is_sensitive(resolved):
            raise PathPolicyError("SENSITIVE_PATH", "Sensitive paths are not previewable")

        classification = self._classification(resolved.suffix.lower())
        if classification is None:
            raise PathPolicyError("UNSUPPORTED_TYPE", "Preview file type is unsupported")

        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise PathPolicyError("FILE_TOO_LARGE", "Preview file exceeds the configured size limit")

        kind, mime_type = classification
        binary_spec = _BINARY_TYPES.get(resolved.suffix.lower())
        if binary_spec is not None:
            expected = binary_spec[2]
            prefix = resolved.read_bytes()[:16]
            signatures = expected if isinstance(expected, tuple) else (expected,)
            if not any(prefix.startswith(signature) for signature in signatures):
                raise PathPolicyError("MIME_MISMATCH", "Preview file content does not match its type")
            if resolved.suffix.lower() == ".webp" and prefix[8:12] != b"WEBP":
                raise PathPolicyError("MIME_MISMATCH", "Preview file content does not match its type")
        else:
            try:
                resolved.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise PathPolicyError("INVALID_UTF8", "Preview text must be valid UTF-8") from exc

        return InspectedFile(resolved, kind, mime_type, size)

    def _inside_allowed_root(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.allowed_roots)

    def _contains_symlink(self, path: Path) -> bool:
        current = path if path.is_absolute() else Path.cwd() / path
        for candidate in (current, *current.parents):
            if candidate.is_symlink():
                return True
        return False

    @staticmethod
    def _is_sensitive(path: Path) -> bool:
        lowered_parts = tuple(part.lower() for part in path.parts)
        name = path.name.lower()
        return (
            any(part in _DENIED_PARTS for part in lowered_parts)
            or name in _DENIED_NAMES
            or name.startswith(".env.")
            or any(fragment in name for fragment in _DENIED_FRAGMENTS)
        )

    @staticmethod
    def _classification(suffix: str) -> tuple[FileKind, str] | None:
        text_classification = (
            _SPECIAL_TEXT_TYPES.get(suffix)
            or _TEXT_TYPES.get(suffix)
            or _STRUCTURED_TYPES.get(suffix)
        )
        if text_classification is not None:
            return text_classification
        binary = _BINARY_TYPES.get(suffix)
        if binary is not None:
            return binary[0], binary[1]
        return None
