"""Convention patterns shared between write-time hook, SessionStart doctor, and vault-organizer sweep.

Single source of truth — all three consumers import from this module so
prevention, surfacing, and persistence stay in lockstep.
"""

from __future__ import annotations

import re

import yaml

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


def find_wikilink_ext_violations(content: str) -> list[tuple[int, str]]:
    """Return (1-indexed line number, matched text) for every [[*.md]] wikilink."""
    violations = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        for match in WIKILINK_MD_EXT_RE.finditer(line):
            end = match.end()
            close = line.find("]]", end - 2)
            if close != -1:
                text = line[match.start() : close + 2]
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
    try:
        parsed = yaml.safe_load(block)
        if parsed is None:
            return {}, None
        if not isinstance(parsed, dict):
            return None, "frontmatter must be a YAML mapping (key: value)"
        return parsed, None
    except yaml.YAMLError as e:
        return None, str(e)
