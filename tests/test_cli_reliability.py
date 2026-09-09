"""Regression checks for first-run, offline, and malformed-input failures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lib.vault_index.cli import (
    SearchTimeoutError,
    init_vault_index,
    link_hermes_memories,
    run_search_doctor,
    setup,
)
from lib.vault_index.config import load_config
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


def test_setup_reports_claude_install_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(tmp_path / "vaults.yaml"))
    monkeypatch.setattr("shutil.which", lambda _: "/bin/claude")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("subprocess.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        setup(tmp_path)


def test_link_preflights_both_memories_and_resolves_relative_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    for name in ("MEMORY.md", "USER.md"):
        (source / name).write_text("fixture")
    destination = tmp_path / "Utility/obsidian-knowledge/hermes"
    destination.mkdir(parents=True)
    (destination / "USER.md").write_text("existing user memory")
    with pytest.raises(FileExistsError):
        link_hermes_memories(tmp_path, Path("source"))
    assert not (destination / "MEMORY.md").exists()
    assert (destination / "USER.md").read_text() == "existing user memory"
    (destination / "USER.md").unlink()
    link_hermes_memories(tmp_path, Path("source"))
    assert (destination / "MEMORY.md").read_text() == "fixture"
    assert (destination / "USER.md").read_text() == "fixture"


def test_link_missing_source_leaves_no_partial_links(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "MEMORY.md").write_text("fixture")
    with pytest.raises(FileNotFoundError):
        link_hermes_memories(tmp_path, source)
    assert not (tmp_path / "Utility").exists()


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
