#!/usr/bin/env python3
"""One-shot migration: ~/.claude/projects/<slug>/memory/ → vault.

For each Claude-Code per-project memory dir:
  1. Reverse the slug to the original absolute cwd path (greedy longest-prefix
     descent — handles `blue-team` etc. with internal dashes).
  2. Resolve the vault-relative memory target via hookslib.repo_memory.
  3. Move every file that the wiki-policy hook would block (feedback_/project_/
     reference_ AND any non-MEMORY .md the user filed there) into the vault.
  4. Rewrite MEMORY.md in place as a pointer to the vault location.

Idempotent: re-running skips files already present at the target.

Usage:
    uv run python scripts/migrate_claude_memory.py            # dry-run
    uv run python scripts/migrate_claude_memory.py --apply    # do it
"""
from __future__ import annotations

import argparse
import shutil
import socket
import sys
from pathlib import Path

# Add hooks/ to path so we can import the resolver.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "hooks"))

from hookslib.repo_memory import resolve_target  # noqa: E402
from hookslib.vault_config import load_vault_roots  # noqa: E402

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def slug_to_path(slug: str) -> Path | None:
    """Reverse `-home-ricardo-src-PERSONAL-blue-team` → /home/ricardo/src/PERSONAL/blue-team.

    Uses greedy longest-prefix descent: at each level, picks the longest
    `-`-joined prefix that exists as an actual directory. Falls back to None
    if no match (orphaned slug, dir deleted, etc.).
    """
    if not slug.startswith("-"):
        return None
    remaining = slug[1:]  # drop leading '-'
    current = Path("/")
    while remaining:
        parts = remaining.split("-")
        # Try longest joined prefix first.
        found = None
        for end in range(len(parts), 0, -1):
            candidate = "-".join(parts[:end])
            if (current / candidate).is_dir():
                found = (candidate, end)
                break
        if not found:
            return None
        candidate, end = found
        current = current / candidate
        remaining = "-".join(parts[end:])
    return current


VAULT_ROOT_MARKERS = ("obisidian", "obsidian", "vault")


def rescue_orphan_to_vault_subdir(slug: str, vault: Path) -> Path | None:
    """When the abs-path no longer exists, try to recover the slug as a
    *vault-relative* path. Many old slugs were Claude sessions started inside
    a now-moved vault subfolder — the suffix after the vault marker still
    matches a real `wiki/` subdir.

    Strategy: walk back from the end of the slug looking for the longest
    suffix that exists as `wiki/<suffix-with-/-instead-of--->/`. Greedy
    longest-suffix match.
    """
    if not slug.startswith("-"):
        return None
    parts = slug[1:].split("-")
    # Find the rightmost segment matching a vault root marker; suffix starts there + 1.
    last_marker = -1
    for i, p in enumerate(parts):
        if p.lower() in VAULT_ROOT_MARKERS:
            last_marker = i
    if last_marker == -1:
        return None
    suffix_parts = parts[last_marker + 1 :]
    if not suffix_parts:
        return None
    # Greedy descent under <vault>/wiki/
    current = vault / "wiki"
    remaining = "-".join(suffix_parts)
    while remaining:
        seg_parts = remaining.split("-")
        found = None
        for end in range(len(seg_parts), 0, -1):
            candidate = "-".join(seg_parts[:end])
            if (current / candidate).is_dir():
                found = (candidate, end)
                break
        if not found:
            return None
        candidate, end = found
        current = current / candidate
        remaining = "-".join(seg_parts[end:])
    return current


def migratable_files(memory_dir: Path) -> list[Path]:
    """Files in `memory_dir` that should move (everything except MEMORY.md)."""
    out: list[Path] = []
    for p in sorted(memory_dir.iterdir()):
        if not p.is_file() or p.suffix != ".md":
            continue
        if p.name == "MEMORY.md":
            continue
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually move files (default: dry-run).",
    )
    args = ap.parse_args()

    vault_roots = load_vault_roots()
    if not vault_roots:
        print("ERROR: no vault configured in ~/.config/obsidian-knowledge/vaults.yaml")
        return 2
    if len(vault_roots) > 1:
        print(f"ERROR: multi-vault not supported; got {vault_roots}")
        return 2
    vault = Path(vault_roots[0])

    host = socket.gethostname().split(".")[0].lower()
    total_moved = 0
    total_skipped = 0
    total_orphan = 0

    for proj_dir in sorted(CLAUDE_PROJECTS.iterdir()):
        memory_dir = proj_dir / "memory"
        if not memory_dir.is_dir():
            continue
        files = migratable_files(memory_dir)
        if not files:
            continue

        cwd = slug_to_path(proj_dir.name)
        scope: str
        if cwd is None:
            # Orphan — original abs path is gone. Try to recover as a vault subdir.
            rescue = rescue_orphan_to_vault_subdir(proj_dir.name, vault)
            if rescue is None:
                print(f"\n[ORPHAN] {proj_dir.name} — no matching abs path; skipping ({len(files)} file(s))")
                total_orphan += len(files)
                continue
            target_dir = rescue / "memory"
            scope = f"orphan-rescue:{rescue.relative_to(vault / 'wiki')}"
            print(f"\n[ORPHAN→VAULT] slug {proj_dir.name}")
            print(f"  → {target_dir}  ({scope})")
        else:
            target = resolve_target(cwd, hostname=host)
            target_dir = vault / "wiki" / target.rel_path
            scope = (
                f"{target.owner}/{target.repo}"
                if target.kind == "repo"
                else f"host:{target.hostname}"
            )
            print(f"\n[{target.kind.upper()}] {cwd}")
            print(f"  → {target_dir}  ({scope})")

        if not args.apply:
            for f in files:
                exists = (target_dir / f.name).exists()
                marker = "SKIP (exists)" if exists else "MOVE"
                print(f"    {marker}: {f.name}")
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        moved_here: list[str] = []
        for f in files:
            dst = target_dir / f.name
            if dst.exists():
                print(f"    SKIP (exists): {f.name}")
                total_skipped += 1
                continue
            shutil.move(str(f), str(dst))
            print(f"    MOVED: {f.name}")
            moved_here.append(f.name)
            total_moved += 1

        # Rewrite MEMORY.md as a pointer.
        memory_index = memory_dir / "MEMORY.md"
        pointer_text = (
            f"<!-- migrated by scripts/migrate_claude_memory.py -->\n"
            f"# Memory moved to Obsidian vault\n\n"
            f"This project's agent memory lives at:\n\n"
            f"  {target_dir}/\n\n"
            f"Scope: {scope}. Read MEMORY.md there.\n"
        )
        # Preserve original index content if any was there (append it below the pointer).
        original = ""
        if memory_index.exists():
            try:
                original = memory_index.read_text()
            except OSError:
                original = ""
        memory_index.write_text(
            pointer_text + ("\n---\n# Pre-migration index\n\n" + original if original.strip() else "")
        )

    print(f"\n--- summary ---")
    print(f"  files moved:   {total_moved}")
    print(f"  files skipped: {total_skipped}")
    print(f"  orphan files:  {total_orphan}")
    if not args.apply:
        print("  (dry-run; pass --apply to execute)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
