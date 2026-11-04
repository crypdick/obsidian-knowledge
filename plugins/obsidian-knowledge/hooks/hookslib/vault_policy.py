"""Typed vault protection policy from the shared preferences file."""

from __future__ import annotations

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
