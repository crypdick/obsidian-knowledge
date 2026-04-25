#!/usr/bin/env python3
"""SessionStart hook: verify memory symlink + inject harness primer.

Runs at every session start. Two responsibilities:

1. Verify ~/.claude/projects/ is symlinked to <vault>/wiki/systems/repos/.
   On failure, emit a non-blocking warning directing the user to
   /setup-harness. (We never block sessions — broken symlink just means
   no vault-backed memory until the user runs the migration.)

2. Inject the harness primer (5 directives: memory location, recall via rg,
   capture via remember-conversations, friction reflection, user-frustration
   reflection) as the SessionStart systemMessage. The primer is the
   load-bearing context for the entire harness — must stand alone.

Multi-vault config not supported in v1.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import recall_init_lib  # noqa: E402
from lib import vault_config  # noqa: E402


def resolve_claude_projects() -> Path:
    """Path to ~/.claude/projects/, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CLAUDE_PROJECTS")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "projects"


def resolve_vaults_config() -> Path:
    """Path to vaults.yaml, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG")
    if override:
        return Path(override)
    return vault_config.CONFIG_PATH


def main() -> int:
    # Read stdin payload (we don't use it but Claude Code may send one)
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

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

    vault_root = Path(vault_roots[0])
    expected_target = vault_root / "wiki" / "systems" / "repos"
    claude_projects = resolve_claude_projects()

    verify = recall_init_lib.verify_symlink(claude_projects, expected_target)
    plugin_root = Path(__file__).resolve().parent.parent
    primer = recall_init_lib.build_primer(vault_root, plugin_root)

    if verify.ok:
        emit_message(primer)
    else:
        # Non-blocking warning + still inject primer so agent has guidance
        emit_message(f"WARNING: {verify.error}\n\n{primer}")

    return 0


def emit_message(message: str) -> None:
    """Emit a SessionStart systemMessage."""
    json.dump({"systemMessage": message}, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
