from __future__ import annotations

import html
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml
import bleach
from markdown_it import MarkdownIt


class RenderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RenderedText:
    html: str
    text: str


def render_text_preview(
    *,
    kind: str,
    mime_type: str,
    display_path: str,
    content: str,
) -> RenderedText:
    suffix = Path(display_path).suffix.lower()
    if kind == "html":
        cleaned = bleach.clean(
            content,
            tags={
                "a", "article", "aside", "b", "blockquote", "br", "code", "div",
                "em", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4",
                "header", "hr", "i", "li", "main", "nav", "ol", "p", "pre",
                "section", "span", "strong", "table", "tbody", "td", "th", "thead",
                "tr", "ul",
            },
            attributes={"a": ["href", "title"], "*": ["class"]},
            protocols={"http", "https", "mailto"},
            strip=True,
        )
        return RenderedText(cleaned, content)

    if kind == "markdown":
        safe_content = re.sub(
            r"\]\(\s*(?:javascript|data|vbscript):[^)]*\)",
            "](#)",
            content,
            flags=re.IGNORECASE,
        )
        markdown = MarkdownIt("commonmark", {"html": False, "linkify": False})
        rendered = markdown.render(safe_content)
        rendered = re.sub(
            r'(<a\s+[^>]*href=")[^"]*(")',
            lambda match: match.group(1) + "#" + match.group(2)
            if _unsafe_href(match.group(0))
            else match.group(0),
            rendered,
            flags=re.IGNORECASE,
        )
        return RenderedText(rendered, content)

    if kind == "structured":
        normalized = _structured_text(suffix, content)
        return RenderedText(f'<pre class="structured">{html.escape(normalized)}</pre>', normalized)

    language = _language_class(suffix, mime_type)
    css_class = f' class="language-{language}"' if language else ""
    return RenderedText(f"<pre><code{css_class}>{html.escape(content)}</code></pre>", content)


def _structured_text(suffix: str, content: str) -> str:
    try:
        if suffix == ".json":
            parsed = json.loads(content)
            return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)
        if suffix in {".yaml", ".yml"}:
            yaml.safe_load(content)
            return content
        if suffix == ".toml":
            tomllib.loads(content)
            return content
    except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        raise RenderError("Invalid structured document") from exc
    raise RenderError("Unsupported structured document")


def _language_class(suffix: str, mime_type: str) -> str | None:
    known = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".css": "css",
        ".sh": "shell",
        ".sql": "sql",
        ".xml": "xml",
        ".csv": "csv",
    }
    return known.get(suffix) or ("text" if mime_type.startswith("text/") else None)


def _unsafe_href(anchor: str) -> bool:
    match = re.search(r'href="\s*([^"\s:]+):', anchor, re.IGNORECASE)
    return match is not None and match.group(1).lower() not in {"http", "https", "mailto"}
