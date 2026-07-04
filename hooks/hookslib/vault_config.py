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
import re
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"


def load_vault_roots() -> list[str]:
    """Return absolute paths of all configured vault roots. [] if config absent."""
    if not CONFIG_PATH.exists():
        return []
    try:
        text = CONFIG_PATH.read_text()
    except OSError:
        return []
    roots: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+(.+)$", line)
        if not m:
            continue
        p = m.group(1).strip().strip("'\"")
        if p and not p.startswith("#"):
            roots.append(os.path.abspath(os.path.expanduser(p)))
    return roots


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
