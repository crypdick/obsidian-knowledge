"""Regression checks for first-run, offline, and malformed-input failures."""

from __future__ import annotations

import errno
import io
import os
import subprocess
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from lib.vault_index import cli
from lib.vault_index.cli import (
    SearchTimeoutError,
    init_vault_index,
    run_search_doctor,
    setup,
)
from lib.vault_index.config import load_config
from lib.vault_index.models import Hit, IndexBusyError
from lib.vault_index.registration import register_vault


def test_registry_handles_prefix_paths_other_keys_and_no_final_newline(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults: ['{vault}-old']\nother: preserved")
    assert register_vault(vault, registry)
    data = yaml.safe_load(registry.read_text())
    assert data == {"vaults": [str(vault) + "-old", str(vault)], "other": "preserved"}
    before = registry.read_bytes()
    assert not register_vault(vault / ".", registry)
    assert registry.read_bytes() == before


@pytest.mark.parametrize("content", ["[", "[]", "false", "vaults: wrong", "vaults: [null]"])
def test_invalid_registry_is_not_modified(tmp_path, content):
    registry = tmp_path / "vaults.yaml"
    registry.write_text(content)
    with pytest.raises((ValueError, yaml.YAMLError)):
        register_vault(tmp_path, registry)
    assert registry.read_text() == content


@pytest.mark.parametrize("content", ["[]", "false", "some string", "42"])
def test_invalid_config_shape_is_rejected(tmp_path, content):
    config = tmp_path / "config.yaml"
    config.write_text(content)
    for operation in (init_vault_index, load_config):
        with pytest.raises(ValueError, match="YAML mapping"):
            operation(config)
    assert config.read_text() == content


def test_setup_rejects_missing_vault_before_registration(tmp_path, monkeypatch):
    registry = tmp_path / "vaults.yaml"
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    with pytest.raises(ValueError, match="vault does not exist"):
        setup(tmp_path / "missing", skip_claude_plugin=True)
    assert not registry.exists()


def test_registration_rejects_file_as_vault(tmp_path):
    vault = tmp_path / "not-a-vault"
    vault.write_text("file")
    with pytest.raises(ValueError, match="vault is not a directory"):
        register_vault(vault, tmp_path / "vaults.yaml")


def test_setup_reports_claude_install_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(tmp_path / "vaults.yaml"))
    monkeypatch.setattr("shutil.which", lambda _: "/bin/claude")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("subprocess.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup(tmp_path)


def test_lightweight_cli_import_does_not_load_retrieval_stack():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import lib.vault_index.cli; assert 'memweave' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_litellm_import_needs_no_public_network():
    script = """
import os, socket
os.environ.pop('LITELLM_LOCAL_MODEL_COST_MAP', None)
attempts = []
def deny(*args, **kwargs):
    attempts.append(args)
    raise OSError('network disabled by regression test')
socket.socket.connect = deny
socket.getaddrinfo = deny
import lib.vault_index.indexer
import litellm
assert not attempts, attempts
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", ["search", "remember", "doctor", "reindex", "setup"])
def test_deadline_includes_index_initialization(tmp_path, command):
    args = [command, "--vault", str(tmp_path)]
    if command in {"search", "remember"}:
        args.append("query")
    if command in {"setup", "reindex"}:
        args += ["--timeout-seconds", "1"]
    if command == "setup":
        args.append("--skip-claude-plugin")
    script = f"""
import sys, time
import lib.vault_index.indexer as indexer
from lib.vault_index.cli import cli_main
import lib.vault_index.guard_install as guards
guards.install_rules = lambda base: base / ".i-insist/obsidian-knowledge.toml"
def stall(*args, **kwargs):
    time.sleep(30)
indexer.Indexer = stall
sys.argv = ['obsidian-knowledge', *{args!r}]
cli_main()
"""
    env = {
        **os.environ,
        "OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS": "1",
        "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(tmp_path / "registry.yaml"),
        "OBSIDIAN_KNOWLEDGE_CACHE_ROOT": str(tmp_path / "cache"),
    }
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 124, result.stderr
    assert "timed out" in result.stderr
    assert "Traceback" not in result.stderr


def test_doctor_does_not_swallow_deadline(tmp_path):
    class StalledIndex:
        def row_count(self):
            raise SearchTimeoutError("doctor exceeded TTL")

    with pytest.raises(SearchTimeoutError):
        run_search_doctor(vault=tmp_path, cache=tmp_path, idx=StalledIndex())


@pytest.mark.parametrize("command", ["init-vault-index", "reindex", "search", "doctor"])
def test_cli_invalid_vault_has_concise_error(tmp_path, command):
    args = [command, "--vault", str(tmp_path / "missing")]
    if command == "search":
        args.append("query")
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "vault does not exist" in result.stderr
    assert "Traceback" not in result.stderr


def test_timeout_configuration_and_disabled_deadline(monkeypatch):
    monkeypatch.delenv(cli.SEARCH_TTL_ENV, raising=False)
    assert cli.search_ttl_seconds() == 30
    monkeypatch.setenv(cli.SEARCH_TTL_ENV, "nonsense")
    assert cli.search_ttl_seconds() == 30
    monkeypatch.setenv(cli.SEARCH_TTL_ENV, "7")
    assert cli.search_ttl_seconds() == 7
    with cli.search_ttl(0):
        pass


def test_search_ttl_restores_existing_alarm(monkeypatch):
    alarms = []
    handlers = []
    monkeypatch.setattr(cli.signal, "getsignal", lambda _signal: "old-handler")
    monkeypatch.setattr(
        cli.signal,
        "alarm",
        lambda seconds: alarms.append(seconds) or (4 if seconds == 0 and len(alarms) == 1 else 0),
    )
    monkeypatch.setattr(cli.signal, "signal", lambda sig, handler: handlers.append((sig, handler)))
    with cli.search_ttl(2):
        assert alarms[-1] == 2
    assert alarms[-2:] == [0, 4]
    assert handlers[-1] == (cli.signal.SIGALRM, "old-handler")


def test_search_ttl_watchdog_reports_and_hard_exits(monkeypatch, capsys):
    class ExpiredEvent:
        def wait(self, _seconds):
            return False

        def set(self):
            pass

    class InlineThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            with pytest.raises(SystemExit, match="124"):
                self.target()

    monkeypatch.setattr(cli.threading, "Event", ExpiredEvent)
    monkeypatch.setattr(cli.threading, "Thread", InlineThread)
    monkeypatch.setattr(cli.os, "_exit", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.delattr(cli.signal, "SIGALRM")
    with cli.search_ttl(1, label="probe"):
        pass
    assert "probe: hard timeout after 6s" in capsys.readouterr().err


def test_resolve_vault_without_registry_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv(cli.VAULTS_CONFIG_ENV, str(tmp_path / "missing.yaml"))
    assert cli.resolve_vault(None, tmp_path) == tmp_path.resolve()
    assert cli.vaults_config_path() == tmp_path / "missing.yaml"
    monkeypatch.delenv(cli.VAULTS_CONFIG_ENV)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert cli.vaults_config_path() == tmp_path / ".config/obsidian-knowledge/vaults.yaml"


def test_default_cache_uses_platform_path_when_writable(tmp_path, monkeypatch):
    base = tmp_path / "cache" / cli.APP_NAME
    base.mkdir(parents=True)
    monkeypatch.delenv(cli.CACHE_ROOT_ENV, raising=False)
    monkeypatch.setattr(cli.platformdirs, "user_cache_dir", lambda _name: str(base))
    assert cli._cache_base_dir() == base


def test_empty_candidate_format_and_missing_hook(tmp_path, monkeypatch):
    assert cli.format_remember_candidates([]).endswith("(no candidates)")
    monkeypatch.setattr(cli, "package_root", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="hook script not found"):
        cli.hook_script_path("missing.py")

    monkeypatch.undo()
    assert cli.hook_script_path("i_insist.py").is_file()


@pytest.mark.parametrize(
    ("event", "kind"),
    [("stop", None), ("pre-tool-use", "missing")],
)
def test_hook_entrypoint_rejects_unsupported_dispatch(event, kind, capsys):
    assert cli.run_hook_entrypoint(event, kind) == 2
    assert "unsupported hook event/kind" in capsys.readouterr().err


def test_hook_entrypoint_forwards_output_and_agent(tmp_path, monkeypatch, capsys):
    script = tmp_path / "hook.py"
    script.write_text("")
    observed = {}
    monkeypatch.setattr(cli, "hook_script_path", lambda _name: script)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(read=lambda: "payload"))

    def run(command, **kwargs):
        observed.update(command=command, kwargs=kwargs)
        return SimpleNamespace(stdout="out", stderr="err", returncode=7)

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.run_hook_entrypoint("session-start", agent="codex") == 7
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("out", "err")
    assert observed["kwargs"]["env"]["OBSIDIAN_KNOWLEDGE_HOOK_AGENT"] == "codex"


def test_setup_reports_existing_registration_no_claude_and_busy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "register_vault", lambda *_args: False)
    monkeypatch.setattr(cli, "vaults_config_path", lambda: tmp_path / "vaults.yaml")
    monkeypatch.setattr("lib.vault_index.guard_install.install_rules", lambda _home: tmp_path / "rules")
    monkeypatch.setattr("shutil.which", lambda _name: None)

    class BusyIndexer:
        vector_enabled = False
        vector_status = "offline"

        def __init__(self, **_kwargs):
            pass

        def full_reindex(self, **_kwargs):
            raise IndexBusyError("busy")

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", BusyIndexer)
    monkeypatch.setattr("lib.vault_index.indexer.default_cache_dir", lambda _vault: tmp_path / "cache")
    cli.setup(tmp_path)
    output = capsys.readouterr().out
    assert "already registered" in output
    assert "claude: not found" in output
    assert "keyword-only (offline)" in output
    assert "another index operation" in output


@pytest.mark.parametrize("plugin_mode", ["skip", "install"])
def test_setup_success_modes(tmp_path, monkeypatch, capsys, plugin_mode):
    calls = []
    monkeypatch.setattr(cli, "register_vault", lambda *_args: True)
    monkeypatch.setattr(cli, "vaults_config_path", lambda: tmp_path / "vaults.yaml")
    monkeypatch.setattr("lib.vault_index.guard_install.install_rules", lambda _home: tmp_path / "rules")
    monkeypatch.setattr("shutil.which", lambda _name: "/bin/claude")
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **_kwargs: calls.append(command))

    class HealthyIndexer:
        vector_enabled = True
        vector_status = "ok"

        def __init__(self, **_kwargs):
            pass

        def full_reindex(self, **_kwargs):
            return SimpleNamespace(indexed=2, skipped=1, deleted=0)

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", HealthyIndexer)
    monkeypatch.setattr("lib.vault_index.indexer.default_cache_dir", lambda _vault: tmp_path / "cache")
    cli.setup(tmp_path, skip_claude_plugin=plugin_mode == "skip")
    output = capsys.readouterr().out
    assert "Indexed: 2, Skipped: 1, Deleted: 0" in output
    assert "Setup complete" in output
    assert len(calls) == (0 if plugin_mode == "skip" else 2)


@pytest.mark.parametrize("error_number", [None, errno.EROFS])
def test_papercut_write_errors(tmp_path, monkeypatch, capsys, error_number):
    def fail(*_args):
        raise OSError(error_number, "denied")

    monkeypatch.setattr("lib.vault_index.papercuts.record_papercut", fail)
    assert cli.run_papercut(vault=tmp_path, description="friction", parser=ArgumentParser()) == 1
    error = capsys.readouterr().err
    assert "could not complete vault log write" in error
    assert ("vault write access is required" in error) == (error_number == 30)


def test_papercut_success_and_validation(tmp_path, monkeypatch, capsys):
    note = tmp_path / "papercuts.md"
    monkeypatch.setattr(
        "lib.vault_index.papercuts.record_papercut", lambda *_args: SimpleNamespace(path=note)
    )
    assert cli.run_papercut(vault=tmp_path, description="friction", parser=ArgumentParser()) == 0
    assert "Logged papercut: papercuts.md" in capsys.readouterr().out
    monkeypatch.setattr(
        "lib.vault_index.papercuts.record_papercut", lambda *_args: (_ for _ in ()).throw(ValueError("blank"))
    )
    with pytest.raises(SystemExit):
        cli.run_papercut(vault=tmp_path, description="", parser=ArgumentParser())


@pytest.mark.parametrize("command", ["search", "remember", "doctor"])
def test_retrieval_commands_report_public_results(tmp_path, monkeypatch, capsys, command):
    class Index:
        vector_enabled = False
        vector_status = "offline"
        _vector_enabled = False

        def __init__(self, **_kwargs):
            pass

        def row_count(self):
            return 1

        def search(self, *_args, **_kwargs):
            return [] if command == "search" else [Hit(path="wiki/note.md", score=2.0)]

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", Index)
    monkeypatch.setattr("lib.vault_index.indexer.default_cache_dir", lambda _vault: tmp_path / "cache")
    args = Namespace(
        cmd=command,
        vault=tmp_path,
        queries=["known"],
        top_k=2,
        digest_only=True,
        query="q",
        memory="m",
        all=True,
    )
    code = cli.run_retrieval_command(args)
    output = capsys.readouterr()
    assert code == 0
    assert {"search": "(no results)", "remember": "Potential homes:", "doctor": "status: PASS"}[
        command
    ] in output.out
    if command != "doctor":
        assert "ranking degraded (offline)" in output.err


def test_doctor_empty_rows_and_search_timeout(tmp_path):
    class EmptyIndex:
        _vector_enabled = True
        vector_status = "ok"

        def row_count(self):
            return 0

        def search(self, *_args, **_kwargs):
            raise SearchTimeoutError("slow")

    with pytest.raises(SearchTimeoutError, match="slow"):
        cli.run_search_doctor(vault=tmp_path, cache=tmp_path, idx=EmptyIndex(), queries=["q"])


def test_retrieval_with_healthy_vector_index(tmp_path, monkeypatch, capsys):
    class HealthyIndex:
        vector_enabled = True

        def __init__(self, **_kwargs):
            pass

        def search(self, *_args, **_kwargs):
            return [Hit(path="wiki/note.md", score=2.0)]

    monkeypatch.setattr("lib.vault_index.indexer.Indexer", HealthyIndex)
    monkeypatch.setattr("lib.vault_index.indexer.default_cache_dir", lambda _vault: tmp_path / "cache")
    args = Namespace(cmd="search", vault=tmp_path, query="q", top_k=1, all=False)
    assert cli.run_retrieval_command(args) == 0
    output = capsys.readouterr()
    assert "wiki/note.md" in output.out
    assert output.err == ""


def test_empty_yaml_is_extended(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("")
    cli.init_vault_index(config)
    assert "vault_index:" in config.read_text()


def test_positive_int_contract():
    assert cli.positive_int("2") == 2
    with pytest.raises(Exception, match="positive integer"):
        cli.positive_int("0")


def test_exit_and_cli_main_error_mapping(monkeypatch, capsys):
    exits = []
    monkeypatch.setattr(cli.os, "_exit", exits.append)
    cli._exit_hard(3)
    assert exits == [3]
    monkeypatch.setattr(cli, "main", lambda: (_ for _ in ()).throw(SearchTimeoutError("slow")))
    cli.cli_main()
    assert exits[-1] == 124
    assert "timed out (slow)" in capsys.readouterr().err
    monkeypatch.setattr(cli, "main", lambda: (_ for _ in ()).throw(ValueError("bad input")))
    cli.cli_main()
    assert exits[-1] == 2
    assert "bad input" in capsys.readouterr().err
    monkeypatch.setattr(cli, "main", lambda: (_ for _ in ()).throw(RuntimeError("unexpected")))
    cli.cli_main()
    assert exits[-1] == 1
    assert "RuntimeError: unexpected" in capsys.readouterr().err


def test_vault_file_commands_read_write_and_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: tmp_path)
    monkeypatch.setattr(cli, "read_vault_file", lambda *_args: b"contents")
    read_args = Namespace(cmd="read", vault=tmp_path, path=Path("note.md"))
    assert cli.run_vault_file_command(read_args, ArgumentParser()) == 0
    assert capsys.readouterr().out == "contents"

    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"new")))
    monkeypatch.setattr(cli, "write_vault_file", lambda *_args, **_kwargs: tmp_path / "note.md")
    write_args = Namespace(cmd="write", vault=tmp_path, path=Path("note.md"), replace=True)
    assert cli.run_vault_file_command(write_args, ArgumentParser()) == 0
    assert "Wrote and verified" in capsys.readouterr().out

    monkeypatch.setattr(cli, "resolve_vault", lambda _vault: (_ for _ in ()).throw(ValueError("bad vault")))
    with pytest.raises(SystemExit):
        cli.run_vault_file_command(read_args, ArgumentParser())
