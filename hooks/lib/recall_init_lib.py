"""Helpers for the SessionStart recall-init hook.

Builds the harness primer injected into every session.
"""
from __future__ import annotations

from pathlib import Path


def build_primer(vault_root: Path, plugin_root: Path) -> str:
    """Build the harness primer text injected into every session.

    Loaded into every session's context. Must stand alone — agents that
    read only this primer should know what to do.
    """
    wiki = vault_root / "wiki"
    return (
        "You are operating under the obsidian-knowledge harness.\n"
        "- Memory: per-project memory lives at ~/.claude/projects/.\n"
        f"- Recall: before answering non-trivial questions, search the wiki: "
        f"`rg <pattern> {wiki}/`.\n"
        "- Capture: at session end, file conversation outcomes (use the "
        "`remember-conversations` skill) and update the changelog.\n"
        "- Reflect on friction: if you struggle with the harness, hit unexpected "
        "blocks, or repeat the same workaround, invoke `/improve-harness`.\n"
        "- Reflect on user frustration: if the user expresses frustration "
        "('fuck', 'wtf', 'this keeps happening'), invoke `/improve-harness`. "
        "The agent is not the unit of analysis — the system is."
    )
