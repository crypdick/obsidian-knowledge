#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0"]
# ///
"""SessionStart hook: inject harness primer.

Runs at every session start. Injects the harness primer as SessionStart
additionalContext so it becomes model context immediately.

Multi-vault config not supported.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookslib import vault_config
from hookslib.primer import build_primer
from hookslib.stop_hook import read_input, session_debounce


def resolve_vaults_config() -> Path:
    """Path to vaults.yaml, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG")
    if override:
        return Path(override)
    return vault_config.CONFIG_PATH


def run() -> int:
    payload = read_input()

    # Resolve vault config
    config_path = resolve_vaults_config()
    if not config_path.exists():
        # No vault configured at all — emit nothing; hook is a no-op
        return 0

    # Read vault roots directly (may need to override CONFIG_PATH via env)
    if config_path != vault_config.CONFIG_PATH:
        vault_config.CONFIG_PATH = config_path
    vault_roots = vault_config.load_vault_roots()

    if len(vault_roots) > 1:
        emit_message(
            "Multi-vault vaults.yaml not supported by obsidian-knowledge "
            "harness. Configure exactly one vault root."
        )
        return 0

    if not vault_roots:
        return 0

    # SessionStart fires on startup|resume|compact. Debounce so a rapid
    # re-fire (e.g. an auto-compaction loop) doesn't re-inject the primer
    # back to back for the same session.
    if session_debounce(payload, "recall-init"):
        return 0

    vault_root = Path(vault_roots[0])
    primer = build_primer(vault_root, cwd=os.getcwd())
    emit_message(primer)

    return 0


def main() -> int:
    """Optional context must not break host when input or storage is unavailable."""
    try:
        return run()
    except Exception:  # allow: exception-handling  (optional lifecycle hook boundary)
        return 0


def emit_message(message: str) -> None:
    """Emit SessionStart context in the shape Claude Code consumes."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    sys.exit(main())
