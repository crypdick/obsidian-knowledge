"""CLI entry points for obsidian-knowledge tooling."""
from __future__ import annotations

import argparse
import os
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
      - "^\\\\.stversions/"
      - "^\\\\.trash/"
      - "^Utility/obsidian-knowledge/cache/"

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
        try:
            existing = yaml.safe_load(yaml_path.read_text()) or {}
        except yaml.YAMLError as exc:
            print(f"error: malformed YAML in {yaml_path}: {exc}", file=sys.stderr)
            sys.exit(1)
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

    p_search = sub.add_parser("search", help="Hybrid (BM25+vector) search the vault index")
    p_search.add_argument("query", help="Free-text query")
    p_search.add_argument("--vault", type=Path, default=Path.cwd())
    p_search.add_argument("--top-k", type=int, default=None)
    p_search.add_argument(
        "--all",
        action="store_true",
        help="Override digest filter (include paths normally hidden from prefetch).",
    )

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
        import fcntl
        import memweave
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import Indexer, default_cache_dir

        cfg = load_config(args.vault / ".claude" / "obsidian-knowledge.yaml")
        cache = default_cache_dir(args.vault)
        cache.mkdir(parents=True, exist_ok=True)
        lock_path = cache / ".reindex.lock"
        with open(lock_path, "w") as lock_f:
            try:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(
                    "reindex: another reindex is in progress (lock held); exiting cleanly.",
                    file=sys.stderr,
                )
                return 0
            idx = Indexer(vault_root=args.vault, cache_dir=cache, config=cfg)
            stats = idx.full_reindex(force=args.force)
            print(
                f"Indexed: {stats.indexed}, Skipped: {stats.skipped}, Deleted: {stats.deleted}",
                flush=True,
            )
    elif args.cmd == "link-hermes-memories":
        link_hermes_memories(args.vault, args.hermes_memories_dir)
    elif args.cmd == "search":
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import Indexer, default_cache_dir

        cfg = load_config(args.vault / ".claude" / "obsidian-knowledge.yaml")
        cache = default_cache_dir(args.vault)
        idx = Indexer(vault_root=args.vault, cache_dir=cache, config=cfg)
        if not idx._vector_enabled:
            print(f"# vector lane off ({idx.vector_status}); FTS-only", file=sys.stderr)
        hits = idx.search(args.query, top_k=args.top_k, override_digest_filter=args.all)
        if not hits:
            print("(no results)")
            return 0
        for h in hits:
            print(f"{h.score:6.1f}  {h.path}")

    return 0


def _exit_hard(code: int) -> None:
    """Flush stdio then `os._exit` to skip Python's atexit/asyncio shutdown.

    memweave/litellm/aiohttp leave non-daemon threads or pending tasks alive
    after `idx.full_reindex()` and `idx.search()` finish, which makes the
    interpreter hang on shutdown — confirmed on mac mini (Apple Silicon
    Python 3.13) where the hourly cron piled up 7 zombie `reindex` processes
    overnight. Force-exit is the same workaround used in `hermes_plugin` for
    the asyncio-daemon-thread mismatch.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    _exit_hard(main())
