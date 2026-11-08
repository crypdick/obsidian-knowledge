"""One cancellable indexing worker, fed by file events and reconciliation."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import logging
import os
import time
from pathlib import Path

import httpx
from watchfiles import Change, awatch

from lib.vault_index.config import load_config
from lib.vault_index.dirty_paths import DirtyPaths
from lib.vault_index.embeddings import OllamaEmbeddingProvider
from lib.vault_index.index_generations import active_cache, prepare_generation, publish_generation
from lib.vault_index.index_policy import index_path, indexable
from lib.vault_index.indexer import Indexer, SyncStats, default_cache_dir
from lib.vault_index.models import IndexBusyError, Progress
from lib.vault_index.vault_listing import visible_name
from obsidian_knowledge_vendor.memweave.exceptions import MemWeaveError

logger = logging.getLogger(__name__)


def content_signature(path: Path) -> str:
    """Content identity, including deletion; never follow a symlink outside the vault."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "deleted"


def enqueue_paths(vault: Path, paths: list[str]) -> None:
    """Coalesce notifications without waiting for embeddings."""
    queue = DirtyPaths(default_cache_dir(vault) / "pending.sqlite")
    config = load_config()
    for relative in paths:
        path = index_path(vault, relative)
        if not path.resolve().is_relative_to(vault.resolve()):
            raise ValueError("index path escapes vault")
        if path.is_dir() or path.suffix != ".md":
            request_scan(vault)
        else:
            queue.mark(relative, content_signature(path) if indexable(vault, relative, config) else "deleted")


def request_scan(vault: Path, *, rebuild: bool = False) -> None:
    """Durably request reconciliation; overlapping requests coalesce."""
    queue = DirtyPaths(default_cache_dir(vault) / "pending.sqlite", quiet_seconds=0)
    queue.mark("@rebuild" if rebuild else "@scan", str(time.time_ns()))


def worker_running(vault: Path) -> bool:
    cache = default_cache_dir(vault)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def directory_event(change: Change, path: Path) -> bool:
    return path.is_dir() or (change == Change.deleted and not path.suffix)


