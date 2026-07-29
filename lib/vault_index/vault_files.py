"""Constrained, durable filesystem I/O for configured Obsidian vaults."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def resolve_vault_file(vault_root: Path, relative_path: Path) -> Path:
    """Resolve one vault-relative path without allowing namespace escape."""
    try:
        vault = vault_root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"vault does not exist: {vault_root}") from exc
    if not vault.is_dir():
        raise ValueError(f"vault is not a directory: {vault}")
    if relative_path.is_absolute():
        raise ValueError(f"path must be vault-relative: {relative_path}")

    target = (vault / relative_path).resolve()
    try:
        target.relative_to(vault)
    except ValueError as exc:
        raise ValueError(f"path resolves outside the vault: {relative_path}") from exc
    if target == vault:
        raise ValueError("path must name a file inside the vault")
    return target


def read_vault_file(vault_root: Path, relative_path: Path) -> bytes:
    """Read exact bytes from a confined vault path."""
    target = resolve_vault_file(vault_root, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"vault file does not exist: {relative_path}")
    return target.read_bytes()


def write_vault_file(
    vault_root: Path,
    relative_path: Path,
    content: bytes,
    *,
    replace: bool = False,
) -> Path:
    """Atomically write, fsync, and verify exact bytes at a confined vault path."""
    if not content.strip():
        raise ValueError("refusing to write empty vault content")

    target = resolve_vault_file(vault_root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = resolve_vault_file(vault_root, relative_path)
    if target.exists() and not replace:
        raise FileExistsError(f"vault file already exists; pass --replace to overwrite: {relative_path}")

    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temp.read_bytes() != content:
            raise OSError(f"temporary write verification failed: {relative_path}")

        if replace:
            os.replace(temp, target)
        else:
            os.link(temp, target)
            temp.unlink()

        directory_fd = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        if target.read_bytes() != content:
            raise OSError(f"final filesystem verification failed: {relative_path}")
        return target
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
