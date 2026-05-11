"""Harness primer text. Single source of truth for both CC and Hermes adapters."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_memory_target(cwd: str):
    """Lazy import; the resolver lives under hooks/ which isn't always on path."""
    plugin_root = Path(__file__).resolve().parent.parent.parent
    hooks_dir = plugin_root / "hooks"
    if str(hooks_dir) not in sys.path:
        sys.path.insert(0, str(hooks_dir))
    from hookslib.repo_memory import resolve_target  # noqa: WPS433
    return resolve_target(cwd)


def build_primer(
    vault_root: Path,
    plugin_root: Path,
    cwd: str | None = None,
) -> str:
    """Build the harness primer text injected into every session.

    Loaded into every session's context. Must stand alone — agents that
    read only this primer should know what to do.

    `cwd` (optional) lets the primer surface the *exact* per-repo or per-host
    memory directory the agent should write to. Defaults to os.getcwd().
    """
    wiki = vault_root / "wiki"
    target = _resolve_memory_target(cwd or os.getcwd())
    memory_dir = wiki / target.rel_path
    if target.kind == "repo":
        scope_desc = f"this repo ({target.owner}/{target.repo})"
    else:
        scope_desc = f"this host ({target.hostname}) — cwd is not in a git repo"
    return (
        "You are operating under the obsidian-knowledge harness.\n"
        f"- Knowledge: Obsidian wiki at {wiki}/ is the persistent memory store — "
        "search it before answering non-trivial questions with `/vault-search <query>` "
        "(hybrid BM25 + dense-embedding retrieval; ranked top-K paths). "
        f"Fall back to `rg <pattern> {wiki}/` only for exact-string lookups. "
        "File outcomes at session end (`remember-conversations` skill) and update the changelog. "
        "Do NOT use Claude's built-in MEMORY.md system; the wiki is the source of truth.\n"
        f"- Per-session agent memory ({scope_desc}) lives at "
        f"{memory_dir}/. Use the same MEMORY.md + per-fact .md file layout as "
        "Claude's native auto-memory, but stored in the vault so it's portable, "
        "syncs across hosts, and is searchable. Read MEMORY.md there at session "
        "start; append new feedback/project/reference facts there, not under "
        "~/.claude/projects/*/memory/ (a PreToolUse hook will block that).\n"
        "- Reflect on friction: if you struggle with the harness, hit unexpected "
        "blocks, or repeat the same workaround, invoke `/improve-harness`.\n"
        "- Reflect on user frustration: if the user expresses frustration "
        "('fuck', 'wtf', 'this keeps happening'), invoke `/improve-harness`. "
        "The agent is not the unit of analysis — the system is."
    )
