#!/usr/bin/env python3
"""Generate or refresh MEMORY.md (the pointer index) at every vault memory dir.

Scans <vault>/wiki/repos/**/memory/ and <vault>/wiki/systems/machines/*/memory/
(plus any other dirs containing feedback_/project_/reference_ files), and
writes/refreshes MEMORY.md with one line per fact file, parsed from each file's
frontmatter `description`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Add hooks/ so we can reuse vault_config.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "hooks"))

from hookslib.vault_config import load_vault_roots  # noqa: E402

FACT_PREFIXES = ("feedback_", "project_", "reference_", "user_")


def parse_description(path: Path) -> str:
    """Pull the `description:` from YAML frontmatter, or fallback to filename."""
    try:
        head = path.read_text(encoding="utf-8")[:2000]
    except OSError:
        return path.stem
    if not head.startswith("---"):
        return path.stem
    end = head.find("---", 3)
    if end == -1:
        return path.stem
    fm = head[3:end]
    m = re.search(r"^description:\s*(.+)$", fm, re.MULTILINE)
    if not m:
        return path.stem
    return m.group(1).strip().strip("'\"")


def find_memory_dirs(vault: Path) -> list[Path]:
    out: list[Path] = []
    # Repo-scoped
    for d in (vault / "wiki" / "repos").glob("*/*/memory"):
        if d.is_dir():
            out.append(d)
    # Host-scoped
    for d in (vault / "wiki" / "systems" / "machines").glob("*/memory"):
        if d.is_dir():
            out.append(d)
    # Other (orphan rescues, e.g. systems/my-domains/memory)
    for d in vault.glob("wiki/**/memory"):
        if d.is_dir() and d not in out:
            out.append(d)
    return sorted(set(out))


def build_index(memory_dir: Path) -> str:
    facts = sorted(
        p for p in memory_dir.iterdir() if p.is_file() and p.suffix == ".md" and p.name != "MEMORY.md"
    )
    lines = [f"- [{p.name}]({p.name}) — {parse_description(p)}" for p in facts]
    return "\n".join(lines) + "\n" if lines else "_(empty)_\n"


def main() -> int:
    vault_roots = load_vault_roots()
    if len(vault_roots) != 1:
        print(f"ERROR: expected exactly 1 vault root; got {vault_roots}")
        return 2
    vault = Path(vault_roots[0])

    n = 0
    for d in find_memory_dirs(vault):
        index = d / "MEMORY.md"
        body = build_index(d)
        index.write_text(body)
        print(f"  {index}  ({body.count(chr(10))} entries)")
        n += 1
    print(f"\nupdated {n} MEMORY.md file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
