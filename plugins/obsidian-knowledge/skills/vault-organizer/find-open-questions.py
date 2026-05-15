#!/usr/bin/env python3
"""find-open-questions: scan ai_managed zones for `> [!question]` callouts.

Usage: python3 find-open-questions.py <vault_root>

Skips matches inside fenced code blocks (``` or ~~~), which are usually
documentation examples rather than real open questions. Emits one line per
hit:

  <relative_path>\t<line_number>\t<question_text>

Exit 0 always. Reads ai_managed zones from
<vault_root>/.claude/obsidian-knowledge.yaml; falls back to ['wiki'].
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

QUESTION_MARKER = "> [!question]"
SCAN_SKIP_DIR_NAMES = {"_sources", ".trash", "node_modules"}


def load_managed_zones(vault_root: Path) -> list[str]:
    config_path = vault_root / ".claude" / "obsidian-knowledge.yaml"
    if HAS_YAML and config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("ai_managed", ["wiki"])
    return ["wiki"]


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return [(line_no, question_text)] for each callout outside code fences."""
    hits: list[tuple[int, str]] = []
    in_fence = False
    fence_marker = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return hits

    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        # Track fenced code-block state. Markdown fences start with ``` or ~~~.
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            continue

        if in_fence:
            continue

        if line.rstrip("\n").startswith(QUESTION_MARKER):
            # Question text is on the next non-blank `> ` line.
            question_text = ""
            for j in range(i, len(lines)):
                next_line = lines[j].rstrip("\n")
                if next_line.startswith("> ") and next_line.strip() != ">":
                    question_text = next_line[2:].strip()
                    break
                if not next_line.startswith(">"):
                    break
            hits.append((i, question_text))

    return hits


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <vault_root>", file=sys.stderr)
        sys.exit(1)

    vault_root = Path(sys.argv[1]).resolve()
    if not vault_root.is_dir():
        print(f"Error: {vault_root} is not a directory", file=sys.stderr)
        sys.exit(1)

    zones = load_managed_zones(vault_root)
    for zone in zones:
        zone_root = vault_root / zone
        if not zone_root.is_dir():
            continue
        for md in sorted(zone_root.rglob("*.md")):
            rel_parts = md.relative_to(vault_root).parts
            if any(part.startswith('.') or part in SCAN_SKIP_DIR_NAMES for part in rel_parts):
                continue
            for line_no, text in scan_file(md):
                rel = md.relative_to(vault_root)
                print(f"{rel}\t{line_no}\t{text}")


if __name__ == "__main__":
    main()
