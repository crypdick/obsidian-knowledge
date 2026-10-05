"""Configured scan boundaries and verified writes for gardener repairs."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import yaml
from hookslib.patterns import parse_frontmatter
from pydantic import BaseModel, ConfigDict, field_validator

from gardener.models import DEFAULT_STUB_PATTERNS
from lib.vault_index.cli import resolve_vault as resolve_cli_vault
from lib.vault_index.vault_files import write_vault_file

# NOTE: skills/vault-organizer/SKILL.md, Question report, documents this state path.
REPORT_PATH = "Utility/obsidian-knowledge/reports/open-questions.md"


def resolve_vault(explicit: Path | None = None) -> Path:
    """Use the CLI's default selection and validate the gardener's root."""
    if explicit is None:
        explicit = resolve_cli_vault(None)
    root = explicit.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"not a vault directory: {root}")
    return root


class OrganizerPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    ai_managed: tuple[str, ...] = ("wiki",)
    ai_readonly_folders: tuple[str, ...] = ()
    ai_readonly_root_files: tuple[str, ...] = ()
    stub_link_patterns: tuple[str, ...] = tuple(DEFAULT_STUB_PATTERNS)

    @field_validator("ai_managed", "ai_readonly_folders", "ai_readonly_root_files")
    @classmethod
    def relative_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            validate_relative(value)
        return values

    @classmethod
    def load(cls, vault_root: Path) -> OrganizerPolicy:
        config = vault_root / ".claude" / "obsidian-knowledge.yaml"
        return cls.model_validate(yaml.safe_load(config.read_text()) or {}) if config.exists() else cls()

    def writable(self, vault_root: Path, relative: str) -> Path:
        path = visible_path(vault_root, relative)
        if relative in self.ai_readonly_root_files or any(
            within(relative, folder) for folder in self.ai_readonly_folders
        ):
            raise ValueError(f"read-only path: {relative}")
        if relative != REPORT_PATH and not any(within(relative, zone) for zone in self.ai_managed):
            raise ValueError(f"outside managed zones: {relative}")
        return path


def within(relative: str, folder: str) -> bool:
    return relative == folder or relative.startswith(folder + "/")


def validate_relative(relative: str) -> Path:
    rel = Path(relative)
    if (
        rel.is_absolute()
        or not rel.parts
        or rel.as_posix() != relative
        or any(part.startswith(".") or part in {"node_modules", "_sources"} for part in rel.parts)
        or ".sync-conflict-" in relative
    ):
        raise ValueError(f"not a visible vault path: {relative}")
    return rel


def visible_path(vault_root: Path, relative: str) -> Path:
    """Reject traversal, protected paths and symlinks before reading."""
    rel = validate_relative(relative)
    path = vault_root / rel
    current = vault_root
    for part in rel.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"symlink path: {relative}")
    path.resolve().relative_to(vault_root.resolve())
    return path


def iter_paths(vault_root: Path, zone: str | None = None) -> Iterator[Path]:
    """Walk visible paths without descending into excluded or symlink folders."""
    root = visible_path(vault_root, zone) if zone is not None else vault_root
    if not root.is_dir():
        return
    if zone is not None:
        yield root
    for directory, folders, files in os.walk(root):
        parent = Path(directory)
        retained = []
        for name in sorted(folders):
            path = parent / name
            try:
                visible_path(vault_root, path.relative_to(vault_root).as_posix())
            except ValueError:
                continue
            retained.append(name)
            yield path
        folders[:] = retained
        for name in sorted(files):
            path = parent / name
            try:
                visible_path(vault_root, path.relative_to(vault_root).as_posix())
            except ValueError:
                continue
            yield path


def iter_markdown(vault_root: Path, zone: str | None = None) -> Iterator[Path]:
    for path in iter_paths(vault_root, zone):
        if path.is_file() and path.suffix == ".md":
            yield path


def write_checked(vault_root: Path, relative: str, before: str | None, after: str) -> None:
    """Refuse changed baselines; use the CLI's durable, verified writer."""
    path = OrganizerPolicy.load(vault_root).writable(vault_root, relative)
    current = path.read_bytes().decode("utf-8") if path.exists() else None
    if current != before:
        raise ValueError(f"file changed since review: {relative}")
    metadata, error = parse_frontmatter(current or "")
    if error:
        raise ValueError(f"cannot safely rewrite malformed frontmatter: {relative}")
    if metadata and metadata.get("dg-publish") is True:
        raise ValueError(f"published note requires human consent: {relative}")
    write_vault_file(vault_root, Path(relative), after.encode("utf-8"), replace=before is not None)
