"""Helpers for the SessionStart recall-init hook.

Verifies that ~/.claude/projects/ is symlinked to the vault repos dir,
and builds the harness primer that gets injected into every session.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    ok: bool
    error: str | None = None


def verify_symlink(claude_projects: Path, expected_target: Path) -> VerifyResult:
    """Check that claude_projects is a symlink pointing to expected_target."""
    if not claude_projects.is_symlink():
        return VerifyResult(
            ok=False,
            error="Memory symlink not configured. Run /setup-harness to migrate.",
        )
    actual = claude_projects.resolve()
    if actual != expected_target.resolve():
        return VerifyResult(
            ok=False,
            error=(
                f"Memory symlink not configured correctly: points to {actual}, "
                f"expected {expected_target}. Run /setup-harness to fix."
            ),
        )
    return VerifyResult(ok=True)


def build_primer(vault_root: Path, plugin_root: Path) -> str:
    """Build the harness primer text injected into every session.

    Loaded into every session's context. Must stand alone — agents that
    read only this primer should know what to do.
    """
    wiki = vault_root / "wiki"
    return (
        "You are operating under the obsidian-knowledge harness.\n"
        f"- Memory: per-project memory lives at {vault_root}/wiki/systems/repos/. "
        f"~/.claude/projects/ is symlinked there.\n"
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
