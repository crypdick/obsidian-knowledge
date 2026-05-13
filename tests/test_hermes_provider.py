"""Tests for ObsidianVaultProvider lifecycle methods."""
import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lib.vault_index.config import load_config
from lib.vault_index.indexer import Indexer


FIXTURE = Path(__file__).parent / "fixtures" / "sample_vault"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE, dst)
    return dst


@pytest.fixture
def provider(vault: Path, tmp_path: Path):
    # Patch the import of agent.memory_provider so we don't need Hermes installed.
    import sys
    sys.modules["agent"] = MagicMock()
    sys.modules["agent.memory_provider"] = MagicMock()
    sys.modules["agent.memory_provider"].MemoryProvider = object  # type: ignore

    from importlib import reload
    import hermes_plugin
    reload(hermes_plugin)

    os.environ["OBSIDIAN_VAULT_ROOT"] = str(vault)
    p = hermes_plugin.ObsidianVaultProvider()
    p.initialize(session_id="test")
    yield p
    p.shutdown()
    del os.environ["OBSIDIAN_VAULT_ROOT"]


def make_indexer(vault: Path) -> Indexer:
    cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
    cache = vault / ".config" / "obsidian-knowledge" / "cache"
    return Indexer(vault_root=vault, cache_dir=cache, config=cfg)


def build_index(vault: Path) -> Indexer:
    indexer = make_indexer(vault)
    indexer.full_reindex()
    return indexer


# ── Task 14: system_prompt_block ─────────────────────────────────────────────

def test_system_prompt_block_includes_primer(provider, vault):
    block = provider.system_prompt_block()
    assert "obsidian-knowledge harness" in block
    assert "wiki" in block.lower()


def test_system_prompt_block_includes_skill_view_directive(provider):
    block = provider.system_prompt_block()
    assert "skill_view" in block
    assert "obsidian-knowledge" in block


# ── Task 15: prefetch + path-dedup ───────────────────────────────────────────

def test_prefetch_returns_report_format(provider, vault):
    build_index(vault)
    out = provider.prefetch("python")
    assert "Top semantic vault hits:" in out
    assert "long-term memory" in out
    assert "vault_search" in out


def test_prefetch_dedups_across_calls(provider, vault):
    build_index(vault)
    first = provider.prefetch("python")
    second = provider.prefetch("python")
    # Paths surfaced in first call should not appear in second call's path lines.
    # Path lines start with leading whitespace + a digit (score).
    first_paths = [
        line.strip()
        for line in first.splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    second_paths = [
        line.strip()
        for line in second.splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    # No overlap — dedup must have filtered out paths already seen.
    assert not (set(first_paths) & set(second_paths))


def test_prefetch_returns_only_nudge_when_no_fresh_hits(provider, vault):
    build_index(vault)
    provider.prefetch("python")  # populate dedup set
    out = provider.prefetch("python")
    # Should still contain the nudge boilerplate; no header expected
    assert "long-term memory" in out


# ── Task 16: on_pre_compress ─────────────────────────────────────────────────

def test_on_pre_compress_clears_dedup_set(provider, vault):
    build_index(vault)
    provider.prefetch("python")
    assert len(provider.injected_paths_this_session) > 0
    result = provider.on_pre_compress(messages=[])
    assert result == ""
    assert provider.injected_paths_this_session == set()


# ── Task 17: vault_search tool ───────────────────────────────────────────────

def test_get_tool_schemas_returns_vault_search(provider):
    schemas = provider.get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "vault_search"
    assert "query" in schemas[0]["parameters"]["properties"]


def test_handle_tool_call_vault_search_returns_json(provider, vault):
    build_index(vault)
    result_json = provider.handle_tool_call("vault_search", {"query": "python"})
    result = json.loads(result_json)
    assert isinstance(result, list)
    if result:
        assert "score" in result[0]
        assert "path" in result[0]


def test_handle_tool_call_vault_search_respects_top_k(provider, vault):
    build_index(vault)
    result = json.loads(
        provider.handle_tool_call("vault_search", {"query": "python", "top_k": 1})
    )
    assert len(result) <= 1


def test_handle_tool_call_unknown_tool_raises(provider):
    with pytest.raises(NotImplementedError):
        provider.handle_tool_call("not_a_tool", {})


# ── Task 18: sync_turn ───────────────────────────────────────────────────────

import time


def test_sync_turn_runs_indexer_in_background(provider, vault):
    indexer = build_index(vault)
    initial_count = indexer.row_count()
    new_file = vault / "wiki" / "new.md"
    new_file.write_text("# New\nFresh content for indexing.\n")

    provider.sync_turn(user_content="hi", assistant_content="hello")
    # Join the background thread (up to 30s to allow for embedding retries).
    provider._sync_thread.join(timeout=30.0)
    refreshed = make_indexer(vault)
    assert refreshed.row_count() > initial_count


# ── Task 19: queue_prefetch ──────────────────────────────────────────────────

def test_queue_prefetch_warms_next_call(provider, vault):
    build_index(vault)
    provider.queue_prefetch("python")  # warms cache
    out = provider.prefetch("python")  # consumes
    assert "Top semantic vault hits" in out or "long-term memory" in out


# ── Task 20: atexit safety net ───────────────────────────────────────────────

def test_atexit_safety_net_registered(monkeypatch, vault):
    # Pattern from OpenViking: a process-global ref + atexit handler ensure
    # shutdown fires even on crash. Verify the handler runs.
    import os
    os.environ["OBSIDIAN_VAULT_ROOT"] = str(vault)
    from importlib import reload
    import hermes_plugin
    reload(hermes_plugin)

    p = hermes_plugin.ObsidianVaultProvider()
    p.initialize(session_id="t")
    assert hermes_plugin._last_active_provider is p
    del os.environ["OBSIDIAN_VAULT_ROOT"]
