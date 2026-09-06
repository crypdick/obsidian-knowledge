"""Vault discovery from the global config.

Single source of truth for "what counts as a vault." Used by the
PreToolUse hook (`protect-vault.py`) and the Stop hooks. Replaces the
older walk-up-for-`.obsidian/` heuristic, which fired on any vault
the agent happened to `cd` into — including ones not in the user's
allowlist.

Config format (`~/.config/obsidian-knowledge/vaults.yaml`):

    vaults:
      - /path/to/your/vault
      - /path/to/another/vault
"""

import os
from pathlib import Path

from vault_registry import load_vault_roots as read_registry

CONFIG_PATH = Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"


def load_vault_roots(config_path: Path | None = None) -> list[str]:
    """Read the shared YAML registry; invalid or absent registries yield no roots."""
    path = config_path or Path(os.environ.get("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(CONFIG_PATH)))
    return read_registry(path)


def matching_vault_root(path: str, vault_roots: list[str] | None = None) -> str | None:
    """Return the configured vault root that contains `path`, or None if outside all.

    Lets callers anchor vault-relative paths (e.g. the changelog directory) to
    an absolute location instead of a cwd-relative one — which is what stops
    reminders from being ambiguously resolved into `wiki/Utility/...`.
    """
    if vault_roots is None:
        vault_roots = load_vault_roots()
    abs_path = os.path.abspath(os.path.expanduser(path))
    for root in vault_roots:
        if abs_path == root or abs_path.startswith(root + os.sep):
            return root
    return None


def is_in_vault(path: str, vault_roots: list[str] | None = None) -> bool:
    """Return True if `path` is inside any configured vault root."""
    return matching_vault_root(path, vault_roots) is not None
