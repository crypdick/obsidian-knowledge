"""Published notes survive cancelled and superseded embedding work."""

import asyncio

import pytest

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


def test_file_changed_during_embedding_keeps_previous_searchable_text(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("orchid original")
    cache = tmp_path / "cache"
    instance = Indexer(tmp_path, cache, VaultIndexConfig(), vector_enabled=False)
    instance.full_reindex()
    asyncio.run(instance._store.close())
    note.write_text("replacement tulip")

    async def embed(texts):
        note.write_text("still editing daisy")
        return [[] for _ in texts]

    instance._store.embedding_provider.embed_batch = embed
    with pytest.raises(OSError, match="changed during indexing"):
        asyncio.run(instance.index_settled_path("note.md"))
    assert instance.search("orchid")[0].path == "note.md"
    assert instance.search("tulip") == []


def test_settled_path_rejects_escape_and_legacy_update_requires_vectors(tmp_path):
    from lib.vault_index.models import IndexBusyError

    instance = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(instance.index_settled_path("../outside.md"))
    with pytest.raises(IndexBusyError, match="embeddings unavailable"):
        instance.index_paths(["note.md"])


@pytest.mark.parametrize("failure", ["outer-deadline", "sql-budget"])
def test_semantic_fallback_does_not_swallow_outer_deadline(tmp_path, failure):
    from lib.vault_index.cli import SearchTimeoutError
    from obsidian_knowledge_vendor.memweave import SearchError

    instance = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), skip_probe=True)
    instance.vector_issue = None

    async def search(*args, **kwargs):
        if failure == "outer-deadline":
            raise SearchTimeoutError("outer deadline")
        raise SearchError("interrupted")

    instance._store.search = search
    if failure == "outer-deadline":
        with pytest.raises(SearchTimeoutError):
            instance.search_report("query")
    else:
        assert instance.search_report("query").degraded_reason == "semantic SQL exceeded its budget"


@pytest.mark.parametrize("budget", ["invalid", "0"])
def test_search_budget_preserves_cli_environment_defaults(tmp_path, monkeypatch, budget):
    from obsidian_knowledge_vendor.memweave import SearchResult

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", budget)
    instance = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), skip_probe=True)
    instance.vector_issue = None

    async def search(*args, **kwargs):
        return [
            SearchResult(
                path=str(tmp_path / "note.md"),
                start_line=1,
                end_line=1,
                score=0.5,
                snippet="",
                source="memory",
            )
        ]

    instance._store.search = search
    assert instance.search_report("query").mode == "hybrid"
