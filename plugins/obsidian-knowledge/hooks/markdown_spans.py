"""Mask Markdown code and escaped brackets without changing source offsets."""

from __future__ import annotations

import re

FENCE_RE = re.compile(r"^(?: {0,3}> ?)* {0,3}(`{3,}|~{3,})(.*?)(?:\r?\n)?$")
BACKTICKS_RE = re.compile(r"`+")


def markdown_text(content: str) -> str:
    """Return text with fenced/inline code replaced by spaces, retaining newlines.

    Recognizes variable-length fences, indented examples, and backtick delimiters,
    including multiline inline spans. Unmatched inline delimiters remain text.
    Odd-backslash escaped opening brackets cannot start semantic links.
    This is a small lexical boundary, not a complete Markdown renderer.
    """
    masked = list(content)

    def hide(start: int, end: int) -> None:
        for offset in range(start, end):
            if content[offset] not in "\r\n":
                masked[offset] = " "

    fence: str | None = None
    offset = 0
    for line in content.splitlines(keepends=True):
        marker = FENCE_RE.match(line)
        if fence is not None:
            hide(offset, offset + len(line))
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence = marker[1]
            hide(offset, offset + len(line))
        elif line.startswith(("    ", "\t")):
            # Conservatively preserve indented examples, including ambiguous list indentation.
            hide(offset, offset + len(line))
        offset += len(line)

    visible = "".join(masked)
    runs = list(BACKTICKS_RE.finditer(visible))
    i = 0
    while i < len(runs):
        opening = runs[i]
        # An escaped backtick is ordinary text, not a code delimiter.
        start = opening.start()
        while start > 0 and visible[start - 1] == "\\":
            start -= 1
        if (opening.start() - start) % 2:
            i += 1
            continue
        closing = next((j for j in range(i + 1, len(runs)) if runs[j][0] == opening[0]), None)
        if closing is None:
            i += 1
        else:
            hide(opening.start(), runs[closing].end())
            i = closing + 1
    for match in re.finditer(r"(\\+)\[", "".join(masked)):
        if len(match[1]) % 2:
            masked[match.end() - 1] = " "
    return "".join(masked)
