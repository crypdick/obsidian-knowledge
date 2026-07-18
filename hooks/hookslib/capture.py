"""Selective durable-knowledge capture policy shared by Stop-hook adapters."""

from __future__ import annotations

import hashlib
import os

from .stop_hook import capture_debounce, emit_block, read_input
from .vault_config import load_vault_roots, matching_vault_root


def capture_session_key(session_id: object) -> str | None:
    """Return a stable opaque key for same-session changelog reuse."""
    if not session_id:
        return None
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:10]


def resolve_capture_vault(cwd: str) -> str | None:
    """Resolve an unambiguous configured vault for a capture decision.

    Capture normally runs from a code repository outside the vault. Prefer the
    containing configured vault when cwd is inside one; otherwise use the sole
    configured vault. Multiple configured vaults require cwd containment so the
    hook never guesses a write destination.
    """
    vault_roots = load_vault_roots()
    containing = matching_vault_root(cwd, vault_roots)
    if containing is not None:
        return containing
    if len(vault_roots) == 1:
        return vault_roots[0]
    return None


def build_reason(vault_root: str, session_key: str | None = None) -> str:
    """Return the single end-of-session capture decision prompt."""
    changelog_dir = os.path.join(vault_root, "Utility", "obsidian-knowledge", "changelog")
    if session_key:
        changelog_reuse = (
            f" The capture key is `{session_key}`: search {changelog_dir}/ for "
            f"`*-session-{session_key}.md`, reuse it if present, and otherwise end the new "
            f"fragment filename with `-session-{session_key}.md`."
        )
    else:
        changelog_reuse = (
            " Search current-day fragments for the canonical note wikilink and reuse a matching "
            "same-session fragment before creating one."
        )
    return (
        "Before stopping, make one capture decision for this session. Default: file nothing. "
        "File only when the session produced a durable, novel delta that will change a future "
        "decision or prevent repeated work, is not already captured, and is not cheaply "
        "recoverable from code, git, an issue, operational logs, or an existing vault note. "
        "Qualifying examples: an explicit request to preserve something; a durable user "
        "preference or decision; a verified reusable procedure; an evidence-backed, non-obvious "
        "failure mode and recovery; or a sourced synthesis. Skip routine edits, commits, releases, "
        "test or deployment progress, transient status/PIDs/job IDs/worktrees, quick factual or "
        "generic educational answers, acknowledgements, generated/raw output, and duplicated facts. "
        "Search the vault first and state the one-sentence durable delta missing from the canonical "
        "note. If you cannot state it, do not file. When a delta qualifies, use the "
        "remember-conversations skill, prefer updating the existing canonical note, and create at "
        "most one durable wiki note unless the user explicitly requested more or two topics are "
        "independently reusable. Quote user wording only when it carries a constraint, preference, "
        "or decision rationale; source and date volatile or high-stakes claims. Only if this capture "
        "changed durable vault content, create or reuse one same-session terse changelog fragment in "
        f"{changelog_dir}/; do not log code, git, or host changes by themselves, and do not edit a "
        f"shared changelog index.{changelog_reuse} If no qualifying delta exists or it was already "
        "filed, stop without writing anything."
    )


def main() -> int:
    """Emit one capture decision per user-message generation in a configured vault."""
    payload = read_input()
    vault_root = resolve_capture_vault(os.getcwd())
    if vault_root is None:
        return 0
    if capture_debounce(payload):
        return 0
    emit_block(build_reason(vault_root, capture_session_key(payload.get("session_id"))))
    return 0
