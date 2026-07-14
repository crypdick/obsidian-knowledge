#!/usr/bin/env python3
"""Keep the Codex packaged plugin in sync with the repo-root source of truth.

The repo is a dual-runtime plugin. Claude Code / Hermes read the source at the
repo root; Codex installs from ``plugins/obsidian-knowledge/`` (see
``.agents/plugins/marketplace.json``). That subtree is a copy of the root's
``commands/``, ``hooks/`` and ``skills/`` trees and drifts silently when the
root is edited but the copy is not. This script makes the copy a pure function
of the root so drift can't survive review.

The single intentional divergence is the hooks manifest filename: the root's
``hooks/codex-hooks.json`` is copied to ``hooks/hooks.json`` in the Codex tree
(the distinct names stop the hooks from double-firing across runtimes).

Usage:
    uv run python scripts/sync_codex_plugin.py          # write the copy
    uv run python scripts/sync_codex_plugin.py --check   # CI: fail on drift
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = REPO_ROOT / "plugins" / "obsidian-knowledge"

# Root subtrees mirrored verbatim into the Codex plugin.
SYNC_DIRS = ("commands", "hooks", "skills")

# Root-relative path -> Codex-relative path for the few files whose names differ.
RENAMES = {
    "hooks/codex-hooks.json": "hooks/hooks.json",
}

IGNORE_PARTS = {"__pycache__"}
IGNORE_SUFFIXES = {".pyc"}


def _is_ignored(path: Path) -> bool:
    return bool(IGNORE_PARTS.intersection(path.parts)) or path.suffix in IGNORE_SUFFIXES


def _expected_pairs() -> list[tuple[Path, Path]]:
    """(source, destination) for every file the Codex tree should contain."""
    pairs: list[tuple[Path, Path]] = []
    for sub in SYNC_DIRS:
        root_dir = REPO_ROOT / sub
        if not root_dir.is_dir():
            continue
        for src in sorted(root_dir.rglob("*")):
            if src.is_dir() or _is_ignored(src):
                continue
            rel = src.relative_to(REPO_ROOT).as_posix()
            dest_rel = RENAMES.get(rel, rel)
            pairs.append((src, CODEX_ROOT / dest_rel))
    return pairs


def _actual_files() -> set[Path]:
    """Files that currently live under the Codex sync dirs (ignoring caches)."""
    found: set[Path] = set()
    for sub in SYNC_DIRS:
        codex_dir = CODEX_ROOT / sub
        if not codex_dir.is_dir():
            continue
        for path in codex_dir.rglob("*"):
            if path.is_file() and not _is_ignored(path):
                found.add(path)
    return found


def _sync_manifest_version(check: bool) -> list[str]:
    """Keep the packaged manifest's release prefix aligned with the source.

    The packaged plugin intentionally carries a ``+codex.<timestamp>`` suffix to
    bust Codex's local plugin cache. Preserve that suffix here; the cachebuster
    script refreshes it after a source version bump.
    """
    source_manifest = REPO_ROOT / ".codex-plugin" / "plugin.json"
    packaged_manifest = CODEX_ROOT / ".codex-plugin" / "plugin.json"
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    packaged = json.loads(packaged_manifest.read_text(encoding="utf-8"))
    source_version = source["version"]
    packaged_version = packaged["version"]
    if not isinstance(source_version, str) or not isinstance(packaged_version, str):
        raise ValueError("Codex plugin manifests must contain string versions.")

    suffix = packaged_version.partition("+")[2]
    expected_version = f"{source_version}+{suffix}" if suffix else source_version
    if packaged_version == expected_version:
        return []

    drift = [f"  out of sync: {packaged_manifest.relative_to(REPO_ROOT)} version"]
    if not check:
        packaged["version"] = expected_version
        packaged_manifest.write_text(json.dumps(packaged, indent=2) + "\n", encoding="utf-8")
    return drift


def sync(check: bool) -> int:
    pairs = _expected_pairs()
    expected = {dest for _, dest in pairs}

    drift = _sync_manifest_version(check)
    for src, dest in pairs:
        if not dest.exists() or not filecmp.cmp(src, dest, shallow=False):
            drift.append(f"  out of sync: {dest.relative_to(REPO_ROOT)}")
            if not check:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    orphans = sorted(_actual_files() - expected)
    for path in orphans:
        drift.append(f"  orphaned (no root source): {path.relative_to(REPO_ROOT)}")
        if not check:
            path.unlink()

    if not drift:
        print("Codex plugin is in sync with the repo root.")
        return 0

    if check:
        print("Codex plugin has drifted from the repo root:", file=sys.stderr)
        print("\n".join(drift), file=sys.stderr)
        print(
            "\nRun `uv run python scripts/sync_codex_plugin.py` and commit the result.",
            file=sys.stderr,
        )
        return 1

    print("Synced Codex plugin from repo root:")
    print("\n".join(drift))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit non-zero without writing (for CI).",
    )
    args = parser.parse_args()
    sys.exit(sync(check=args.check))


if __name__ == "__main__":
    main()
