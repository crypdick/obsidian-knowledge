"""The worker cancels busy files and advances quiet work without losing edits."""

import asyncio

from lib.vault_index.index_generations import active_cache
from lib.vault_index.index_worker import IndexWorker
from lib.vault_index.indexer import SyncStats


def test_edit_cancels_active_file_then_indexes_quiet_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    active = tmp_path / "active.md"
    quiet = tmp_path / "quiet.md"
    active.write_text("first")
    quiet.write_text("quiet")
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    worker.observe("active.md")
    worker.observe("quiet.md")
    completed = []
    cancelled = []

    async def exercise():
        started = asyncio.Event()

        async def index(relative):
            if relative == "active.md":
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.append(relative)
            else:
                completed.append(relative)
                return SyncStats(1, 0, 0)

        monkeypatch.setattr(worker, "index_one", index)
        operation = asyncio.create_task(worker.process_next())
        await started.wait()
        worker.queue.quiet_seconds = 30
        active.write_text("second")
        worker.observe("active.md")
        await operation
        assert cancelled == ["active.md"]
        assert await worker.process_next()
        assert completed == ["quiet.md"]
        assert not await worker.process_next()
        assert worker.queue.current("active.md", 2)

    asyncio.run(exercise())


def test_worker_commits_changes_and_deletions(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.indexer import Indexer

    path = tmp_path / "note.md"
    path.write_text("orchid greenhouse")
    worker = IndexWorker(tmp_path, quiet_seconds=0)

    async def exercise():
        await worker.scan()
        assert await worker.process_next()
        assert not await worker.process_next()
        path.unlink()
        await worker.scan()
        assert await worker.process_next()

    asyncio.run(exercise())
    instance = Indexer(tmp_path, active_cache(worker.cache), VaultIndexConfig(), vector_enabled=False)
    assert instance.search("orchid") == []


def test_model_rebuild_serves_old_index_until_publish(tmp_path, monkeypatch, fake_ollama, drain_index):
    from lib.vault_index.config import VaultIndexConfig
    from lib.vault_index.index_generations import active_cache
    from lib.vault_index.indexer import Indexer

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    note = tmp_path / "note.md"
    note.write_text("orchid original")
    asyncio.run(drain_index(tmp_path))
    first = IndexWorker(tmp_path, quiet_seconds=0)
    previous = active_cache(first.cache)
    fake_ollama.models = ("other-model:latest",)
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_MODEL", "ollama/other-model")
    note.write_text("tulip replacement")
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    assert worker.target != previous

    async def exercise():
        await worker.scan()
        assert await worker.process_next()
        # Work has committed only into the unpublished generation.
        assert active_cache(worker.cache) == previous

    asyncio.run(exercise())
    old = Indexer(tmp_path, active_cache(worker.cache), VaultIndexConfig(), vector_enabled=False)
    assert old.search("orchid")[0].path == "note.md"
    assert old.search("tulip") == []
    asyncio.run(worker.process_next())
    assert active_cache(worker.cache) == worker.target
    new = Indexer(tmp_path, active_cache(worker.cache), VaultIndexConfig(), vector_enabled=False)
    assert new.search("tulip")[0].path == "note.md"
    # An existing reader keeps its selected generation after publication.
    assert old.search("orchid")[0].path == "note.md"


def test_restart_resumes_pending_generation(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    worker.observe("note.md")
    restarted = IndexWorker(tmp_path, quiet_seconds=0)
    assert restarted.target == worker.target
    assert restarted.queue.ready() == ("note.md", 1)
    asyncio.run(restarted.scan())
    asyncio.run(restarted.process_next())
    assert restarted.queue.pending_count() == 0


def test_offline_embedder_leaves_work_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    worker.observe("note.md")
    assert asyncio.run(worker.process_next())
    assert worker.queue.pending_count() == 1
    assert worker.queue.ready() is None
    assert not (worker.cache / "current-generation").exists()
