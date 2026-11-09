"""Daemon notifications, restart durability, and shutdown at public seams."""

import asyncio
import contextlib
import fcntl

import pytest
from watchfiles import Change

from lib.vault_index import cli
from lib.vault_index.index_generations import active_cache, prepare_generation, publish_generation
from lib.vault_index.index_worker import IndexWorker, enqueue_paths, request_scan, worker_running
from lib.vault_index.mcp_index import refresh_index


def test_watcher_coalesces_file_and_directory_events(tmp_path, monkeypatch):
    note = tmp_path / "note.md"
    note.write_text("orchid")
    folder = tmp_path / "folder"
    folder.mkdir()
    worker = IndexWorker(tmp_path, quiet_seconds=0)

    async def events(*args, **kwargs):
        yield {(Change.modified, str(note)), (Change.modified, str(tmp_path / "settings.json"))}
        yield {(Change.added, str(folder))}
        yield {(Change.deleted, str(tmp_path / "gone-folder"))}
        yield set()

    monkeypatch.setattr("lib.vault_index.index_worker.awatch", events)
    asyncio.run(worker.watch())
    assert worker.queue.current("note.md", 1)
    assert worker.queue.current("@scan", 2)
    assert worker.queue.pending_count() == 2


def test_notifications_reject_escapes_and_ignore_nonnotes(tmp_path):
    worker = IndexWorker(tmp_path)
    for relative in ["../secret.md", "/secret.md"]:
        with pytest.raises(ValueError):
            enqueue_paths(tmp_path, [relative])
        with pytest.raises(ValueError):
            worker.queue.mark(relative, "x")
    worker.observe("../secret.md")
    worker.observe("settings.json")
    assert worker.queue.pending_count() == 0


def test_notification_failure_does_not_fail_completed_write(tmp_path, monkeypatch, capsys):
    def unavailable(*args):
        raise OSError("queue unavailable")

    monkeypatch.setattr("lib.vault_index.index_worker.enqueue_paths", unavailable)
    cli.index_written_file(tmp_path, "note.md")
    assert "next scan will reconcile" in capsys.readouterr().err
    assert asyncio.run(refresh_index(tmp_path, ["note.md"])) == "deferred to next scan: queue unavailable"


def test_reindex_requests_coalesce_while_worker_holds_lock(tmp_path, monkeypatch, capsys):
    worker = IndexWorker(tmp_path)
    (tmp_path / "note.md").write_text("orchid")
    assert not worker_running(tmp_path)
    with (worker.cache / ".worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for extra in [[], ["--path", "note.md"], ["--force"]]:
            monkeypatch.setattr(
                "sys.argv", ["obsidian-knowledge", "reindex", "--vault", str(tmp_path), *extra]
            )
            assert cli.main() == 0
    assert capsys.readouterr().out.count("Queued index update") == 3
    assert worker.queue.pending_count() == 3


def test_worker_cli_dispatch(tmp_path, monkeypatch):
    seen = []

    async def run(self):
        seen.append((self.vault, self.queue.quiet_seconds, self.scan_seconds))

    monkeypatch.setattr(IndexWorker, "run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "obsidian-knowledge",
            "index-worker",
            "--vault",
            str(tmp_path),
            "--quiet-seconds",
            "7",
            "--scan-seconds",
            "11",
        ],
    )
    assert cli.main() == 0
    assert seen == [(tmp_path, 7, 11)]


def test_daemon_single_owner_and_clean_shutdown(tmp_path, monkeypatch):
    worker = IndexWorker(tmp_path, quiet_seconds=0, scan_seconds=0.1)

    async def no_events(*args, **kwargs):
        await asyncio.Future()
        yield set()

    monkeypatch.setattr("lib.vault_index.index_worker.awatch", no_events)

    async def exercise():
        scanned = asyncio.Event()
        scan = worker.scan

        async def observed_scan():
            await scan()
            scanned.set()

        monkeypatch.setattr(worker, "scan", observed_scan)
        task = asyncio.create_task(worker.run())
        try:
            await asyncio.wait_for(scanned.wait(), 5)
            assert worker_running(tmp_path)
            with pytest.raises(BlockingIOError):
                IndexWorker(tmp_path, quiet_seconds=0)
            await asyncio.sleep(1.1)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert not worker_running(tmp_path)

    asyncio.run(exercise())


