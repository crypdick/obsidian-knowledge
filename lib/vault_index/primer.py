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
    from hookslib.repo_memory import resolve_target

    return resolve_target(cwd)


KNOWLEDGE_BASE_INDEX_REL = Path("wiki/systems/knowledge-base/index.md")
KNOWLEDGE_BASE_INDEX_MAX_CHARS = 6000


def _read_capped(path: Path, limit: int) -> str:
    """Read a UTF-8 text file with a hard character cap for prompt safety."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text) <= limit:
        return text.strip()
    return text[:limit].rstrip() + "\n\n[truncated — open the vault note for the full index]"


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
    kb_index_path = vault_root / KNOWLEDGE_BASE_INDEX_REL
    kb_index = _read_capped(kb_index_path, KNOWLEDGE_BASE_INDEX_MAX_CHARS)
    kb_block = ""
    if kb_index:
        kb_block = (
            "\n\nKnowledge-base memory index "
            f"({KNOWLEDGE_BASE_INDEX_REL}, capped at {KNOWLEDGE_BASE_INDEX_MAX_CHARS} chars):\n"
            f"{kb_index}"
        )
    if target.kind == "repo":
        scope_desc = f"this repo ({target.owner}/{target.repo})"
    else:
        scope_desc = f"this host ({target.hostname}) — cwd is not in a git repo"
    return (
        "You are operating under the obsidian-knowledge harness.\n"
        f"- Knowledge: Obsidian wiki at {wiki}/ is the persistent memory store — "
        "search it before answering non-trivial questions with "
        '`obsidian-knowledge search "<query>"` '
        "(ranked top matching paths). "
        f"Fall back to `rg <pattern> {wiki}/` only for exact-string lookups. "
        "File outcomes at session end (`remember-conversations` skill) — this creates a terse changelog entry and any diary/convo notes. "
        "Do NOT use Hermes/Claude built-in MEMORY.md or USER.md systems; the wiki is the source of truth.\n"
        "- Hermes profile memory lives in `wiki/systems/knowledge-base/index.md` as a thin index with wikilinks to detail notes. "
        "Keep the index bounded; add or edit linked notes for durable facts instead of growing the index.\n"
        f"- Per-session agent memory ({scope_desc}) lives at "
        f"{memory_dir}/. Use the same MEMORY.md + per-fact .md file layout as "
        "Claude's native auto-memory, but stored in the vault so it's portable, "
        "syncs across hosts, and is searchable. Read MEMORY.md there at session "
        "start; append new feedback/project/reference facts there, not under "
        "~/.claude/projects/*/memory/ (a PreToolUse hook will block that).\n"
        "- Reflect on friction: if you struggle with the harness, hit unexpected "
        "blocks, or repeat the same workaround, log it immediately with "
        '`obsidian-knowledge papercut "what happened"`. This only records a '
        "durable report; continue the requested work rather than turning it into "
        "a side quest."
        f"{kb_block}"
    )
