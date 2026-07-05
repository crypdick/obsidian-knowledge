# allow: file-length  (broad lifecycle test surface; splitting tracked in docs/QUALITY.md)
"""Tests for ObsidianKnowledgeProvider lifecycle methods."""

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
    p = hermes_plugin.ObsidianKnowledgeProvider()
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


def command_script(cmd: list[str]) -> str:
    return cmd[cmd.index("-c") + 1]


# ── Task 14: system_prompt_block ─────────────────────────────────────────────


def test_system_prompt_block_includes_primer(provider, vault):
    block = provider.system_prompt_block()
    assert "obsidian-knowledge harness" in block
    assert "wiki" in block.lower()


def test_system_prompt_block_includes_skill_view_directive(provider):
    block = provider.system_prompt_block()
    assert "skill_view" in block
    assert "obsidian-knowledge" in block


# ── Task 15: prefetch uses current-turn vault_search ─────────────────────────


def test_prefetch_returns_report_format(provider, vault, monkeypatch):
    import hermes_plugin

    monkeypatch.setattr(
        hermes_plugin,
        "_run_vault_search",
        lambda query, **kwargs: [{"score": 100.0, "path": "wiki/python.md"}],
    )

    out = provider.prefetch("python")
    assert "Results for vault_search('python')" in out
    assert "wiki/python.md" in out
    assert "long-term memory" in out
    assert "vault_search" in out


def test_prefetch_runs_current_query_every_call(provider, vault, monkeypatch):
    import hermes_plugin

    calls = []

    def fake_search(query, **kwargs):
        calls.append(query)
        return [{"score": 100.0, "path": f"wiki/{query}.md"}]

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fake_search)

    first = provider.prefetch("python")
    second = provider.prefetch("python")

    assert calls == ["python", "python"]
    assert "wiki/python.md" in first
    assert "wiki/python.md" in second


def test_prefetch_inlines_warning_when_vault_search_returns_no_hits(provider, vault, monkeypatch):
    import hermes_plugin

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", lambda query, **kwargs: [])

    out = provider.prefetch("python")

    assert "Obsidian memory provider warning" in out
    assert "vault_search('python') returned no hits" in out
    assert "fix the memory plugin" in out
    assert "long-term memory" in out


def test_prefetch_skips_greeting_without_search(provider, monkeypatch):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("greeting prefetch should not search the vault")

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fail_if_called)

    out = provider.prefetch("hi")

    assert "long-term memory" in out


def test_prefetch_uses_bounded_no_rebuild_search(provider, monkeypatch):
    import hermes_plugin

    calls = []

    def fake_search(query, **kwargs):
        calls.append((query, kwargs))
        return [{"score": 100.0, "path": "wiki/current.md"}]

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fake_search)

    out = provider.prefetch("how should I tune Hermes memory?")

    assert "wiki/current.md" in out
    assert calls == [
        (
            "how should I tune Hermes memory?",
            {
                "timeout": hermes_plugin._VAULT_PREFETCH_TIMEOUT_SECONDS,
                "allow_rebuild": False,
            },
        )
    ]


def test_prefetch_ignores_stale_background_cache(provider, monkeypatch):
    import hermes_plugin

    monkeypatch.setattr(
        hermes_plugin,
        "_run_vault_search",
        lambda query, **kwargs: [{"score": 100.0, "path": "wiki/current.md"}],
    )
    provider._prefetch_cache = [{"score": 100.0, "path": "wiki/stale.md"}]
    provider._prefetch_thread = MagicMock()
    provider._prefetch_thread.is_alive.return_value = True

    out = provider.prefetch("python")

    provider._prefetch_thread.join.assert_not_called()
    assert "wiki/current.md" in out
    assert "wiki/stale.md" not in out
    assert "long-term memory" in out


# ── Task 16: on_pre_compress ─────────────────────────────────────────────────


def test_on_pre_compress_clears_dedup_set(provider, vault):
    provider.injected_paths_this_session.add("wiki/python.md")
    assert len(provider.injected_paths_this_session) > 0
    result = provider.on_pre_compress(messages=[])
    assert result == ""
    assert provider.injected_paths_this_session == set()


