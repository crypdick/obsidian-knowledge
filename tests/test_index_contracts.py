"""Index entrypoints share admission, identity, and restart contracts."""

import asyncio

import pytest
from pydantic import ValidationError

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.index_generations import active_cache
from lib.vault_index.index_state import embedding_fingerprint
from lib.vault_index.index_worker import IndexWorker
from lib.vault_index.indexer import Indexer
from lib.vault_index.mcp_index import read_index_status


@pytest.mark.parametrize("mode", ["full", "targeted", "settled", "worker"])
def test_index_admission_agrees_across_entrypoints(tmp_path, monkeypatch, fake_ollama, mode):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("orchid allowed")
    outside = tmp_path / "secret.md"
    outside.write_text("private daisy")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    from lib.vault_index.indexer import default_cache_dir

    config = VaultIndexConfig(index={"deny_regex": ["^denied/"]})
    index = Indexer(vault, default_cache_dir(vault), config)
    try:
        index.full_reindex()
        excluded = [".hidden/note.md", "venv/note.md", "__pycache__/note.md", "denied/note.md"]
        for relative in excluded:
            path = vault / relative
            path.parent.mkdir()
            path.write_text("private daisy")
        (vault / "external.md").symlink_to(outside)
        (vault / "internal.md").symlink_to(vault / "note.md")
        (vault / "alias").symlink_to(vault / "denied", target_is_directory=True)
        excluded += ["external.md", "internal.md", "alias/note.md"]
        fake_ollama.texts.clear()
        if mode == "full":
            index.full_reindex()
        elif mode == "targeted":
            index.index_paths(["."])
        elif mode == "settled":
            for relative in excluded:
                asyncio.run(index.index_settled_path(relative))
        else:
            worker = IndexWorker(vault, quiet_seconds=0)
            worker.config = config

            async def drain():
                await worker.scan()
                while await worker.process_next():
                    pass

            asyncio.run(drain())
        assert index.indexed_paths() == ["note.md"]
        assert not any("private" in text for text in fake_ollama.texts)
    finally:
        asyncio.run(index._store.close())


@pytest.mark.parametrize("mode", ["full", "targeted", "settled"])
def test_old_entry_removed_when_replaced_by_external_symlink(tmp_path, fake_ollama, mode):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "note.md"
    note.write_text("orchid allowed")
    index = Indexer(vault, tmp_path / "cache", VaultIndexConfig())
    try:
        index.full_reindex()
        note.unlink()
        outside = tmp_path / "secret.md"
        outside.write_text("private daisy")
        note.symlink_to(outside)
        if mode == "full":
            index.full_reindex()
        elif mode == "targeted":
            index.index_paths(["note.md"])
        else:
            asyncio.run(index.index_settled_path("note.md"))
        assert index.indexed_paths() == []
    finally:
        asyncio.run(index._store.close())


def test_restart_removes_deleted_staged_only_note_before_publication(tmp_path, monkeypatch, fake_ollama):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    note = tmp_path / "new.md"
    note.write_text("orchid staged")
    worker = IndexWorker(tmp_path, quiet_seconds=0)
    asyncio.run(worker.scan())
    assert asyncio.run(worker.process_next())
    assert not (worker.cache / "current-generation").exists()
    note.unlink()
    restarted = IndexWorker(tmp_path, quiet_seconds=0)
    assert restarted.target == worker.target

    async def drain():
        await restarted.scan()
        while await restarted.process_next():
            pass

    asyncio.run(drain())
    assert active_cache(worker.cache) == restarted.target
    index = Indexer(tmp_path, worker.cache, VaultIndexConfig(), vector_enabled=False)
    assert index.indexed_paths() == []


def test_endpoint_change_invalidates_worker_and_mcp_readiness(
    tmp_path, monkeypatch, fake_ollama, drain_index
):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    asyncio.run(drain_index(tmp_path))
    old = IndexWorker(tmp_path, quiet_seconds=0)
    assert not old.building
    assert read_index_status(tmp_path).vector_index_ready
    fingerprint = embedding_fingerprint()
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_KEY", "synthetic-credential")
    assert embedding_fingerprint() == fingerprint
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "http://other-provider:11434")
    changed = IndexWorker(tmp_path, quiet_seconds=0)
    assert changed.building
    assert changed.target != active_cache(changed.cache)
    assert not read_index_status(tmp_path).vector_index_ready
    assert read_index_status(tmp_path).degraded_reason == "embedding settings changed; update required"


@pytest.mark.parametrize("overrides", [{"top_k": 0}, {"top_k": -1}, {"min_score": float("nan")}])
def test_search_overrides_use_config_validation(tmp_path, overrides):
    index = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    with pytest.raises(ValidationError):
        index.search_report("orchid", **overrides)


