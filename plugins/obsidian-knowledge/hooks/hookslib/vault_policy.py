"""Typed vault protection policy from the shared preferences file."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, field_validator
from vault_preferences import load_preferences


class VaultPolicy(BaseModel):
    """Optional protection rules; an absent rule has no enforcement cost."""

    # NOTE: docs/hooks.md documents nested read-only path semantics.
    ai_readonly_folders: tuple[str, ...] = ()
    ai_readonly_root_files: tuple[str, ...] = ()
    publish_allowlist: tuple[str, ...] = ()
    generic_filenames: tuple[str, ...] = ()
    illegal_filename_chars: tuple[str, ...] = ()

    @field_validator("ai_readonly_folders", "ai_readonly_root_files")
    @classmethod
    def readonly_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            path = PurePosixPath(value)
            if (
                path.is_absolute()
                or not path.parts
                or path.as_posix() != value
                or ".." in path.parts
                or "\\" in value
            ):
                raise ValueError(f"read-only entry must be a normalized vault-relative path: {value}")
        return values

    def readonly_relative(self, relative: str) -> bool:
        """Protect exact configured files and complete folder subtrees."""
        return relative in self.ai_readonly_root_files or any(
            relative == folder or relative.startswith(folder + "/") for folder in self.ai_readonly_folders
        )


def load_vault_policy() -> VaultPolicy:
    """Read shared rules independently of the host's vault locations."""
    return VaultPolicy.model_validate(load_preferences().root)
