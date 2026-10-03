#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""convention-sweep: vault-wide check for write-time convention violations.

Usage: uv run convention-sweep.py [vault_root]

Walks all `.md` files under <vault_root> (skipping dotfolders, _sources/,
.trash/, node_modules/) and runs the same three checks as the
i-insist vault checker and the SessionStart `doctor.py`
hook — using the shared `hooks/hookslib/patterns.py` module so all four
points (write-time, session-start, on-demand sweep, persistence) stay
in lockstep.

Exit 0 always. Issues printed to stdout, one per line, tab-separated:

  WIKILINK_EXT  <rel_path>:<lineno>  <matched_text>
  YAML_ERR      <rel_path>           <error_message>
  UNDATED_FILE  <rel_path>

Header block at top of output points to lib/state-files.md for the
needs-attention.md entry format.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from organizer_context import resolve_vault

# isort: split
# organizer_context puts the plugin's hooks on sys.path before this import.
from hookslib.patterns import (
    DATE_PREFIX_RE,
    PERIODIC_NOTE_RE,
    find_wikilink_ext_violations,
    is_in_dated_folder,
    parse_frontmatter,
)

SKIP_DIR_NAMES = {"_sources", ".trash", "node_modules"}


def iter_vault_md(vault_root: Path):
    for md in vault_root.rglob("*.md"):
        rel_parts = md.relative_to(vault_root).parts
        if any(part.startswith(".") or part in SKIP_DIR_NAMES for part in rel_parts):
            continue
        yield md


def sweep(vault_root: Path) -> list[str]:
    issues: list[str] = []
    for md in iter_vault_md(vault_root):
        rel = md.relative_to(vault_root)
        rel_str = str(rel)

        if is_in_dated_folder(rel_str):
            basename = md.name
            is_journal = rel_str.startswith("Journal/")
            if (
                basename != "index.md"
                and not DATE_PREFIX_RE.match(basename)
                and not (is_journal and PERIODIC_NOTE_RE.match(basename))
            ):
                issues.append(f"UNDATED_FILE\t{rel_str}")

        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, match in find_wikilink_ext_violations(content):
            issues.append(f"WIKILINK_EXT\t{rel_str}:{lineno}\t{match}")

        _, err = parse_frontmatter(content)
        if err:
            # PyYAML errors span multiple lines (parser context block);
            # collapse to a single line so each issue stays grep-friendly.
            flat_err = " | ".join(part.strip() for part in err.splitlines() if part.strip())
            issues.append(f"YAML_ERR\t{rel_str}\t{flat_err}")

    return issues


def print_header(lib_dir: Path, counts: dict[str, int]) -> None:
    total = sum(counts.values())
    if total == 0:
        return
    summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    print(f"# convention-sweep: {summary}")
    print("# All checks shared with i_insist.py + doctor.py via hooks/hookslib/patterns.py.")
    print(f"# needs-attention.md entry format → {lib_dir}/state-files.md")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_root", type=Path, nargs="?", help="default: configured vault")
    vault_root = resolve_vault(parser.parse_args().vault_root)

    lib_dir = Path(__file__).parent / "lib"
    issues = sweep(vault_root)

    if not issues:
        print("OK: no convention violations found")
        return

    counts: dict[str, int] = {"WIKILINK_EXT": 0, "UNDATED_FILE": 0, "YAML_ERR": 0}
    for line in issues:
        issue_type = line.split("\t")[0]
        if issue_type in counts:
            counts[issue_type] += 1

    print_header(lib_dir, counts)
    print("\n".join(issues))


if __name__ == "__main__":
    main()
