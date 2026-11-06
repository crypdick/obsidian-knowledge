"""Result-scaled deadlines account for initialization and retain fallback time."""

from types import SimpleNamespace

import pytest

from lib.vault_index import search_budget
from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=100.0)
    monkeypatch.setattr(search_budget, "time", SimpleNamespace(monotonic=lambda: current.now))
    return current


@pytest.mark.parametrize(("top_k", "seconds"), [(1, 5.1), (10, 6), (100, 15), (1000, 28)])
def test_linear_budget_and_outer_cap(clock, monkeypatch, top_k, seconds):
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", raising=False)
    assert search_budget.semantic_deadline(top_k) == pytest.approx(clock.now + seconds)


@pytest.mark.parametrize(("ttl", "seconds"), [("invalid", 28), ("0", 105), ("-1", 105), ("4", 2)])
def test_environment_deadline_defaults_and_disabled_limit(clock, monkeypatch, ttl, seconds):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", ttl)
    assert search_budget.semantic_deadline(1000) == clock.now + seconds


def test_elapsed_initialization_reduces_budget_and_context_resets(clock):
    with search_budget.command_deadline(30):
        clock.now += 25
        assert search_budget.semantic_deadline(100) == 128
        clock.now += 4
        assert search_budget.semantic_deadline(100) == 129.5
        clock.now += 2
        assert search_budget.semantic_deadline(100) == 131
        with search_budget.command_deadline(0):
            assert search_budget.semantic_deadline(1000) == 236
        assert search_budget.semantic_deadline(100) == 131
    assert search_budget.COMMAND_DEADLINE.get() is None


def test_budget_context_resets_on_failure(clock):
    with pytest.raises(ValueError), search_budget.command_deadline(30):
        raise ValueError("test failure")
    assert search_budget.COMMAND_DEADLINE.get() is None


def test_requested_count_controls_shared_deadline_not_expanded_candidates(tmp_path, clock, monkeypatch):
    from lib.vault_index import indexer

    monkeypatch.setattr(indexer, "time", SimpleNamespace(monotonic=lambda: clock.now))
    instance = Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), skip_probe=True)
    instance.vector_issue = None
    captured = {}

    async def search(query, **kwargs):
        captured.update(kwargs)
        return []

    async def wait_for(coro, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return await coro

    monkeypatch.setattr(instance._store, "search", search)
    monkeypatch.setattr(indexer.asyncio, "wait_for", wait_for)
    with search_budget.command_deadline(30):
        clock.now += 20
        assert instance.search_report("orchid", top_k=100).mode == "hybrid"
    assert captured == {"timeout": 8, "max_results": 500, "min_score": 0.0, "deadline": 128}
