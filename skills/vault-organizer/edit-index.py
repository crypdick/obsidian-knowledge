#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml", "pydantic>=2"]
# ///
"""Render reviewed JSON entries into one index section; --apply verifies writes.

Usage: uv run edit-index.py [VAULT] wiki/topic/index.md [--apply] < reviewed.json
Input: {"section": "Notes", "entries": [{"target": "wiki/topic/note",
         "description": "orientation", "label": "optional display name"}]}
For a new flat index, supply "title" instead of "section". Existing prose and
other sections remain byte-for-byte intact. Ambiguous entry blocks are refused.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from organizer_context import resolve_vault
from organizer_io import OrganizerPolicy, visible_path, write_checked
from pydantic import BaseModel, ConfigDict, field_validator

ENTRY = re.compile(r"^- \[\[([^\]|#^]+)(?:\|[^\]]+)?\]\].*$")
HEADING = re.compile(r"^(#{1,6}) (.+?)\s*$")


class ReviewedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target: str
    description: str
    label: str | None = None

    @field_validator("target", "label")
    @classmethod
    def single_link_component(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(c in value for c in "\n\r[]|#^")):
            raise ValueError("target and label must be nonblank single link components")
        return value

    @field_validator("description")
    @classmethod
    def one_line(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("description must be a nonblank single line")
        return value

    def render(self) -> str:
        label = f"|{self.label}" if self.label else ""
        return f"- [[{self.target.removesuffix('.md')}{label}]] — {self.description}\n"


class IndexReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    section: str | None = None
    title: str | None = None
    entries: tuple[ReviewedEntry, ...]

    @field_validator("section", "title")
    @classmethod
    def heading_text(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\n" in value or "\r" in value):
            raise ValueError("heading must be a nonblank single line")
        return value


def resolve_entry(vault: Path, index: Path, target: str) -> Path:
    for relative in (target, target + ".md"):
        for candidate in (relative, (index.parent.relative_to(vault) / relative).as_posix()):
            path = visible_path(vault, candidate)
            if path.is_file():
                return path
    raise ValueError(f"target does not exist: {target}")


def section_bounds(lines: tuple[str, ...], section: str | None) -> tuple[int, int]:
    headings = tuple((i, match) for i, line in enumerate(lines) if (match := HEADING.match(line)))
    if section is None:
        if any(len(match[1]) > 1 for _, match in headings):
            raise ValueError("sectioned index requires an explicit section")
        return (headings[0][0] + 1 if headings else 0), len(lines)
    matches = tuple((i, match) for i, match in headings if match[2] == section)
    if len(matches) != 1:
        raise ValueError(f"section must exist exactly once: {section}")
    start, selected = matches[0]
    end = next((i for i, match in headings if i > start and len(match[1]) <= len(selected[1])), len(lines))
    if any(i > start and i < end for i, _ in headings):
        raise ValueError("select a leaf section without nested headings")
    return start + 1, end


def sort_entry(line: str) -> tuple[bool, str]:
    match = ENTRY.match(line)
    assert match is not None
    target = match[1].removesuffix(".md")
    folder = target.endswith("/index")
    name = Path(target).parent.name if folder else Path(target).name
    return not folder, name.casefold()


def reviewed_entries(
    vault: Path, index: Path, existing_lines: tuple[str, ...], review: IndexReview
) -> tuple[str, ...]:
    entries = list(existing_lines)
    for entry in review.entries:
        resolved = resolve_entry(vault, index, entry.target)
        if resolved == index:
            raise ValueError("index cannot link to itself")
        matching = []
        for i, line in enumerate(entries):
            match = ENTRY.match(line)
            assert match is not None
            try:
                existing = resolve_entry(vault, index, match[1])
            except ValueError:
                continue
            if existing == resolved:
                matching.append(i)
        if len(matching) > 1:
            raise ValueError(f"duplicate existing entries: {entry.target}")
        if matching:
            entries[matching[0]] = entry.render()
        else:
            entries.append(entry.render())
    return tuple(sorted(entries, key=sort_entry))


def render_index(vault: Path, index: Path, before: str | None, review: IndexReview) -> str:
    if before is None:
        if not review.title or review.section is not None:
            raise ValueError("new index requires title and no section")
        before = f"# {review.title}\n\n"
    lines = tuple(before.splitlines(keepends=True))
    if any(line.lstrip().startswith(("```", "~~~")) for line in lines):
        raise ValueError("index contains fenced examples; review it manually")
    start, end = section_bounds(lines, review.section)
    positions = tuple(i for i in range(start, end) if ENTRY.match(lines[i]))
    if positions and positions != tuple(range(positions[0], positions[-1] + 1)):
        raise ValueError("section has multiple entry blocks; review them separately")
    block_start = positions[0] if positions else end
    block_end = positions[-1] + 1 if positions else end
    if (
        positions
        and block_end < end
        and lines[block_end].strip()
        and lines[block_end].startswith((" ", "\t"))
    ):
        raise ValueError("entry has continuation text; review it manually")
    entries = reviewed_entries(vault, index, lines[block_start:block_end], review)
    prefix = "".join(lines[:block_start])
    suffix = "".join(lines[block_end:])
    if not positions and entries:
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n" if prefix.endswith("\n") else "\n\n"
        if suffix and not suffix.startswith("\n"):
            suffix = "\n" + suffix
    return prefix + "".join(entries) + suffix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_root", type=Path, nargs="?", help="default: configured vault")
    parser.add_argument("index_path")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        vault = resolve_vault(args.vault_root)
        if Path(args.index_path).name != "index.md":
            raise ValueError("edit-index only edits index.md")
        index = OrganizerPolicy.load(vault).writable(vault, args.index_path)
        before = index.read_bytes().decode("utf-8") if index.exists() else None
        review = IndexReview.model_validate_json(sys.stdin.read())
        after = render_index(vault, index, before, review)
        if args.apply:
            write_checked(vault, args.index_path, before, after)
        else:
            sys.stdout.write(after)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