def test_shutdown_cancels_active_job(tmp_path, monkeypatch):
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    (tmp_path / "note.md").write_text("orchid")
    worker.observe("note.md")

    async def exercise():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocked(relative):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        monkeypatch.setattr(worker, "index_one", blocked)
        task = asyncio.create_task(worker.process_next())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert worker.queue.pending_count() == 1

    asyncio.run(exercise())


def test_forced_rebuild_coalesces_and_publishes(tmp_path, fake_ollama, drain_index):
    (tmp_path / "note.md").write_text("orchid")
    asyncio.run(drain_index(tmp_path))
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    previous = active_cache(worker.cache)
    request_scan(tmp_path, rebuild=True)

    async def exercise():
        assert await worker.process_next()
        target = worker.target
        assert target != previous
        request_scan(tmp_path, rebuild=True)
        while await worker.process_next():
            pass
        assert worker.target == target
        assert active_cache(worker.cache) == target

    asyncio.run(exercise())


def test_generation_manifest_validation_and_resume(tmp_path):
    assert active_cache(tmp_path) is None
    target, created = prepare_generation(tmp_path, "model")
    assert created
    assert prepare_generation(tmp_path, "model") == (target, False)
    publish_generation(tmp_path, target)
    assert active_cache(tmp_path) == target
    with pytest.raises(ValueError):
        publish_generation(tmp_path, tmp_path / "bad")
    (tmp_path / "current-generation").write_text("../outside")
    with pytest.raises(ValueError):
        active_cache(tmp_path)


def test_missing_staged_file_is_requeued_after_restart(tmp_path, fake_ollama):
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    (tmp_path / "note.md").write_text("orchid")
    worker.observe("note.md")
    worker.queue.complete("note.md", 1)
    asyncio.run(worker.scan())
    assert worker.queue.ready() == ("note.md", 2)


def test_explicit_path_update_without_any_index_defers(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["obsidian-knowledge", "reindex", "--vault", str(tmp_path), "--path", "note.md"]
    )
    assert cli.main() == 3
    assert "index not built yet" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", ["success", "failure", "other-provider"])
def test_model_warmup_is_independent_of_queries(tmp_path, monkeypatch, outcome):
    import httpx

    from lib.vault_index.embeddings import OllamaEmbeddingProvider
    from obsidian_knowledge_vendor.memweave.embedding.provider import LiteLLMEmbeddingProvider

    worker = IndexWorker(tmp_path)
    called = []

    async def warm(self):
        called.append("warm")
        if outcome == "failure":
            raise httpx.ConnectError("offline")

    async def sleep(delay):
        called.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(OllamaEmbeddingProvider, "warm_up", warm)
    monkeypatch.setattr("lib.vault_index.index_worker.asyncio.sleep", sleep)
    if outcome == "other-provider":
        monkeypatch.setattr(
            "lib.vault_index.indexer.make_embedding_provider",
            lambda config, **kwargs: LiteLLMEmbeddingProvider(config),
        )
        asyncio.run(worker.maintain_embedder())
        assert called == []
    else:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(worker.maintain_embedder())
        assert called == ["warm", 60 if outcome == "failure" else 300]


def test_existing_unpublished_generation_is_reused_for_explicit_request(tmp_path, fake_ollama, drain_index):
    (tmp_path / "note.md").write_text("orchid")
    asyncio.run(drain_index(tmp_path))
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    target, _ = prepare_generation(worker.cache, worker.fingerprint)
    request_scan(tmp_path, rebuild=True)
    assert asyncio.run(worker.process_next())
    assert worker.target == target
    assert worker.building


def test_directory_notification_requests_reconciliation(tmp_path):
    (tmp_path / "folder").mkdir()
    worker = IndexWorker(tmp_path)
    enqueue_paths(tmp_path, ["folder"])
    assert worker.queue.ready() == ("@scan", 1)


def test_unreadable_note_does_not_stop_scan(tmp_path, monkeypatch, caplog):
    worker = IndexWorker(tmp_path)
    (tmp_path / "note.md").write_text("orchid")

    def unreadable(path):
        raise PermissionError("read denied")

    monkeypatch.setattr("lib.vault_index.index_worker.content_signature", unreadable)
    asyncio.run(worker.scan())
    assert worker.initial_scan
    assert "later reconciliation will retry" in caplog.text


def test_corrupt_rebuild_manifest_is_rejected(tmp_path):
    (tmp_path / "building-generation.json").write_text('{"name": "../escape", "fingerprint": "model"}')
    with pytest.raises(ValueError):
        prepare_generation(tmp_path, "model")
