"""MCP index health, CLI index commands, and their result parsing."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lib.vault_index.cli import default_cache_dir_for_vault, search_ttl_seconds
from lib.vault_index.index_generations import active_cache
from lib.vault_index.index_state import rebuild_pending
from lib.vault_index.indexer import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_EMBEDDING_MODEL,
    FINGERPRINT_FILENAME,
)


class IndexStatus(BaseModel):
    index_exists: bool
    indexed_files: int | None
    vector_index_ready: bool = Field(
        description="Persisted vector index matches settings; endpoint not probed."
    )
    degraded_reason: str | None


class IndexUpdate(BaseModel):
    status: Literal["updated", "busy", "queued"]
    indexed: int | None = None
    skipped: int | None = None
    deleted: int | None = None


def read_index_status(vault: Path) -> IndexStatus:
    """Inspect persisted metadata without constructing Indexer or creating a cache.

    File freshness and embedding endpoint availability are unknown: this does
    not walk the vault, probe the network, or trigger index repair.
    """
    cache = active_cache(default_cache_dir_for_vault(vault))
    database = cache / "index.sqlite"
    if not database.is_file():
        return IndexStatus(
            index_exists=False, indexed_files=None, vector_index_ready=False, degraded_reason="index absent"
        )
    try:
        with contextlib.closing(
            sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True, timeout=1)
        ) as connection:
            row = connection.execute("SELECT count(*) FROM files").fetchone()
            indexed_files = int(row[0])
            vector_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_vec'"
            ).fetchone()
    except sqlite3.Error as exc:
        return IndexStatus(
            index_exists=True,
            indexed_files=None,
            vector_index_ready=False,
            degraded_reason=f"index unreadable: {exc}",
        )
    try:
        fingerprint = (cache / FINGERPRINT_FILENAME).read_text().strip()
    except (OSError, UnicodeError):
        fingerprint = None
    model = os.environ.get("MEMWEAVE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    current = f"{model}@{DEFAULT_CHUNK_TOKENS}/{DEFAULT_CHUNK_OVERLAP}"
    if rebuild_pending(database):
        reason = "vector index rebuild incomplete; update required"
    elif indexed_files == 0:
        reason = "index empty"
    elif fingerprint is None:
        reason = "embedding fingerprint unavailable"
    elif fingerprint == "keyword-only":
        reason = "index built in keyword-only mode"
    elif fingerprint != current:
        reason = "embedding settings changed; update required"
    elif vector_table is None:
        reason = "vector index unavailable"
    else:
        reason = None
    return IndexStatus(
        index_exists=True,
        indexed_files=indexed_files,
        vector_index_ready=reason is None,
        degraded_reason=reason,
    )


def parse_index_update(stdout: bytes, stderr: bytes) -> IndexUpdate:
    """Interpret successful reindex exits, including its clean lock-contention exit."""
    if b"reindex: another index operation is in progress (lock held); exiting cleanly." in stderr:
        return IndexUpdate(status="busy")
    match = re.fullmatch(rb"Indexed: ([0-9]+), Skipped: ([0-9]+), Deleted: ([0-9]+)\s*", stdout)
    if match is None:
        raise ValueError("unexpected reindex output")
    return IndexUpdate(status="updated", indexed=int(match[1]), skipped=int(match[2]), deleted=int(match[3]))


async def run_index_command(
    command: list[str], operation: str, *, deadline_seconds: int | float | None = None
) -> tuple[bytes, bytes]:
    """Run one CLI operation with a deadline and reap its process on cancellation."""
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=deadline_seconds if deadline_seconds is not None else search_ttl_seconds() + 10,
        )
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise ValueError(stderr.decode(errors="replace").strip() or f"vault {operation} failed")
    return stdout, stderr


async def refresh_index(vault: Path, rel_paths: list[str]) -> str:
    """Coalesce mutations for the worker; never embed inside a write request."""
    from lib.vault_index.index_worker import enqueue_paths

    try:
        await asyncio.to_thread(enqueue_paths, vault, rel_paths)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return f"deferred to next scan: {exc}"
    return "queued"
