"""Convention patterns shared between write-time hook, SessionStart doctor, and vault-organizer sweep.

Single source of truth — all three consumers import from this module so
prevention, surfacing, and persistence stay in lockstep.
"""

from __future__ import annotations

import re
from types import ModuleType
from typing import Any

from markdown_spans import markdown_text
from note_frontmatter import frontmatter_envelope

yaml: ModuleType | None
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
DATE_PREFIX_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])")

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


def dated_filename_violation(path: str) -> bool:
    """Apply the complete date convention, including periodic Journal exceptions."""
    # NOTE: docs/hooks.md documents this shared guard/doctor/gardener policy.
    basename = path.rsplit("/", 1)[-1]
    return bool(
        is_in_dated_folder(path)
        and basename != "index.md"
        and not DATE_PREFIX_RE.match(basename)
        and not (path.startswith("Journal/") and PERIODIC_NOTE_RE.match(basename))
    )


# Match [[<name>.md]] or [[<name>.md|<alias>]]. Only .md — other
# extensions (.pdf, .jpg, .png) are attachments and keep their extension.
WIKILINK_MD_EXT_RE = re.compile(r"\[\[[^\]|\n]+\.md(\||\]\])")


def find_wikilink_ext_violations(content: str) -> list[tuple[int, str]]:
    """Find actual [[*.md]] links, excluding fenced and inline code examples."""
    violations = []
    for lineno, line in enumerate(markdown_text(content).splitlines(), start=1):
        for match in WIKILINK_MD_EXT_RE.finditer(line):
            close = line.find("]]", match.end() - 2)
            text = line[match.start() : close + 2] if close != -1 else match.group(0)
            violations.append((lineno, text))
    return violations


def parse_frontmatter(content: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse YAML frontmatter block.

    Returns (parsed_dict, None) on success.
    Returns (None, error_message) on malformed YAML or missing closing delimiter.
    Returns (None, None) if the content has no frontmatter block at all.
    """
    try:
        envelope = frontmatter_envelope(content)
    except ValueError as exc:
        return None, str(exc)
    if envelope is None:
        return None, None
    block = envelope["yaml"]
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


def is_published(content: str, *, fragment: bool = False) -> bool:
    """Interpret publication as YAML Boolean true, never a text match.

    Edit events can contain a YAML fragment rather than a complete note.
    Malformed frontmatter fails closed; arbitrary non-YAML body fragments do
    not themselves establish publication.
    """
    if yaml is None:
        raise ValueError("PyYAML required to determine publication state")
    metadata, error = parse_frontmatter(content)
    if error:
        raise ValueError(error)
    if metadata is None and fragment:
        try:
            candidate = yaml.safe_load(content)
        except yaml.YAMLError:
            return False
        metadata = candidate if isinstance(candidate, dict) else None
    return bool(metadata and metadata.get("dg-publish") is True)