# ── Task 17: vault_search tool ───────────────────────────────────────────────


def test_get_tool_schemas_returns_vault_search_and_memory_redirect(provider):
    schemas = provider.get_tool_schemas()
    by_name = {schema["name"]: schema for schema in schemas}
    assert set(by_name) == {"vault_search", "memory"}
    assert "query" in by_name["vault_search"]["parameters"]["properties"]


def test_handle_tool_call_memory_returns_redirect_error(provider):
    result = json.loads(
        provider.handle_tool_call("memory", {"action": "add", "target": "memory", "content": "x"})
    )
    assert result["success"] is False
    assert "Built-in Hermes memory is disabled" in result["error"]
    assert result["replacement"] == "obsidian-knowledge"


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

    script = command_script(calls[0][0][0])
    assert "default_cache_dir" in script
    assert "vault / '.config' / 'obsidian-knowledge' / 'cache'" not in script
    assert calls[0][1]["timeout"] == hermes_plugin._VAULT_SEARCH_TIMEOUT_SECONDS


def test_build_primer_subprocess_uses_timeout_and_forced_exit(monkeypatch, provider, vault):
    import hermes_plugin

    calls = []

    class Result:
        returncode = 0
        stdout = "primer"
        stderr = ""

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fake_run)

    assert hermes_plugin._run_build_primer(str(vault), str(vault.parent)) == "primer"

    script = command_script(calls[0][0][0])
    assert "os._exit(0)" in script
    assert calls[0][1]["timeout"] == hermes_plugin._VAULT_PRIMER_TIMEOUT_SECONDS


def test_build_primer_timeout_returns_fallback(monkeypatch, provider, vault):
    import hermes_plugin

    def fake_run(*args, **kwargs):
        raise hermes_plugin.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fake_run)

    assert (
        hermes_plugin._run_build_primer(str(vault), str(vault.parent))
        == "You are operating under the obsidian-knowledge harness."
    )


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
    result = json.loads(provider.handle_tool_call("vault_search", {"query": "python", "top_k": 1}))
    assert len(result) <= 1


def test_handle_tool_call_unknown_tool_raises(provider):
    with pytest.raises(NotImplementedError):
        provider.handle_tool_call("not_a_tool", {})


def test_indexer_does_not_force_rebuild_for_prefingerprint_vector_cache(tmp_path: Path, vault: Path):
    """Old caches with an existing vector table should remain searchable.

    A missing embedder fingerprint alone is not proof that the cache is FTS-only:
    deployments upgraded before the fingerprint file existed may already have
    populated chunks_vec. Search/prefetch must not synchronously rebuild those
    caches on every query, because gateway memory prefetch has a tight timeout.
    """
    cache = tmp_path / "cache"
    cache.mkdir()
    import sqlite3

    with sqlite3.connect(cache / "index.sqlite") as conn:
        conn.execute("CREATE TABLE chunks_vec (id INTEGER PRIMARY KEY)")

    idx = Indexer(
        vault_root=vault,
        cache_dir=cache,
        config=load_config(vault / ".claude" / "obsidian-knowledge.yaml"),
        skip_probe=True,
    )

    assert idx._stale_fingerprint() is False
    assert idx._needs_rebuild is False


def test_indexer_rebuilds_prefingerprint_cache_without_vector_table(tmp_path: Path, vault: Path):
    """Pre-vector/pre-fingerprint caches still need a one-time rebuild."""
    cache = tmp_path / "cache"
    cache.mkdir()
    import sqlite3

    with sqlite3.connect(cache / "index.sqlite") as conn:
        conn.execute("CREATE TABLE files (id INTEGER PRIMARY KEY)")

    idx = Indexer(
        vault_root=vault,
        cache_dir=cache,
        config=load_config(vault / ".claude" / "obsidian-knowledge.yaml"),
        skip_probe=True,
    )

    assert idx._stale_fingerprint() is True
    assert idx._needs_rebuild is True


def test_indexer_search_can_skip_rebuild_for_hot_path(vault: Path):
    idx = make_indexer(vault)
    idx._needs_rebuild = True
    idx._vector_enabled = False
    idx._auto_rebuild = MagicMock(side_effect=AssertionError("should not rebuild"))

    assert isinstance(idx.search("python", allow_rebuild=False), list)
    idx._auto_rebuild.assert_not_called()


