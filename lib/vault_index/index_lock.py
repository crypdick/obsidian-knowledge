"""Shared-reader/exclusive-writer access to one vault index."""

from __future__ import annotations

import contextlib
import fcntl
from pathlib import Path

from lib.vault_index.models import IndexBusyError


@contextlib.contextmanager
def index_lock(cache_dir: Path, *, exclusive: bool, blocking: bool = False):
    """Hold the per-vault SQLite access lock.

    memweave uses one SQLite DB per vault cache. Reindex/sync are writers and
    must be exclusive; search is a reader and takes a shared lock so writers do
    not collide with an in-flight query. Scheduled indexing skips contention;
    CLI searches normally wait within their deadline; MCP searches request a
    nonblocking shared lock and report busy. See docs/MCP.md's search contract.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = cache_dir / ".index.sqlite.lock"
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        mode |= fcntl.LOCK_NB
    with open(lock_path, "w") as lock_f:
        try:
            fcntl.flock(lock_f.fileno(), mode)
        except BlockingIOError as exc:
            raise IndexBusyError(
                "vault index is busy: another operation holds the index lock; retry after it completes"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
