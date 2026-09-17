"""CLI parser dispatch contracts."""

from __future__ import annotations

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

    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: tmp_path)
    monkeypatch.setattr(cli, "init_vault_index", lambda path: calls.append(("init", path)))
    assert run_main(monkeypatch, "init-vault-index", "--vault", str(tmp_path)) == 0
    assert calls[-1] == ("init", tmp_path / ".claude/obsidian-knowledge.yaml")

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