# ── Task 18: sync_turn ───────────────────────────────────────────────────────


def test_sync_turn_skips_when_no_vault_markdown_changed(monkeypatch, provider):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("sync_turn should not reindex when the vault is clean")

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fail_if_called)

    provider.sync_turn(user_content="hi", assistant_content="hello", session_id="test")

    assert provider._sync_thread is None


def test_sync_turn_runs_indexer_after_vault_markdown_write(monkeypatch, provider, vault):
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
    hermes_plugin._on_post_tool_call(
        tool_name="write_file",
        args={"path": str(vault / "wiki" / "python.md"), "content": "updated"},
        session_id="test",
        result='{"bytes_written": 7}',
    )

    provider.sync_turn(user_content="hi", assistant_content="hello", session_id="test")
    provider._sync_thread.join(timeout=5.0)

    assert not provider._sync_thread.is_alive()
    assert provider._sync_thread.daemon is False
    assert calls[0][1]["timeout"] == hermes_plugin._VAULT_SYNC_TIMEOUT_SECONDS
    script = command_script(calls[0][0][0])
    assert "user_cache_dir('obsidian-knowledge')" in script
    assert hermes_plugin._SYNC_FINGERPRINT_FILENAME in script
    assert "path_passes(rel, cfg.index)" in script
    assert "marker.read_text().strip() == digest" in script
    assert "from lib.vault_index.indexer import Indexer" in script
    assert script.index("marker.read_text().strip() == digest") < script.index(
        "from lib.vault_index.indexer import Indexer"
    )
    assert "idx.sync()" in script
    assert "idx.row_count()" in script


# ── Task 19: queue_prefetch ──────────────────────────────────────────────────


def test_queue_prefetch_is_noop(provider, vault, monkeypatch):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("queue_prefetch should not run stale next-turn searches")

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fail_if_called)

    provider.queue_prefetch("python")

    assert provider._prefetch_thread is None


def test_queue_prefetch_does_not_touch_existing_thread(provider, monkeypatch):
    import hermes_plugin

    def fail_if_called(*args, **kwargs):
        raise AssertionError("queue_prefetch should not inspect or start background searches")

    monkeypatch.setattr(hermes_plugin, "_run_vault_search", fail_if_called)
    provider._prefetch_thread = MagicMock()

    provider.queue_prefetch("python")

    provider._prefetch_thread.is_alive.assert_not_called()


# ── Task 20: atexit safety net ───────────────────────────────────────────────


def test_atexit_safety_net_registered(monkeypatch, vault):
    # Pattern from OpenViking: a process-global ref + atexit handler ensure
    # shutdown fires even on crash. Verify the handler runs.
    import os

    os.environ["OBSIDIAN_VAULT_ROOT"] = str(vault)
    from importlib import reload

    import hermes_plugin

    reload(hermes_plugin)

    p = hermes_plugin.ObsidianKnowledgeProvider()
    p.initialize(session_id="t")
    assert hermes_plugin._last_active_provider is p
    del os.environ["OBSIDIAN_VAULT_ROOT"]


def test_installed_plugin_root_defaults_to_repo_root(provider):
    import hermes_plugin

    assert hermes_plugin._PLUGIN_REPO == Path(hermes_plugin.__file__).resolve().parent.parent


def test_python_cmd_falls_back_to_uv_run(monkeypatch, provider, tmp_path):
    import hermes_plugin

    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_PYTHON", raising=False)
    monkeypatch.setattr(hermes_plugin, "_UV_PYTHON", tmp_path / "missing-python")

    assert hermes_plugin._python_cmd() == ["uv", "run", "python"]


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
        "on_session_finalize",
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

    (vault / ".claude" / "obsidian-knowledge.yaml").write_text("generic_filenames:\n  - notes.md\n")

    result = hermes_plugin._on_pre_tool_call(
        tool_name="write_file",
        args={"path": str(vault / "wiki" / "topic" / "notes.md"), "content": "x"},
    )

    assert result["action"] == "block"
    assert "generic" in result["message"].lower()


