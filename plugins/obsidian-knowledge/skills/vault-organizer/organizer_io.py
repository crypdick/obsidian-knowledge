"""Shared path guards and verified writes for reviewed gardener repairs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class OrganizerPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    ai_managed: tuple[str, ...] = ("wiki",)
    ai_readonly_folders: tuple[str, ...] = ()
    ai_readonly_root_files: tuple[str, ...] = ()

    @classmethod
    def load(cls, vault_root: Path) -> OrganizerPolicy:
        config = vault_root / ".claude" / "obsidian-knowledge.yaml"
        return cls.model_validate(yaml.safe_load(config.read_text()) or {}) if config.exists() else cls()

    def writable(self, vault_root: Path, relative: str) -> Path:
        path = visible_path(vault_root, relative)
        if "_sources" in Path(relative).parts:
            raise ValueError(f"protected source: {relative}")
        if relative in self.ai_readonly_root_files or any(
            within(relative, folder) for folder in self.ai_readonly_folders
        ):
            raise ValueError(f"read-only path: {relative}")
        # Reports are derivative state, including when Utility is not ai_managed.
        if relative != "Utility/obsidian-knowledge/reports/open-questions.md" and not any(
            within(relative, zone) for zone in self.ai_managed
        ):
            raise ValueError(f"outside managed zones: {relative}")
        return path


def within(relative: str, folder: str) -> bool:
    return relative == folder.rstrip("/") or relative.startswith(folder.rstrip("/") + "/")


def visible_path(vault_root: Path, relative: str) -> Path:
    """Reject traversal, hidden/dependency paths and symlinks before reading."""
    rel = Path(relative)
    if (
        rel.is_absolute()
        or not rel.parts
        or rel.as_posix() != relative
        or any(part.startswith(".") or part == "node_modules" for part in rel.parts)
        or ".sync-conflict-" in relative
    ):
        raise ValueError(f"not a visible vault path: {relative}")
    path = vault_root / rel
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != vault_root.parent):
        raise ValueError(f"symlink path: {relative}")
    path.resolve().relative_to(vault_root.resolve())
    return path


def write_checked(vault_root: Path, relative: str, before: str | None, after: str) -> None:
    """Refuse changed baselines; delegate durable writes to the installed CLI."""
    path = OrganizerPolicy.load(vault_root).writable(vault_root, relative)
    current = path.read_bytes().decode("utf-8") if path.exists() else None
    if current != before:
        raise ValueError(f"file changed since review: {relative}")
    command = ["obsidian-knowledge", "write", "--vault", str(vault_root)]
    if before is not None:
        command.append("--replace")
    result = subprocess.run([*command, relative], input=after, text=True, capture_output=True, check=True)
    if "Wrote and verified:" not in result.stdout or path.read_bytes() != after.encode("utf-8"):
        raise OSError(f"write verification failed: {relative}")
