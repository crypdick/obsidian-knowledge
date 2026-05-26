"""Convention patterns shared between write-time hook, SessionStart doctor, and vault-organizer sweep.

Single source of truth — all three consumers import from this module so
prevention, surfacing, and persistence stay in lockstep.
"""

from __future__ import annotations

import re

try:
    import yaml
except ImportError:  # pragma: no cover - depends on host python
    yaml = None

# Folders where files are expected to have YYYY-MM-DD date prefixes.
# Match as substrings of the path: "Journal/" at the start or "/diary/",
# "/convos/", "/plans/" anywhere.
DATED_FOLDER_MARKERS = [
    "Journal/",
    "/diary/",
    "/convos/",
    "/plans/",
]

# Date prefix: YYYY-MM-DD where MM is 01-12 and DD is 01-31 (loose, not
# calendar-accurate; good enough to reject typos like 2026-13-01).
DATE_PREFIX_RE = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
)

# Obsidian periodic note filenames: YYYY-Y.md, YYYY-MNN.md, YYYY-WNN.md.
# These live in Journal/ and use their own naming convention rather than
# YYYY-MM-DD prefixes. Also accepts the "All *.md" aggregate rollup files.
PERIODIC_NOTE_RE = re.compile(r"^\d{4}-(?:Y|M\d{2}|W\d{2})\.md$|^All .+\.md$")


def is_in_dated_folder(path: str) -> bool:
    """True if path falls under a folder where dated naming is expected.

    Excludes `_sources/` children even if they're inside a dated parent.
    """
    if "/_sources/" in path or path.startswith("_sources/"):
        return False
    if path.startswith("Journal/"):
        return True
    return any(m in path for m in DATED_FOLDER_MARKERS if m != "Journal/")


# Match [[<name>.md]] or [[<name>.md|<alias>]]. Only .md — other
# extensions (.pdf, .jpg, .png) are attachments and keep their extension.
WIKILINK_MD_EXT_RE = re.compile(r"\[\[[^\]|\n]+\.md(\||\]\])")

# Markdown fenced code block delimiter (``` or ~~~, optional language tag).
FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)")
# Inline code span — strip backtick-delimited segments before scanning a line
# so `[[foo.md]]` (rendered as code) does not trip the wikilink check.
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def find_wikilink_ext_violations(content: str) -> list[tuple[int, str]]:
    """Return (1-indexed line number, matched text) for every [[*.md]] wikilink.

    Skips fenced code blocks (``` / ~~~) and inline code spans (`...`) so
    documentation that demonstrates a violation as a literal example does
    not trip the check. Limits false positives in design docs and READMEs
    that quote the canonical wrong form alongside the right one.
    """
    violations = []
    fence_char: str | None = None
    fence_len: int = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            char = marker[0]
            length = len(marker)
            if fence_char is None:
                fence_char = char
                fence_len = length
                continue
            if char == fence_char and length >= fence_len:
                # CommonMark: closing fence must be same char and at least as long.
                fence_char = None
                fence_len = 0
                continue
            # Inside a fence and this line isn't a valid closer — treat as content.
        if fence_char is not None:
            continue
        scan_line = INLINE_CODE_RE.sub("", line)
        for match in WIKILINK_MD_EXT_RE.finditer(scan_line):
            end = match.end()
            close = scan_line.find("]]", end - 2)
            if close != -1:
                text = scan_line[match.start() : close + 2]
            else:
                text = match.group(0)
            violations.append((lineno, text))
    return violations


def parse_frontmatter(content: str) -> tuple[dict | None, str | None]:
    """Parse YAML frontmatter block.

    Returns (parsed_dict, None) on success.
    Returns (None, error_message) on malformed YAML or missing closing delimiter.
    Returns (None, None) if the content has no frontmatter block at all.
    """
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        return None, None

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    close_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        return None, "frontmatter missing closing --- delimiter"

    block = "\n".join(lines[1:close_idx])
    if not block.strip():
        return {}, None
    if yaml is None:
        # Keep hooks/sweeps runnable under minimal system Python. Without
        # PyYAML we can still validate delimiter shape, but not full YAML syntax.
        return {}, None

    try:
        parsed = yaml.safe_load(block)
        if parsed is None:
            return {}, None
        if not isinstance(parsed, dict):
            return None, "frontmatter must be a YAML mapping (key: value)"
        return parsed, None
    except yaml.YAMLError as e:
        return None, str(e)