def test_foreground_reindex_uses_generations_and_preserves_old_reader(tmp_path, monkeypatch, fake_ollama):
    from lib.vault_index.index_worker import foreground_reindex
    from lib.vault_index.indexer import default_cache_dir

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    note = tmp_path / "note.md"
    note.write_text("orchid")
    seen = []
    first = foreground_reindex(tmp_path, progress=lambda done, total: seen.append((done, total)))
    assert (first.indexed, first.skipped, first.deleted) == (1, 0, 0)
    assert seen[0][0] == 0
    cache = default_cache_dir(tmp_path)
    previous = active_cache(cache)
    old = Indexer(tmp_path, cache, VaultIndexConfig(), vector_enabled=False)
    assert foreground_reindex(tmp_path).skipped == 1
    note.write_text("tulip")
    forced = foreground_reindex(tmp_path, force=True)
    assert (forced.indexed, forced.skipped, forced.deleted) == (1, 0, 0)
    assert active_cache(cache) != previous
    assert old.search("orchid")[0].path == "note.md"
    note.unlink()
    deleted = foreground_reindex(tmp_path)
    assert deleted.deleted == 1


def test_foreground_offline_recovery_remains_keyword_only(tmp_path, monkeypatch):
    from lib.vault_index.index_worker import foreground_reindex
    from lib.vault_index.indexer import default_cache_dir

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    assert foreground_reindex(tmp_path).indexed == 1
    index = Indexer(tmp_path, default_cache_dir(tmp_path), VaultIndexConfig(), vector_enabled=False)
    assert index.search("orchid")[0].path == "note.md"
    assert read_index_status(tmp_path).degraded_reason == "index built in keyword-only mode"


def test_foreground_backend_failure_surfaces_without_publishing(tmp_path, monkeypatch, fake_ollama):
    from lib.vault_index.index_worker import foreground_reindex
    from lib.vault_index.indexer import default_cache_dir

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")

    async def fail(self, relative):
        raise OSError("backend failed")

    monkeypatch.setattr(IndexWorker, "index_one", fail)
    with pytest.raises(OSError, match="backend failed"):
        foreground_reindex(tmp_path)
    assert not (default_cache_dir(tmp_path) / "current-generation").exists()
    worker = IndexWorker(tmp_path)
    assert worker.queue.pending_count() == 1


def test_legacy_fingerprint_requires_rebuild_in_worker_and_status(tmp_path, monkeypatch, fake_ollama):
    from lib.vault_index.index_worker import foreground_reindex
    from lib.vault_index.indexer import default_cache_dir

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    foreground_reindex(tmp_path)
    cache = default_cache_dir(tmp_path)
    (active_cache(cache) / "embedder-fingerprint.txt").write_text("ollama/bge-m3@320/64")
    assert IndexWorker(tmp_path).building
    assert not read_index_status(tmp_path).vector_index_ready
    assert foreground_reindex(tmp_path).indexed == 1
    assert read_index_status(tmp_path).vector_index_ready


@pytest.mark.parametrize("phase", ["initialization", "drain"])
def test_foreground_lock_races_report_busy(tmp_path, monkeypatch, phase):
    import fcntl

    from lib.vault_index.index_worker import foreground_reindex
    from lib.vault_index.indexer import default_cache_dir
    from lib.vault_index.models import IndexBusyError

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    cache = default_cache_dir(tmp_path)
    cache.mkdir(parents=True)
    with (cache / ".worker.lock").open("w") as held:
        if phase == "initialization":
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            original = IndexWorker.__init__

            def raced(self, *args, **kwargs):
                original(self, *args, **kwargs)
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)

            monkeypatch.setattr(IndexWorker, "__init__", raced)
        with pytest.raises(IndexBusyError, match="worker is running"):
            foreground_reindex(tmp_path)


def test_foreground_waits_for_existing_quiet_deadline(tmp_path, monkeypatch, fake_ollama):
    from lib.vault_index.index_worker import foreground_reindex

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "note.md").write_text("orchid")
    worker = IndexWorker(tmp_path, quiet_seconds=0.2)
    worker.observe("note.md")
    assert foreground_reindex(tmp_path).indexed == 1


def test_notification_rejects_external_alias_without_reading_it(tmp_path, monkeypatch):
    from lib.vault_index.index_worker import enqueue_paths

    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("secret")
    (vault / "alias.md").symlink_to(outside)
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="escapes vault"):
        enqueue_paths(vault, ["alias.md"])


def test_content_signature_represents_deletion(tmp_path):
    from lib.vault_index.index_worker import content_signature

    assert content_signature(tmp_path / "missing.md") == "deleted"
