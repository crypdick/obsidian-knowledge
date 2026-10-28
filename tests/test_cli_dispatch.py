"""CLI parser dispatch contracts."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from lib.vault_index import cli
from lib.vault_index.cli import SearchTimeoutError
from lib.vault_index.models import IndexBusyError


def run_main(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["obsidian-knowledge", *arguments])
    return cli.main()


def test_main_lightweight_dispatches(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "setup", lambda vault, **kwargs: calls.append(("setup", vault, kwargs)))
    assert run_main(monkeypatch, "setup", "--vault", str(tmp_path), "--skip-claude-plugin") == 0
    assert calls[0][0] == "setup"
    assert calls[0][2] == {"skip_claude_plugin": True, "skip_guards": False}
    assert run_main(monkeypatch, "setup", "--vault", str(tmp_path), "--skip-guards") == 0
    assert calls[-1][2] == {"skip_claude_plugin": False, "skip_guards": True}

    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: tmp_path)
    monkeypatch.setattr(cli, "init_vault_index", lambda path: calls.append(("init", path)))
    assert run_main(monkeypatch, "init-vault-index") == 0
    assert calls[-1] == ("init", cli.preferences_path())

    monkeypatch.setattr(cli, "run_vault_file_command", lambda args, parser: 6)
    assert run_main(monkeypatch, "read", "note.md", "--vault", str(tmp_path)) == 6
    monkeypatch.setattr(cli, "run_papercut", lambda **kwargs: 5)
    assert run_main(monkeypatch, "papercut", "friction", "--vault", str(tmp_path)) == 5
    monkeypatch.setattr(cli, "run_retrieval_command", lambda args: 4)
    assert run_main(monkeypatch, "search", "query", "--vault", str(tmp_path)) == 4

    monkeypatch.setattr(cli, "run_hook_entrypoint", lambda *args, **kwargs: 3)
    assert run_main(monkeypatch, "_hook", "stop", "--kind", "capture-session") == 3
    assert capsys.readouterr().err == ""


def test_main_install_rules_success_and_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("lib.vault_index.guard_install.install_rules", lambda base: base / "rules.toml")
    monkeypatch.chdir(tmp_path)
    assert run_main(monkeypatch, "install-rules") == 0
    assert f"Installed i-insist rules: {tmp_path / 'rules.toml'}" in capsys.readouterr().out

    monkeypatch.setattr(
        "lib.vault_index.guard_install.install_rules",
        lambda _base: (_ for _ in ()).throw(OSError("read-only")),
    )
    assert run_main(monkeypatch, "install-rules", "--global") == 2
    assert "i-insist setup failed: read-only" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", ["success", "busy", "timeout"])
def test_main_reindex_outcomes(tmp_path, monkeypatch, capsys, outcome):
    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: tmp_path)
    monkeypatch.setattr(cli, "default_cache_dir_for_vault", lambda _vault: tmp_path / "cache")

    class Index:
        def __init__(self, **_kwargs):
            pass

        def full_reindex(self, *, force):
            if outcome == "busy":
                raise IndexBusyError("busy")
            if outcome == "timeout":
                raise SearchTimeoutError("slow")
            return SimpleNamespace(indexed=2, skipped=1, deleted=3)

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", Index)
    code = run_main(monkeypatch, "reindex", "--vault", str(tmp_path), "--force")
    assert code == {"success": 0, "busy": 0, "timeout": 124}[outcome]
    output = capsys.readouterr()
    expected = {"success": "Indexed: 2", "busy": "another index operation", "timeout": "timed out"}
    assert expected[outcome] in output.out + output.err


def test_reindex_progress_is_interactive_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: tmp_path)
    monkeypatch.setattr(cli, "default_cache_dir_for_vault", lambda _vault: tmp_path / "cache")
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    class Index:
        def __init__(self, **_kwargs):
            pass

        def full_reindex(self, *, force, progress):
            progress(0, 2)
            progress(2, 2)
            return SimpleNamespace(indexed=2, skipped=0, deleted=0)

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", Index)
    assert run_main(monkeypatch, "reindex", "--vault", str(tmp_path)) == 0
    output = capsys.readouterr()
    assert "2/2" in output.err
    assert "Reindexing" not in output.out
    assert "Indexed: 2" in output.out


def test_reindex_progress_throttles_and_handles_empty(capsys, monkeypatch):
    monkeypatch.setattr(cli.time, "monotonic", lambda: 1.0)
    progress = cli.ReindexProgress()
    progress.close()
    progress(0, 0)
    progress(1, 2)
    progress.close()
    output = capsys.readouterr().err
    assert "0/0" in output
    assert "1/2" not in output


@pytest.mark.parametrize("needs_rebuild", [False, True])
def test_search_deadline_interrupts_index_lock_wait(tmp_path, needs_rebuild):
    script = f"""
import fcntl, sys
import lib.vault_index.indexer as indexer
from lib.vault_index.cli import cli_main
from lib.vault_index.config import VaultIndexConfig
from pathlib import Path
vault = Path({str(tmp_path)!r})
instance = indexer.Indexer(vault, vault / 'cache', VaultIndexConfig(), skip_probe=True)
instance._needs_rebuild = {needs_rebuild!r}
indexer.Indexer = lambda *args, **kwargs: instance
lock = open(instance.cache_dir / '.index.sqlite.lock', 'w')
fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
sys.argv = ['obsidian-knowledge', 'search', 'query', '--vault', str(vault)]
cli_main()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 124, result.stderr
    assert "timed out" in result.stderr
    assert "Traceback" not in result.stderr
    assert "(no results)" not in result.stdout
