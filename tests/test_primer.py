"""Tests for build_primer."""

from pathlib import Path

import pytest
from hookslib.repo_memory import MemoryTarget

from lib.vault_index.primer import KNOWLEDGE_BASE_INDEX_MAX_CHARS, build_primer


def test_build_primer_mentions_vault_root(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert str(tmp_path) in text


def test_build_primer_mentions_wiki_path(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert "wiki" in text.lower()


def test_build_primer_instructs_agents_to_log_papercuts(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    assert "obsidian-knowledge papercut" in text
    assert "/improve-harness" not in text


def test_build_primer_keeps_capture_and_memory_selective(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    assert "durable, novel delta" in text
    assert "filing nothing as success" in text
    assert "Never store PIDs, job IDs" in text
    assert "Every saved note must be hermetic" in text
    assert "category 15" in text
    assert "at most 20 bullets or 6000 characters" in text
    assert "Do not create a second generated memory/index.md" in text


def test_build_primer_injects_knowledge_base_index_with_cap(tmp_path: Path):
    index = tmp_path / "wiki" / "systems" / "knowledge-base" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("# Knowledge Base\n\n[[hermes-agent-operating-profile]]")

    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    assert "Knowledge-base memory index" in text
    assert "[[hermes-agent-operating-profile]]" in text
    assert f"capped at {KNOWLEDGE_BASE_INDEX_MAX_CHARS} chars" in text


def test_build_primer_truncates_large_knowledge_base_index(tmp_path: Path):
    index = tmp_path / "wiki" / "systems" / "knowledge-base" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("x" * (KNOWLEDGE_BASE_INDEX_MAX_CHARS + 100))

    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    injected = text.split("Knowledge-base memory index", 1)[1]

    assert "[truncated — open the vault note for the full index]" in injected
    assert len(injected) < KNOWLEDGE_BASE_INDEX_MAX_CHARS + 500


def test_build_primer_treats_missing_repo_memory_as_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = MemoryTarget(
        kind="repo",
        rel_path="repos/acme/project/memory",
        owner="acme",
        repo="project",
        hostname=None,
        remote_url="git@github.com:acme/project.git",
    )
    monkeypatch.setattr("lib.vault_index.primer._resolve_memory_target", lambda _cwd: target)

    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    assert "No MEMORY.md exists yet" in text
    assert "treat repo memory as empty" in text
    assert "Do not report its absence as a papercut" in text


def test_build_primer_reads_existing_repo_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = MemoryTarget(
        kind="repo",
        rel_path="repos/acme/project/memory",
        owner="acme",
        repo="project",
        hostname=None,
        remote_url="git@github.com:acme/project.git",
    )
    memory_file = tmp_path / "wiki" / target.rel_path / "MEMORY.md"
    memory_file.parent.mkdir(parents=True)
    memory_file.write_text("- durable fact\n")
    monkeypatch.setattr("lib.vault_index.primer._resolve_memory_target", lambda _cwd: target)

    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")

    assert f"Read {memory_file} at session start" in text
    assert "No MEMORY.md exists yet" not in text
