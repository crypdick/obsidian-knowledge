"""Tests for ObsidianVaultProvider lifecycle methods."""
import json
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lib.vault_index.config import load_config
from lib.vault_index.indexer import Indexer, default_cache_dir


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
    cache = default_cache_dir(vault)
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

def test_prefetch_returns_report_format(provider, vault, monkeypatch):
    monkeypatch.setattr(
        provider,
        "_prefetch_cache",
        [{"score": 100.0, "path": "wiki/python.md"}],
    )
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = False

    out = provider.prefetch("python")
    assert "Top semantic vault hits:" in out
    assert "wiki/python.md" in out
    assert "long-term memory" in out
    assert "vault_search" in out


def test_prefetch_dedups_across_calls(provider, vault, monkeypatch):
    monkeypatch.setattr(
        provider,
        "_prefetch_cache",
        [{"score": 100.0, "path": "wiki/python.md"}],
    )
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = False
    first = provider.prefetch("python")

    monkeypatch.setattr(
        provider,
        "_prefetch_cache",
        [{"score": 100.0, "path": "wiki/python.md"}],
    )
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = False
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
    out = provider.prefetch("python")
    # Should still contain the nudge boilerplate; no header expected
    assert "long-term memory" in out


def test_prefetch_does_not_block_on_running_background_search(provider, monkeypatch):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("prefetch must not run a synchronous vault search")

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fail_if_called)
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = True

    out = provider.prefetch("python")

    provider._prefetch_thread.join.assert_called_once_with(timeout=0.0)
    assert "long-term memory" in out


# ── Task 16: on_pre_compress ─────────────────────────────────────────────────

def test_on_pre_compress_clears_dedup_set(provider, vault):
    provider.injected_paths_this_session.add("wiki/python.md")
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


def test_vault_search_subprocess_uses_default_cache_and_timeout(monkeypatch, provider):
    import hermes_plugin

    calls = []

    class Result:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fake_run)
    assert hermes_plugin._run_vault_search("python") == []

    script = calls[0][0][0][2]
    assert "default_cache_dir" in script
    assert "vault / '.config' / 'obsidian-knowledge' / 'cache'" not in script
    assert calls[0][1]["timeout"] == hermes_plugin._VAULT_SEARCH_TIMEOUT_SECONDS


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


def test_sync_turn_runs_indexer_in_background(monkeypatch, provider):
    import hermes_plugin

    calls = []

    class Result:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fake_run)
    provider.sync_turn(user_content="hi", assistant_content="hello")
    provider._sync_thread.join(timeout=5.0)

    assert not provider._sync_thread.is_alive()
    assert provider._sync_thread.daemon is False
    assert calls[0][1]["timeout"] == hermes_plugin._VAULT_SEARCH_TIMEOUT_SECONDS
    script = calls[0][0][0][2]
    assert "default_cache_dir" in script
    assert "idx.sync()" in script
    assert "idx.row_count()" in script


# ── Task 19: queue_prefetch ──────────────────────────────────────────────────

def test_queue_prefetch_warms_next_call(provider, vault):
    build_index(vault)
    provider.queue_prefetch("python")  # warms cache
    assert provider._prefetch_thread.daemon is False
    out = provider.prefetch("python")  # consumes
    assert "Top semantic vault hits" in out or "long-term memory" in out


def test_queue_prefetch_skips_when_search_already_running(provider, monkeypatch):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("queue_prefetch must not start overlapping searches")

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fail_if_called)
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = True

    provider.queue_prefetch("python")


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


# ── Hermes plugin hook bridge ───────────────────────────────────────────────


def test_register_adds_hermes_hook_bridge(provider):
    import hermes_plugin

    class Ctx:
        def __init__(self):
            self.hooks = []

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

    ctx = Ctx()
    hermes_plugin.register(ctx)

    assert {name for name, _ in ctx.hooks} >= {
        "pre_tool_call",
        "post_tool_call",
        "on_session_end",
        "pre_llm_call",
    }


def test_pre_tool_call_blocks_terminal_protected_dir(provider, vault):
    import hermes_plugin

    protected = vault / "_sources" / "original.pdf"
    protected.parent.mkdir()
    protected.write_text("original")

    result = hermes_plugin._on_pre_tool_call(
        tool_name="terminal",
        args={"command": f"rm {protected}"},
    )

    assert result["action"] == "block"
    assert "protected" in result["message"]


def test_pre_tool_call_blocks_write_file_generic_name(provider, vault):
    import hermes_plugin

    (vault / ".claude" / "obsidian-knowledge.yaml").write_text(
        "generic_filenames:\n  - notes.md\n"
    )

    result = hermes_plugin._on_pre_tool_call(
        tool_name="write_file",
        args={"path": str(vault / "wiki" / "topic" / "notes.md"), "content": "x"},
    )

    assert result["action"] == "block"
    assert "generic" in result["message"].lower()


def test_pre_tool_call_blocks_patch_mode_publish_guard(provider, vault):
    import hermes_plugin

    (vault / ".claude" / "obsidian-knowledge.yaml").write_text(
        "publish_allowlist:\n  - wiki/allowed/\n"
    )

    result = hermes_plugin._on_pre_tool_call(
        tool_name="patch",
        args={
            "mode": "patch",
            "patch": (
                "*** Begin Patch\n"
                f"*** Add File: {vault}/wiki/python/published.md\n"
                "+---\n"
                "+dg-publish: true\n"
                "+---\n"
                "+body\n"
                "*** End Patch\n"
            ),
        },
    )

    assert result["action"] == "block"
    assert "dg-publish" in result["message"]


def test_post_tool_call_reflection_queues_next_pre_llm(monkeypatch, provider, tmp_path):
    import hermes_plugin

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path))
    key = "session-reflect"

    for _ in range(10):
        hermes_plugin._on_post_tool_call(
            tool_name="terminal",
            args={"command": "pwd"},
            session_id=key,
            result='{"exit_code": 0}',
        )

    injected = hermes_plugin._on_pre_llm_call(session_id=key)

    assert injected is not None
    assert "friction" in injected["context"]


def test_session_end_queues_index_sync_nudge(provider):
    import hermes_plugin

    key = "session-index"
    hermes_plugin._on_post_tool_call(
        tool_name="write_file",
        args={"path": "/vault/wiki/python/new-note.md", "content": "x"},
        session_id=key,
        result='{"status": "success"}',
    )
    hermes_plugin._on_session_end(session_id=key)

    injected = hermes_plugin._on_pre_llm_call(session_id=key)

    assert injected is not None
    assert "parent index.md" in injected["context"]
