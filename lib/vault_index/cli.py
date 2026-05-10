"""CLI entry points for obsidian-knowledge tooling."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

DEFAULT_VAULT_INDEX_TEMPLATE = """
# Vault index config — drives memweave retrieval, filtering, and weighting.
# Path patterns are Python regexes evaluated against vault-relative paths.
vault_index:
  # What gets embedded at index time. Skipped paths are invisible to vault_search.
  index:
    allow_regex: []
    deny_regex:
      - "^Journal/"
      - "^Inbox/"
      - "^_sources/"
      - "^\\\\.obsidian/"
      - "^\\\\.config/"

  # What surfaces in default prefetch digest. Subset of indexed.
  digest:
    allow_regex:
      - "^wiki/"
      - "^.+/convos/"
    deny_regex: []

  # Score multipliers (longest-regex-match wins) applied before top-K truncation.
  weights:
    - regex: "^wiki/"
      multiplier: 1.5
    - regex: "^.+/convos/"
      multiplier: 1.3
    - regex: "^.+/changelog\\\\.md$"
      multiplier: 0.6

  default_weight: 1.0
  top_k: 5
  # min_score: null  # uncomment to set a hard cutoff
"""


def init_vault_index(yaml_path: Path) -> None:
    """Add a `vault_index:` section template to the per-vault config file.

    No-op if the section already exists. Preserves any other sections.
    """
    if yaml_path.exists():
        existing = yaml.safe_load(yaml_path.read_text()) or {}
        if "vault_index" in existing:
            print(f"vault_index section already present in {yaml_path}; not modified.")
            return
        with yaml_path.open("a") as f:
            f.write("\n" + DEFAULT_VAULT_INDEX_TEMPLATE)
    else:
        yaml_path.write_text(DEFAULT_VAULT_INDEX_TEMPLATE)
    print(f"Wrote vault_index template to {yaml_path}")


def link_hermes_memories(vault_root: Path, hermes_memories_dir: Path) -> None:
    """Symlink Hermes built-in MEMORY.md and USER.md into the vault.

    Symlinks live at <vault>/Utility/obsidian-knowledge/hermes/{MEMORY,USER}.md.
    Idempotent — overwrites existing symlinks.

    NOTE: Obsidian linter must be configured to skip this directory before
    symlinks go live, or the linter's frontmatter rewrites will corrupt the
    section-sign delimiter format Hermes uses. See:
      <vault>/.obsidian/plugins/obsidian-linter/data.json (excluded_paths)
    """
    if not hermes_memories_dir.exists():
        raise FileNotFoundError(f"Hermes memories dir not found: {hermes_memories_dir}")

    link_dir = vault_root / "Utility" / "obsidian-knowledge" / "hermes"
    link_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("MEMORY.md", "USER.md"):
        target = hermes_memories_dir / filename
        link = link_dir / filename
        if not target.exists():
            print(f"Source missing, skipping: {target}", file=sys.stderr)
            continue
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        print(f"Symlinked: {link} -> {target}")

    print(
        f"\nIMPORTANT: configure your Obsidian linter to exclude '{link_dir.relative_to(vault_root)}/' "
        "before opening these files in Obsidian. The linter would corrupt Hermes's "
        "section-sign delimiter format otherwise."
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="obsidian-knowledge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser(
        "init-vault-index",
        help="Add vault_index template to .claude/obsidian-knowledge.yaml",
    )
    p_init.add_argument("--vault", type=Path, default=Path.cwd(), help="Vault root (default: cwd)")

    p_reindex = sub.add_parser("reindex", help="Run a full re-index of the vault")
    p_reindex.add_argument("--vault", type=Path, default=Path.cwd())
    p_reindex.add_argument("--force", action="store_true")

    p_link = sub.add_parser(
        "link-hermes-memories",
        help="Symlink Hermes MEMORY.md/USER.md into the vault",
    )
    p_link.add_argument("--vault", type=Path, default=Path.cwd())
    p_link.add_argument(
        "--hermes-memories-dir",
        type=Path,
        default=Path.home() / ".hermes" / "memories",
    )

    args = parser.parse_args()

    if args.cmd == "init-vault-index":
        init_vault_index(args.vault / ".claude" / "obsidian-knowledge.yaml")
    elif args.cmd == "reindex":
        import asyncio
        import memweave
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import Indexer

        cfg = load_config(args.vault / ".claude" / "obsidian-knowledge.yaml")
        cache = args.vault / ".config" / "obsidian-knowledge" / "cache"
        idx = Indexer(vault_root=args.vault, cache_dir=cache, config=cfg)
        stats = idx.full_reindex(force=args.force)
        print(f"Indexed: {stats.indexed}, Skipped: {stats.skipped}, Deleted: {stats.deleted}", flush=True)
        # Close the store to release DB + watcher, then force-exit to avoid
        # LiteLLM background threads preventing clean process termination.
        asyncio.run(idx._store.close())
        import os
        os._exit(0)
    elif args.cmd == "link-hermes-memories":
        link_hermes_memories(args.vault, args.hermes_memories_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
