#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""filter-unresolved-links: filter `obsidian unresolved` JSON output.

Usage:
  obsidian unresolved verbose format=json | uv run filter-unresolved-links.py [vault_root]

Reads `stub_link_patterns:` from <vault_root>/.claude/obsidian-knowledge.yaml
to know which link names are intentional concept-stubs (not real broken
references). Falls back to a built-in default list.

Drops entries that:
  - have no source files in ai_managed zones (links from outside the
    managed tree are not the organizer's concern)
  - match a stub pattern
  - are template placeholders (`{{...}}` or `<% ... %>`)

Emits the surviving entries one per line:
  <count>\t<link>\t<comma-separated-managed-sources>
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from pathlib import Path

import yaml
from organizer_context import resolve_vault

# Don't crash with a BrokenPipeError when stdout is piped to head/less.
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

DEFAULT_STUB_PATTERNS = [
    r"^\(PAPER\) ",
    r"^\(VIDEO\) ",
    r"^\(POST\) ",
    r"^\(PODCAST\) ",
    r"^\(RECIPE\) ",
    r"^\(BOOK\) ",
    r"^\(Vision\) ",
    r"^\(Pillar\) ",
    r"^@",  # @Person stubs
]
TEMPLATE_PLACEHOLDER = re.compile(r"\{\{|\<%")


def load_config(vault_root: Path) -> tuple[list[str], list[re.Pattern]]:
    """Return (ai_managed_zones, compiled_stub_patterns)."""
    zones = ["wiki"]
    patterns_raw = DEFAULT_STUB_PATTERNS

    config_path = vault_root / ".claude" / "obsidian-knowledge.yaml"
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        zones = cfg.get("ai_managed", zones)
        patterns_raw = cfg.get("stub_link_patterns", patterns_raw)

    compiled = [re.compile(p) for p in patterns_raw]
    return zones, compiled


def is_stub(link: str, patterns: list[re.Pattern]) -> bool:
    if TEMPLATE_PLACEHOLDER.search(link):
        return True
    return any(p.search(link) for p in patterns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_root", type=Path, nargs="?", help="default: configured vault")
    vault_root = resolve_vault(parser.parse_args().vault_root)
    zones, patterns = load_config(vault_root)
    zone_prefixes = tuple(f"{z}/" for z in zones)

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    surviving = []
    for item in data:
        link = item.get("link", "")
        sources_str = item.get("sources", "")
        sources = [s.strip() for s in sources_str.split(",") if s.strip()]
        managed_sources = [s for s in sources if s.startswith(zone_prefixes)]

        if not managed_sources:
            continue
        if is_stub(link, patterns):
            continue

        count = item.get("count", str(len(managed_sources)))
        surviving.append((count, link, managed_sources))

    if not surviving:
        print(f"# No actionable unresolved links (filtered {len(data)} total)")
        return

    print(f"# {len(surviving)} actionable unresolved links (filtered from {len(data)} total)")
    for count, link, sources in surviving:
        print(f"{count}\t{link}\t{', '.join(sources)}")


if __name__ == "__main__":
    main()
