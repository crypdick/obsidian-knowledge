"""Audit managed-zone structure and vault-wide Markdown conventions."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from gardener.conventions import sweep
from gardener.io import OrganizerPolicy, iter_markdown, iter_paths, resolve_vault, visible_path

SKIP_NAMES = {"index.md"}
SKIP_PATTERNS = [
    re.compile(r"^TODO-", re.IGNORECASE),
    re.compile(r"^CLAUDE", re.IGNORECASE),
]
TYPED_SUBFOLDERS = {"plans", "convos", "diary", "reference", "_sources", "archive"}
DUMPING_GROUND_SKIP_NAMES = {"archive", "_sources", "Utility"}
DUMPING_GROUND_THRESHOLD = 4
AUDIT_SKIP_ZONES = {"Utility"}
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


def is_skipped(name: str) -> bool:
    if name in SKIP_NAMES:
        return True
    return any(p.match(name) for p in SKIP_PATTERNS)


def extract_wikilink_targets(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]|#^]+)(?:[#^|][^\]]*)?\]\]", text))


def has_visible_content(folder: Path, vault_root: Path) -> bool:
    return any(
        path.is_file() and path.name != "index.md"
        for path in iter_paths(vault_root, folder.relative_to(vault_root).as_posix())
    )


def links_entry(targets: set[str], entry: Path, folder: Path, vault_root: Path) -> bool:
    expected = entry.relative_to(vault_root).as_posix().removesuffix(".md")
    local = entry.relative_to(folder).as_posix().removesuffix(".md")
    return any(target.removesuffix(".md") in {expected, local} for target in targets)


def audit_folder(folder: Path, vault_root: Path) -> list[str]:
    issues: list[str] = []

    if not has_visible_content(folder, vault_root):
        return [f"EMPTY_FOLDER\t{folder}"]

    children = []
    for child in folder.iterdir():
        try:
            visible_path(vault_root, child.relative_to(vault_root).as_posix())
        except ValueError:
            continue
        children.append(child)
    children_dirs = [d for d in children if d.is_dir() and has_visible_content(d, vault_root)]
    children_md = [f for f in children if f.is_file() and f.suffix == ".md"]

    index = folder / "index.md"

    if index not in children:
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
    for md in iter_markdown(vault_root):
        if has_stacked_frontmatter(md):
            issues.append(f"STACKED_FRONTMATTER\t{md}")
    return issues


def walk_managed(vault_root: Path, zone: str) -> list[str]:
    all_issues: list[str] = []
    for folder in iter_paths(vault_root, zone):
        if folder.is_dir():
            all_issues.extend(audit_folder(folder, vault_root))

    return all_issues


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", dest="vault_root", type=Path, help="default: configured vault")
    vault_root = resolve_vault(parser.parse_args(argv).vault_root)

    zones = [z for z in OrganizerPolicy.load(vault_root).ai_managed if z not in AUDIT_SKIP_ZONES]
    issues: list[str] = []
    for zone in zones:
        issues.extend(walk_managed(vault_root, zone))
    issues.extend(walk_vault_for_stacked_frontmatter(vault_root))
    issues.extend(sweep(vault_root))

    if not issues:
        print("OK: no structural or convention issues found")
        return

    print("\n".join(issues))
