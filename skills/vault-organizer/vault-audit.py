#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""vault-audit: structural audit of wiki/ tree + vault-wide content checks.

Usage: uv run vault-audit.py [vault_root]

Reads zone config from <vault_root>/.claude/obsidian-knowledge.yaml to determine
which folders are ai_managed. Falls back to 'wiki' if config missing.

Exit 0 always. Issues printed to stdout, one per line:

  MISSING_INDEX        <folder>
  EMPTY_FOLDER         <folder>
  NOT_INDEXED          <index_path>  entry=<name>
  DUMPING_GROUND       <folder>  inline=<N>  subfolders=<M>
  STACKED_FRONTMATTER  <file>

Structural issues (MISSING_*, DUMPING_GROUND) are scoped to ai_managed zones.
STACKED_FRONTMATTER is vault-wide (skips _sources/, .trash/, hidden dirs).

A header block at the top of output points to lib/ reference files.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml
from organizer_context import resolve_vault

SKIP_NAMES = {"index.md"}
SKIP_PATTERNS = [
    re.compile(r"^TODO-", re.IGNORECASE),
    re.compile(r"^CLAUDE", re.IGNORECASE),
]
TYPED_SUBFOLDERS = {"plans", "convos", "diary", "reference", "_sources", "archive"}
DUMPING_GROUND_SKIP_NAMES = {"archive", "_sources", "Utility"}
DUMPING_GROUND_THRESHOLD = 4
AUDIT_SKIP_ZONES = {"Utility"}
SCAN_SKIP_DIR_NAMES = {"_sources", ".trash", "node_modules"}
INDEX_SKIP_DIR_NAMES = {"_sources", "node_modules"}
SYNC_CONFLICT_RE = re.compile(r"\.sync-conflict-\d{8}-\d{6}-[^/]+\.md$", re.IGNORECASE)
FRONTMATTER_SCAN_LINE_LIMIT = 60

# Patterns matching filenames that belong in a typed subfolder (diary/, convos/,
# plans/) rather than at folder root. Inline files NOT matching these are
# treated as wiki/guide notes — convention says those stay at root and should
# not count toward the dumping-ground threshold.
MISPLACED_INLINE_PATTERNS = [
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}"),  # date-prefixed: diary/log
    re.compile(r"-design\.md$", re.IGNORECASE),  # design doc / plan
    re.compile(r"-convo\.md$", re.IGNORECASE),  # convo note
    re.compile(r"-diary\.md$", re.IGNORECASE),  # diary note
]


def load_managed_zones(vault_root: Path) -> list[str]:
    config_path = vault_root / ".claude" / "obsidian-knowledge.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("ai_managed", ["wiki"])
    return ["wiki"]


def is_skipped(name: str) -> bool:
    if name in SKIP_NAMES or name.startswith("."):
        return True
    if SYNC_CONFLICT_RE.search(name):
        return True
    return any(p.match(name) for p in SKIP_PATTERNS)


def extract_wikilink_targets(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]|#^]+)(?:[#^|][^\]]*)?\]\]", text))


def has_visible_content(folder: Path) -> bool:
    return any(
        path.is_file()
        and not path.is_symlink()
        and path.name != "index.md"
        and not SYNC_CONFLICT_RE.search(path.name)
        and not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(folder).parts)
        for path in folder.rglob("*")
    )


def links_entry(targets: set[str], entry: Path, folder: Path, vault_root: Path) -> bool:
    expected = entry.relative_to(vault_root).as_posix().removesuffix(".md")
    local = entry.relative_to(folder).as_posix().removesuffix(".md")
    return any(target.removesuffix(".md") in {expected, local} for target in targets)


def audit_folder(folder: Path, vault_root: Path) -> list[str]:
    issues: list[str] = []

    if not has_visible_content(folder):
        return [f"EMPTY_FOLDER\t{folder}"]

    children_dirs = [
        d
        for d in folder.iterdir()
        if d.is_dir()
        and not d.is_symlink()
        and not d.name.startswith(".")
        and d.name not in INDEX_SKIP_DIR_NAMES
        and has_visible_content(d)
    ]
    children_md = [f for f in folder.iterdir() if f.is_file() and not f.is_symlink() and f.suffix == ".md"]

    index = folder / "index.md"

    if not index.exists():
        issues.append(f"MISSING_INDEX\t{folder}")
        return issues

    index_text = index.read_text(encoding="utf-8", errors="replace")
    linked_targets = extract_wikilink_targets(index_text)

    for md in children_md:
        if is_skipped(md.name):
            continue
        if not links_entry(linked_targets, md, folder, vault_root):
            issues.append(f"NOT_INDEXED\t{index}\tentry={md.name}")

    for d in children_dirs:
        if d.name.startswith("."):
            continue
        if not links_entry(linked_targets, d / "index.md", folder, vault_root):
            issues.append(f"NOT_INDEXED\t{index}\tentry={d.name}/")

    has_subfolders = len(children_dirs) > 0
    if has_subfolders and folder.name not in DUMPING_GROUND_SKIP_NAMES | TYPED_SUBFOLDERS:
        inline_files = [f for f in children_md if not is_skipped(f.name) and f.name.lower() != "index.md"]
        misplaced = [f for f in inline_files if is_misplaced_inline(f.name)]
        if len(misplaced) >= DUMPING_GROUND_THRESHOLD:
            issues.append(
                f"DUMPING_GROUND\t{folder}\t"
                f"misplaced={len(misplaced)}\tinline_total={len(inline_files)}\t"
                f"subfolders={len(children_dirs)}"
            )

    return issues


