"""Recognize the supported Markdown YAML envelope without interpreting its fields."""

from __future__ import annotations

import re

_OPENING = re.compile(r"\A\ufeff?---[ \t]*(?:\r?\n|\Z)")
_ENVELOPE = re.compile(
    r"\A(?P<opening>\ufeff?---[ \t]*\r?\n)(?P<yaml>.*?)"
    r"(?P<closing>^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z))",
    flags=re.MULTILINE | re.DOTALL,
)


def frontmatter_envelope(content: str) -> re.Match[str] | None:
    """Return envelope offsets, None for ordinary body, or reject an unclosed header."""
    envelope = _ENVELOPE.match(content)
    if envelope is None and _OPENING.match(content):
        raise ValueError("frontmatter missing closing --- delimiter")
    return envelope