class IndexWorker:
    """File events cancel obsolete work; scans repair missed notifications."""

    def __init__(self, vault: Path, *, quiet_seconds: float | int = 30, scan_seconds: float | int = 3600):
        self.vault = vault.resolve()
        self.cache = default_cache_dir(self.vault)
        self.queue = DirtyPaths(self.cache / "pending.sqlite", quiet_seconds=quiet_seconds)
        self.config = load_config()
        self.scan_seconds = scan_seconds
        self.active_path: str | None = None
        self.active_task: asyncio.Task[SyncStats] | None = None
        self.stats = SyncStats(0, 0, 0)
        self.wake = asyncio.Event()
        with (self.cache / ".worker.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            probe = Indexer(self.vault, self.cache, self.config, skip_probe=True)
            self.fingerprint = probe._embedder_fingerprint()
            self.building = probe.vector_issue is not None
            self.target = active_cache(self.cache)
            manifest = self.cache / "building-generation.json"
            if self.building or manifest.exists():
                self.prepare_rebuild()
        self.initial_scan = False

    def prepare_rebuild(self) -> bool:
        """Select the unpublished generation and require its missing work."""
        self.target, created = prepare_generation(self.cache, self.fingerprint)
        self.building = True
        if created:
            self.queue.invalidate()
        return created

    def observe(self, relative: str) -> None:
        try:
            path = index_path(self.vault, relative)
        except ValueError:
            return
        if path.suffix != ".md":
            return
        try:
            signature = content_signature(path) if indexable(self.vault, relative, self.config) else "deleted"
        except OSError:
            logger.exception("Cannot read note; later reconciliation will retry", extra={"path": relative})
            return
        self.queue.mark(relative, signature)
        self.wake.set()

    async def scan(self) -> None:
        """Discover current files and deletions without extending unchanged deadlines."""
        instance = Indexer(self.vault, self.cache, self.config, vector_enabled=False)
        paths = set(instance.indexed_paths())
        staged = set(Indexer(self.vault, self.target, self.config, vector_enabled=False).indexed_paths())
        paths.update(staged)
        for directory, folders, files in os.walk(self.vault):
            folders[:] = [
                name for name in folders if visible_name(name) and not (Path(directory) / name).is_symlink()
            ]
            paths.update(
                (Path(directory) / name).relative_to(self.vault).as_posix()
                for name in files
                if visible_name(name) and name.endswith(".md")
            )
        for relative in sorted(paths):
            self.observe(relative)
            if self.building and relative not in staged and (self.vault / relative).is_file():
                self.queue.require(relative)
            await asyncio.sleep(0)
        self.initial_scan = True

    async def watch(self) -> None:
        async for changes in awatch(self.vault, debounce=100, step=50):
            for _, name in changes:
                path = Path(name)
                if path.suffix == ".md":
                    self.observe(path.relative_to(self.vault).as_posix())
            # Directory moves/deletes can omit individual children. Reconcile
            # them through the same dirty set rather than launching another job.
            if any(directory_event(change, Path(name)) for change, name in changes):
                request_scan(self.vault)

    async def reconcile(self) -> None:
        while True:
            request_scan(self.vault)
            await asyncio.sleep(self.scan_seconds)

    async def maintain_embedder(self) -> None:
        """Cold model loading must not restart whenever a short query expires."""
        provider = Indexer(self.vault, self.target, self.config, skip_probe=True)._store.embedding_provider
        if not isinstance(provider, OllamaEmbeddingProvider):
            return
        while True:
            try:
                await provider.warm_up()
            except httpx.HTTPError:
                logger.exception("Embedding model warmup failed; retrying independently of searches")
                await asyncio.sleep(60)
            else:
                await asyncio.sleep(300)

    async def index_one(self, relative: str) -> SyncStats:
        instance = Indexer(self.vault, self.target, self.config)
        if not instance.vector_enabled:
            raise IndexBusyError(instance.vector_status)
        return await instance.index_settled_path(relative)

    async def process_next(self, *, retry_errors: bool = True) -> bool:
        selected = self.queue.ready()
        if selected is None:
            if self.building and self.initial_scan and self.queue.pending_count() == 0:
                publish_generation(self.cache, self.target)
                self.building = False
            return False
        relative, revision = selected
        if relative in {"@scan", "@rebuild"}:
            if relative == "@rebuild" and not self.building and self.prepare_rebuild():
                # invalidate also advances this request; complete its current revision below.
                revision += 1
            await self.scan()
            self.queue.complete(relative, revision)
            return True
        self.active_path = relative
        task = self.active_task = asyncio.create_task(self.index_one(relative))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.1)
                # Check contents even if the watcher misses or delays an event.
                self.observe(relative)
                if not self.queue.current(relative, revision):
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return True
            result = await task
            if result is not None:
                self.stats.indexed += result.indexed
                self.stats.skipped += result.skipped
                self.stats.deleted += result.deleted
            self.queue.complete(relative, revision)
        except (OSError, ValueError, MemWeaveError, IndexBusyError):
            logger.exception("Indexing deferred", extra={"path": relative})
            self.queue.retry(relative, revision)
            if not retry_errors:
                raise
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self.active_task = None
            self.active_path = None
        return True

    async def run(self) -> None:
        """Run until cancelled; one lifetime lock excludes a second worker."""
        with (self.cache / ".worker.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self.watch())
                tasks.create_task(self.reconcile())
                tasks.create_task(self.maintain_embedder())
                while True:
                    self.wake.clear()
                    if not await self.process_next():
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(self.wake.wait(), timeout=1)


def foreground_reindex(vault: Path, *, force: bool = False, progress: Progress | None = None) -> SyncStats:
    """Drain the same queue/generation lifecycle without starting a daemon.

    Unavailable embeddings retain the explicit keyword-only recovery path.
    Online failures leave durable work pending and surface immediately rather
    than retrying forever in a foreground command.
    """
    cache = default_cache_dir(vault)
    try:
        worker = IndexWorker(vault, quiet_seconds=0)
    except BlockingIOError as exc:
        raise IndexBusyError("another index worker is running") from exc
    with (cache / ".worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise IndexBusyError("another index worker is running") from exc
        probe = Indexer(vault, cache, worker.config)
        try:
            before = set(probe.indexed_paths())
            if not probe.vector_enabled:
                return probe.full_reindex(force=force, progress=progress)
        finally:
            asyncio.run(probe._store.close())

        async def drain() -> SyncStats:
            if force and not worker.building:
                worker.prepare_rebuild()
            await worker.scan()
            total = worker.queue.pending_count()
            done = 0
            if progress is not None:
                progress(0, total)
            while True:
                if await worker.process_next(retry_errors=False):
                    done += 1
                    if progress is not None:
                        progress(done, max(done, total))
                elif worker.queue.pending_count():
                    await asyncio.sleep(0.1)
                else:
                    break
            after = set(Indexer(vault, cache, worker.config, vector_enabled=False).indexed_paths())
            worker.stats.skipped = max(worker.stats.skipped, len(after) - worker.stats.indexed)
            worker.stats.deleted = max(worker.stats.deleted, len(before - after))
            return worker.stats

        return asyncio.run(drain())
