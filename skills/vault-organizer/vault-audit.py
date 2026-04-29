#!/usr/bin/env python3
"""vault-audit: structural audit of wiki/ tree + vault-wide content checks.

Usage: python3 vault-audit.py <vault_root>

Reads zone config from <vault_root>/.claude/obsidian-knowledge.yaml to determine
which folders are ai_managed. Falls back to 'wiki' if config missing.

Exit 0 always. Issues printed to stdout, one per line:

  MISSING_INDEX        <folder>
  MISSING_ENTRY        <index_path>  missing=<name>
  DUMPING_GROUND       <folder>  inline=<N>  subfolders=<M>
  STACKED_FRONTMATTER  <file>

Structural issues (MISSING_*, DUMPING_GROUND) are scoped to ai_managed zones.
STACKED_FRONTMATTER is vault-wide (skips _sources/, .trash/, hidden dirs).

A header block at the top of output points to lib/ reference files.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

SKIP_NAMES = {"index.md"}
SKIP_PATTERNS = [
    re.compile(r'^TODO-', re.IGNORECASE),
    re.compile(r'^CLAUDE', re.IGNORECASE),
]
TYPED_SUBFOLDERS = {"plans", "convos", "diary", "reference", "_sources", "archive"}
DUMPING_GROUND_SKIP_NAMES = {"archive", "_sources", "Utility"}
DUMPING_GROUND_THRESHOLD = 4
AUDIT_SKIP_ZONES = {"Utility"}
SCAN_SKIP_DIR_NAMES = {"_sources", ".trash", "node_modules"}
FRONTMATTER_SCAN_LINE_LIMIT = 60


def load_managed_zones(vault_root: Path) -> list[str]:
    config_path = vault_root / ".claude" / "obsidian-knowledge.yaml"
    if HAS_YAML and config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("ai_managed", ["wiki"])
    return ["wiki"]


def is_skipped(name: str) -> bool:
    if name in SKIP_NAMES:
        return True
    return any(p.match(name) for p in SKIP_PATTERNS)


def extract_wikilink_targets(text: str) -> set[str]:
    return set(re.findall(r'\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]', text))


def audit_folder(folder: Path) -> list[str]:
    issues: list[str] = []

    children_dirs = [d for d in folder.iterdir() if d.is_dir() and not d.name.startswith('.')]
    children_md = [f for f in folder.iterdir() if f.is_file() and f.suffix == '.md']

    index = folder / "index.md"

    if not index.exists():
        issues.append(f"MISSING_INDEX\t{folder}")
        return issues

    index_text = index.read_text(encoding="utf-8", errors="replace")
    linked_targets = extract_wikilink_targets(index_text)
    linked_basenames = {
        component.lower().removesuffix('.md')
        for t in linked_targets
        for component in t.rstrip('/').split('/')
    }

    for md in children_md:
        if is_skipped(md.name):
            continue
        if md.stem.lower() not in linked_basenames:
            issues.append(f"MISSING_ENTRY\t{index}\tmissing={md.name}")

    for d in children_dirs:
        if d.name.startswith('.'):
            continue
        if d.name.lower() not in linked_basenames:
            issues.append(f"MISSING_ENTRY\t{index}\tmissing={d.name}/")

    has_subfolders = len(children_dirs) > 0
    if has_subfolders and folder.name not in DUMPING_GROUND_SKIP_NAMES:
        inline_files = [
            f for f in children_md
            if not is_skipped(f.name) and f.name.lower() != "index.md"
        ]
        if len(inline_files) >= DUMPING_GROUND_THRESHOLD:
            issues.append(
                f"DUMPING_GROUND\t{folder}\t"
                f"inline={len(inline_files)}\tsubfolders={len(children_dirs)}"
            )

    return issues


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
                lines.append(line.rstrip('\n'))
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
        if any(part.startswith('.') or part in SCAN_SKIP_DIR_NAMES for part in rel_parts):
            continue
        if has_stacked_frontmatter(md):
            issues.append(f"STACKED_FRONTMATTER\t{md}")
    return issues


def walk_managed(vault_root: Path, zone: str) -> list[str]:
    zone_root = vault_root / zone
    if not zone_root.exists():
        return []

    all_issues: list[str] = []
    for folder in sorted([zone_root] + [d for d in zone_root.rglob('*') if d.is_dir()]):
        if any(part.startswith('.') for part in folder.parts):
            continue
        if '_sources' in folder.parts:
            continue
        all_issues.extend(audit_folder(folder))

    return all_issues


def print_header(lib_dir: Path, counts: dict[str, int]) -> None:
    total = sum(counts.values())
    if total == 0:
        return
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    print(f"# vault-audit: {summary}")
    print(f"# Fix guides (read only what you need):")
    print(f"#   MISSING_INDEX, MISSING_ENTRY → {lib_dir}/index-format.md")
    print(f"#   DUMPING_GROUND               → {lib_dir}/note-types.md")
    print(f"#   STACKED_FRONTMATTER          → {lib_dir}/stacked-frontmatter.md")
    print(f"#   State file formats           → {lib_dir}/state-files.md")
    print(f"#   Broken links (run separately)→ {lib_dir}/broken-links.md")
    print(f"#   Rename ambiguous files       → {lib_dir}/rename-files.md")
    print()


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <vault_root>", file=sys.stderr)
        sys.exit(1)

    vault_root = Path(sys.argv[1]).resolve()
    if not vault_root.is_dir():
        print(f"Error: {vault_root} is not a directory", file=sys.stderr)
        sys.exit(1)

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
        "MISSING_ENTRY": 0,
        "DUMPING_GROUND": 0,
        "STACKED_FRONTMATTER": 0,
    }
    for line in issues:
        issue_type = line.split('\t')[0]
        if issue_type in counts:
            counts[issue_type] += 1

    print_header(lib_dir, counts)
    print("\n".join(issues))


if __name__ == "__main__":
    main()
