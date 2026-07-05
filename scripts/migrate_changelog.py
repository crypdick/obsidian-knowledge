#!/usr/bin/env python3
"""One-shot migration: changelog.md → per-session files in changelog/.

Parses the monolithic changelog.md, splits on H2 date headers, converts
each section to a terse 1-liner file under changelog/. Renames the original
to changelog-archive.md when done.

Usage:
    uv run python scripts/migrate_changelog.py --vault /path/to/vault   # dry-run
    uv run python scripts/migrate_changelog.py --vault /path/to/vault --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Entry:
    date: str
    title: str
    body: str


@dataclass
class MigrateResult:
    would_create: int = 0
    created: int = 0
    skipped: int = 0


_H2_SPLIT_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.+)$", re.MULTILINE)
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9\s-]")
_SLUG_SPACE_RE = re.compile(r"[\s_]+")
_SLUG_DASH_RE = re.compile(r"-{2,}")


def slugify(title: str, max_len: int = 60) -> str:
    s = title.lower()
    s = _SLUG_STRIP_RE.sub("", s)
    s = _SLUG_SPACE_RE.sub("-", s)
    s = _SLUG_DASH_RE.sub("-", s)
    s = s[:max_len].rstrip("-")
    return s


def entry_to_filename(date: str, title: str) -> str:
    return f"{date}-000000-{slugify(title)}.md"


def extract_diary_links(body: str) -> list[str]:
    all_links = re.findall(r"\[\[[^\]]+\]\]", body)
    return [link for link in all_links if "/diary/" in link or "/convos/" in link]


def parse_entries(content: str) -> list[Entry]:
    matches = list(_H2_SPLIT_RE.finditer(content))
    if not matches:
        return []
    entries = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        entries.append(Entry(date=m.group(1), title=m.group(2).strip(), body=body))
    return entries


def _format_entry_content(entry: Entry) -> str:
    line = f"{entry.date} 00:00 — {entry.title}"
    diary_links = extract_diary_links(entry.body)
    if diary_links:
        line += " " + " ".join(f"→ {lnk}" for lnk in diary_links)
    return line + "\n"


def migrate(vault_root: Path, apply: bool = False) -> MigrateResult:
    utility = vault_root / "Utility" / "obsidian-knowledge"
    changelog_md = utility / "changelog.md"
    changelog_dir = utility / "changelog"
    archive = utility / "changelog-archive.md"

    if not changelog_md.exists():
        print(f"Nothing to do: {changelog_md} not found.", file=sys.stderr)
        return MigrateResult()

    content = changelog_md.read_text(encoding="utf-8")
    entries = parse_entries(content)
    result = MigrateResult()

    if not entries:
        print("No H2 entries found in changelog.md.", file=sys.stderr)
        return result

    for entry in entries:
        filename = entry_to_filename(entry.date, entry.title)
        dest = changelog_dir / filename
        if apply and dest.exists():
            result.skipped += 1
            print(f"  skip (exists): {filename}")
            continue
        result.would_create += 1
        if apply:
            changelog_dir.mkdir(exist_ok=True)
            dest.write_text(_format_entry_content(entry), encoding="utf-8")
            result.created += 1
            print(f"  create: {filename}")
        else:
            print(f"  would create: {filename}")

    if apply:
        if result.created > 0:
            changelog_md.rename(archive)
            print("\nRenamed changelog.md → changelog-archive.md")
        print(f"Done: {result.created} created, {result.skipped} skipped.")
    else:
        print(f"\nDry run: {result.would_create} entries would be created. Pass --apply to execute.")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="Vault root (default: cwd)")
    parser.add_argument("--apply", action="store_true", help="Write files (default: dry-run)")
    args = parser.parse_args()
    migrate(args.vault, apply=args.apply)


if __name__ == "__main__":
    main()