def is_misplaced_inline(filename: str) -> bool:
    """True if filename matches a pattern indicating it belongs in a typed subfolder.

    Wiki/guide/TODO notes belong inline at folder root per convention. Diary,
    convo, and design-doc files belong in dated subfolders. Filename patterns
    distinguish them: date-prefixed names and `-design`/`-convo`/`-diary`
    suffixes are signals of misplacement.
    """
    return any(p.search(filename) for p in MISPLACED_INLINE_PATTERNS)


def has_stacked_frontmatter(file: Path) -> bool:
    """True if file starts with two consecutive YAML frontmatter blocks.

    Pattern: line 1 is `---`, find closing `---`, then next non-blank line is
    also `---`. Triggered by tools like update-time-on-edit injecting a
    `created/updated` block on top of a Templater-emitted block.
    """
    try:
        with open(file, encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= FRONTMATTER_SCAN_LINE_LIMIT:
                    break
                lines.append(line.rstrip("\n"))
    except OSError:
        return False

    if not lines or lines[0] != "---":
        return False

    close_idx = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if close_idx is None:
        return False

    j = close_idx + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1

    return j < len(lines) and lines[j] == "---"


def walk_vault_for_stacked_frontmatter(vault_root: Path) -> list[str]:
    issues: list[str] = []
    for md in vault_root.rglob("*.md"):
        rel_parts = md.relative_to(vault_root).parts
        if any(part.startswith(".") or part in SCAN_SKIP_DIR_NAMES for part in rel_parts):
            continue
        if SYNC_CONFLICT_RE.search(md.name) or md.is_symlink():
            continue
        if has_stacked_frontmatter(md):
            issues.append(f"STACKED_FRONTMATTER\t{md}")
    return issues


def walk_managed(vault_root: Path, zone: str) -> list[str]:
    zone_root = vault_root / zone
    if not zone_root.exists():
        return []

    all_issues: list[str] = []
    for folder in sorted([zone_root] + [d for d in zone_root.rglob("*") if d.is_dir()]):
        if any(part.startswith(".") for part in folder.parts):
            continue
        if any(part in SCAN_SKIP_DIR_NAMES for part in folder.parts) or folder.is_symlink():
            continue
        all_issues.extend(audit_folder(folder, vault_root))

    return all_issues


def print_header(lib_dir: Path, counts: dict[str, int]) -> None:
    total = sum(counts.values())
    if total == 0:
        return
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    print(f"# vault-audit: {summary}")
    print("# Fix guides (read only what you need):")
    print(f"#   MISSING_INDEX, NOT_INDEXED   → {lib_dir}/index-format.md")
    print("#   EMPTY_FOLDER                → triage; do not create an empty index or delete")
    print(f"#   DUMPING_GROUND               → {lib_dir}/note-types.md")
    print(f"#   STACKED_FRONTMATTER          → {lib_dir}/stacked-frontmatter.md")
    print(f"#   State file formats           → {lib_dir}/state-files.md")
    print(f"#   Broken links (run separately)→ {lib_dir}/broken-links.md")
    print(f"#   Rename ambiguous files       → {lib_dir}/rename-files.md")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_root", type=Path, nargs="?", help="default: configured vault")
    vault_root = resolve_vault(parser.parse_args().vault_root)

    lib_dir = Path(__file__).parent / "lib"

    zones = [z for z in load_managed_zones(vault_root) if z not in AUDIT_SKIP_ZONES]
    issues: list[str] = []
    for zone in zones:
        issues.extend(walk_managed(vault_root, zone))
    issues.extend(walk_vault_for_stacked_frontmatter(vault_root))

    if not issues:
        print("OK: no structural issues found")
        return

    counts: dict[str, int] = {
        "MISSING_INDEX": 0,
        "EMPTY_FOLDER": 0,
        "NOT_INDEXED": 0,
        "DUMPING_GROUND": 0,
        "STACKED_FRONTMATTER": 0,
    }
    for line in issues:
        issue_type = line.split("\t")[0]
        if issue_type in counts:
            counts[issue_type] += 1

    print_header(lib_dir, counts)
    print("\n".join(issues))


if __name__ == "__main__":
    main()
