"""One-line search snippets read from matching vault notes."""

from __future__ import annotations

import re
from pathlib import Path

from lib.vault_index.models import Hit

SNIPPET_MAX_CHARS = 240


def crop_snippet(line: str, terms: list[str]) -> str:
    """Crop a single-line snippet around the earliest query-term match."""
    if len(line) <= SNIPPET_MAX_CHARS:
        return line

    lowered = line.lower()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    anchor = min(positions) if positions else 0
    start = max(0, anchor - SNIPPET_MAX_CHARS // 3)
    end = start + SNIPPET_MAX_CHARS
    if end > len(line):
        end = len(line)
        start = max(0, end - SNIPPET_MAX_CHARS)
    snippet = line[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(line):
        snippet += "..."
    return snippet


def snippet_for_path(vault_root: Path, rel_path: str, terms: list[str]) -> str:
    """Read a vault-relative markdown file and return a one-line search snippet."""
    candidate = vault_root / rel_path
    try:
        candidate.resolve().relative_to(vault_root.resolve())
    except (OSError, ValueError):
        return ""

    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    def score(line: str) -> tuple[int, int]:
        lowered = line.lower()
        matched = sum(1 for term in terms if term in lowered)
        return (matched, -len(line))

    if terms:
        best = max(lines, key=score)
        if score(best)[0] > 0:
            return crop_snippet(best, terms)

    return crop_snippet(lines[0], terms)


def with_snippets(vault_root: Path, hits: list[Hit], query: str) -> list[Hit]:
    """Attach a snippet to each hit, preferring lines containing query terms."""
    terms = [term.lower() for term in re.findall(r"[\w-]+", query) if term.strip()]
    return [hit.model_copy(update={"snippet": snippet_for_path(vault_root, hit.path, terms)}) for hit in hits]
