"""Bounded discovery of visible vault directories and files."""

from __future__ import annotations

import stat
from collections.abc import Iterator
from fnmatch import fnmatchcase
from itertools import islice
from pathlib import Path

from pydantic import BaseModel


class ListingEntry(BaseModel):
    """One vault-relative directory or regular file."""

    path: str
    name: str
    is_directory: bool
    size_bytes: int | None


class ListingReport(BaseModel):
    """A bounded page and the next matching-entry offset, when available."""

    entries: list[ListingEntry]
    next_offset: int | None


def _visible_name(name: str) -> bool:
    return (
        not name.startswith(".")
        and name not in {"node_modules", "_sources"}
        and ".sync-conflict-" not in name
    )


def _entries(directory: Path, vault: Path, remaining_depth: int) -> Iterator[ListingEntry]:
    # Sorting retains one directory at a time; pagination never materializes the whole vault.
    for child in sorted(directory.iterdir()):
        if not _visible_name(child.name):
            continue
        info = child.lstat()
        is_directory = stat.S_ISDIR(info.st_mode)
        if not is_directory and not stat.S_ISREG(info.st_mode):
            continue
        yield ListingEntry(
            path=child.relative_to(vault).as_posix(),
            name=child.name,
            is_directory=is_directory,
            size_bytes=None if is_directory else info.st_size,
        )
        if is_directory and remaining_depth > 1:
            yield from _entries(child, vault, remaining_depth - 1)


def list_vault_files(
    vault_root: Path,
    relative_path: Path = Path("."),
    *,
    recursive: bool = False,
    depth: int = 3,
    pattern: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ListingReport:
    """List visible entries in deterministic depth-first order without following symlinks.

    Depth counts immediate children as level one; nonrecursive listings always use
    one level. Pattern uses case-sensitive ``fnmatch`` against paths relative to
    the requested directory: ``*`` also matches ``/``. Filtering never prunes
    directories. Offsets count matching entries; concurrent vault changes can
    shift pages.
    """
    # NOTE: docs/MCP.md documents these discovery bounds and exclusions.
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be nonnegative")
    if not 1 <= depth <= 10:
        raise ValueError("depth must be between 1 and 10")
    try:
        vault = vault_root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"vault does not exist: {vault_root}") from exc
    if not vault.is_dir():
        raise ValueError(f"vault is not a directory: {vault}")
    if relative_path.is_absolute():
        raise ValueError(f"path must be vault-relative: {relative_path}")
    if any(not _visible_name(part) for part in relative_path.parts):
        raise ValueError(f"not a visible vault path: {relative_path}")
    directory = vault
    for part in relative_path.parts:
        directory /= part
        if directory.is_symlink():
            raise ValueError(f"symlink path: {relative_path}")
    if not stat.S_ISDIR(directory.stat().st_mode):
        raise NotADirectoryError(f"not a vault directory: {relative_path}")
    candidates = _entries(directory, vault, depth if recursive else 1)
    matching = (
        entry
        for entry in candidates
        if pattern is None or fnmatchcase(Path(entry.path).relative_to(relative_path).as_posix(), pattern)
    )
    page = list(islice(matching, offset, offset + limit + 1))
    return ListingReport(
        entries=page[:limit],
        next_offset=offset + limit if len(page) > limit else None,
    )