def test_pre_tool_call_blocks_patch_mode_publish_guard(provider, vault):
    import hermes_plugin

    (vault / ".claude" / "obsidian-knowledge.yaml").write_text("publish_allowlist:\n  - wiki/allowed/\n")

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
    assert "remember-conversations" in injected["context"]
    assert "/improve-harness" not in injected["context"]
    assert "or describe it" not in injected["context"]
    assert "auto-invokes improve-harness" not in injected["context"]


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


def test_session_end_queues_index_sync_nudge_for_terminal_obsidian_move(provider):
    import hermes_plugin

    key = "session-index-move"
    hermes_plugin._on_post_tool_call(
        tool_name="terminal",
        args={"command": 'obsidian move path="wiki/systems/foo.md" to="wiki/systems/bar.md"'},
        session_id=key,
        result='{"exit_code": 0}',
    )
    hermes_plugin._on_session_end(session_id=key)

    injected = hermes_plugin._on_pre_llm_call(session_id=key)

    assert injected is not None
    assert "wiki/systems/" in injected["context"]
    assert "parent index.md" in injected["context"]


def test_session_end_does_not_queue_index_sync_nudge_when_terminal_edits_index(provider):
    import hermes_plugin

    key = "session-index-move-synced"
    hermes_plugin._on_post_tool_call(
        tool_name="terminal",
        args={"command": 'obsidian move path="wiki/systems/foo.md" to="wiki/systems/bar.md"'},
        session_id=key,
        result='{"exit_code": 0}',
    )
    hermes_plugin._on_post_tool_call(
        tool_name="terminal",
        args={"command": 'obsidian edit path="wiki/systems/index.md" content="..."'},
        session_id=key,
        result='{"exit_code": 0}',
    )
    hermes_plugin._on_session_end(session_id=key)

    injected = hermes_plugin._on_pre_llm_call(session_id=key)

    assert injected is None or "parent index.md" not in injected["context"]


def test_session_end_uses_packaged_stop_hook_reasons(monkeypatch, provider, tmp_path):
    import hermes_plugin

    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    calls = []

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, reason: str):
            self.stdout = json.dumps({"decision": "block", "reason": reason})

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result(f"reason from {Path(cmd[-1]).name}")

    monkeypatch.setattr(hermes_plugin.subprocess, "run", fake_run)

    hermes_plugin._on_session_end(session_id="session-stop")
    injected = hermes_plugin._on_pre_llm_call(session_id="session-stop")

    assert injected is not None
    assert "reason from update-changelog.py" in injected["context"]
    assert "reason from remind-convos.py" in injected["context"]
    assert calls
    assert all(call[1]["cwd"] == str(tmp_path) for call in calls)


def test_session_finalize_keeps_stop_hooks_scoped_to_same_session(monkeypatch, provider, tmp_path):
    import hermes_plugin

    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))

    class Result:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"decision": "block", "reason": "finalize reminder"})

    monkeypatch.setattr(hermes_plugin.subprocess, "run", lambda *a, **k: Result())

    hermes_plugin._on_session_finalize(session_id="old-session")
    unrelated = hermes_plugin._on_pre_llm_call(session_id="new-session")
    injected = hermes_plugin._on_pre_llm_call(session_id="old-session")

    assert unrelated is None
    assert injected is not None
    assert "finalize reminder" in injected["context"]


def test_session_finalize_does_not_leak_pending_end_reminders_to_default_queue(
    monkeypatch, provider, tmp_path
):
    import hermes_plugin

    monkeypatch.setenv("OBSIDIAN_VAULT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        hermes_plugin,
        "_run_stop_hook_reasons",
        lambda session_id="": ["queued before finalize"] if session_id == "old-session" else [],
    )

    hermes_plugin._on_session_end(session_id="old-session")

    monkeypatch.setattr(hermes_plugin, "_run_stop_hook_reasons", lambda session_id="": [])
    hermes_plugin._on_session_finalize(session_id="old-session")
    unrelated = hermes_plugin._on_pre_llm_call(session_id="new-session")
    injected = hermes_plugin._on_pre_llm_call(session_id="old-session")

    assert unrelated is None
    assert injected is not None
    assert "queued before finalize" in injected["context"]
