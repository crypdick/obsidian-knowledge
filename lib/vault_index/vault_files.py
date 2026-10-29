"""Constrained, durable filesystem I/O for configured Obsidian vaults."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path

from lib.vault_index.note_creation import initialize_note


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


def read_vault_file(vault_root: Path, relative_path: Path, *, max_bytes: int | None = None) -> bytes:
    """Read exact bytes from a confined vault path."""
    target = resolve_vault_file(vault_root, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"vault file does not exist: {relative_path}")
    if max_bytes is None:
        return target.read_bytes()
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    with target.open("rb") as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"vault file exceeds {max_bytes} byte download limit: {relative_path}")
    return content


def write_vault_file(
    vault_root: Path,
    relative_path: Path,
    content: bytes,
    *,
    replace: bool = False,
    expected_content: bytes | None = None,
) -> Path:
    """Initialize new-note metadata, then atomically write, fsync, and verify bytes."""
    if not content.strip():
        raise ValueError("refusing to write empty vault content")

    target = resolve_vault_file(vault_root, relative_path)
    vault = vault_root.expanduser().resolve()
    # NOTE: Utility is a vault-root zone; see docs/configuration.md, Shared preferences and host locations.
    if target.relative_to(vault).parts[:2] == ("wiki", "Utility"):
        raise ValueError("Utility paths must be vault-relative: use Utility/... instead of wiki/Utility/...")
    if target.exists() and not replace:
        raise FileExistsError(f"vault file already exists; pass --replace to overwrite: {relative_path}")

    if not target.exists():
        content = initialize_note(vault, target.relative_to(vault), content)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = resolve_vault_file(vault_root, relative_path)

    original_stat = target.stat() if target.exists() else None
    mode = stat.S_IMODE(original_stat.st_mode) if original_stat is not None else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp = Path(temp_name)
    try:
        # NOTE: docs/MCP.md, vault_write: retain existing access ownership before publication.
        if original_stat is not None:
            os.fchown(fd, original_stat.st_uid, original_stat.st_gid)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temp.read_bytes() != content:
            raise OSError(f"temporary write verification failed: {relative_path}")

        # NOTE: detects edits before replacement, without an external-process atomic CAS.
        if expected_content is not None and target.read_bytes() != expected_content:
            raise ValueError(f"vault file changed since it was read: {relative_path}")
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


def append_vault_file(vault_root: Path, relative_path: Path, content: str, *, inline: bool = False) -> Path:
    """Append literal UTF-8 content to an existing file through the verified writer."""
    if not content:
        raise ValueError("append content must not be empty")
    baseline = read_vault_file(vault_root, relative_path)
    combined = baseline + (b"" if inline else b"\n") + content.encode("utf-8")
    return write_vault_file(vault_root, relative_path, combined, replace=True, expected_content=baseline)


def patch_vault_file(
    vault_root: Path,
    relative_path: Path,
    old_str: str,
    new_str: str,
    *,
    expected_sha256: str | None = None,
) -> Path:
    """Replace exactly one UTF-8 text match, preserving all other bytes."""
    if not old_str:
        raise ValueError("old_str must not be empty")
    baseline = read_vault_file(vault_root, relative_path)
    if expected_sha256 is not None and hashlib.sha256(baseline).hexdigest() != expected_sha256:
        raise ValueError(f"vault file SHA-256 does not match expected_sha256: {relative_path}")

    text = baseline.decode("utf-8")
    start = text.find(old_str)
    if start < 0 or text.find(old_str, start + 1) >= 0:
        raise ValueError("old_str must occur exactly once in the vault file")
    content = (text[:start] + new_str + text[start + len(old_str) :]).encode("utf-8")
    return write_vault_file(vault_root, relative_path, content, replace=True, expected_content=baseline)
