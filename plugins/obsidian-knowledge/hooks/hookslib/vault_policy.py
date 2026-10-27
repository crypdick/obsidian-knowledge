"""Typed vault protection policy from the shared preferences file."""

from __future__ import annotations

import os

from pydantic import BaseModel
from vault_preferences import load_preferences


class VaultPolicy(BaseModel):
    """Optional protection rules; an absent rule has no enforcement cost."""

    ai_readonly_folders: tuple[str, ...] = ()
    ai_readonly_root_files: tuple[str, ...] = ()
    publish_allowlist: tuple[str, ...] = ()
    generic_filenames: tuple[str, ...] = ()
    illegal_filename_chars: tuple[str, ...] = ()


def load_vault_policy() -> VaultPolicy:
    """Read shared rules independently of the host's vault locations."""
    return VaultPolicy.model_validate(load_preferences().root)


def find_containing_vault(file_path: str, vault_roots: list[str]) -> str | None:
    """Return the vault root that contains `file_path`, or None."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    for root in vault_roots:
        if abs_path == root or abs_path.startswith(root + os.sep):
            return root
    return None
