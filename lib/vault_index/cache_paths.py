"""One cache identity for writers, readers, and status inspection."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import platformdirs

APP_NAME = "obsidian-knowledge"
CACHE_ROOT_ENV = "OBSIDIAN_KNOWLEDGE_CACHE_ROOT"
SANDBOX_CACHE_ROOT = Path("/tmp/obsidian-knowledge-cache")


def default_cache_dir(vault_root: Path) -> Path:
    """Select the root without creating state; concrete generations never relocate."""
    override = os.environ.get(CACHE_ROOT_ENV)
    if override:
        base = Path(override).expanduser() / APP_NAME
    else:
        base = Path(platformdirs.user_cache_dir(APP_NAME))
        existing = base
        while not existing.exists():
            existing = existing.parent
        if not os.access(existing, os.W_OK):
            base = SANDBOX_CACHE_ROOT / APP_NAME
    resolved = vault_root.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "-", resolved.name) or "vault"
    return base / f"{safe_name}-{digest}"
