"""Tests for build_primer."""

import sys
from pathlib import Path

import pytest
from hookslib.primer import KNOWLEDGE_BASE_INDEX_MAX_CHARS, build_primer
from hookslib.repo_memory import MemoryTarget


def test_build_primer_mentions_vault_root(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)
    assert str(tmp_path) in text


def test_build_primer_mentions_wiki_path(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)
    assert "wiki" in text.lower()


def test_build_primer_anchors_utility_outside_wiki(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)

    assert f"Vault root: {tmp_path}/" in text
    assert f"Plugin state: {tmp_path / 'Utility' / 'obsidian-knowledge'}/" in text
    assert "Never create `wiki/Utility/`" in text


def test_build_primer_instructs_agents_to_log_papercuts(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)

    assert "obsidian-knowledge papercut" in text
    assert "/improve-harness" not in text


def test_build_primer_defers_access_recovery_to_skill(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)

    assert "obsidian-knowledge skill" in text
    assert "references/access-errors.md" in text
    assert "Ollama" not in text
    assert "EPERM" not in text
    assert "EACCES" not in text


def test_build_primer_routes_write_guidance_before_writing(tmp_path: Path):
    text = build_primer(vault_root=tmp_path)

    assert "obsidian-knowledge skill" in text
    assert "remember-conversations" not in text
    assert "Before writing" in text
    assert "operational notes" in text
    assert "category 15" not in text
    assert "at most 20 bullets or 6000 characters" not in text
    assert "before non-trivial answers" not in text
    assert "~/.codex/memories/" in text


def test_build_primer_injects_knowledge_base_index_with_cap(tmp_path: Path):
    index = tmp_path / "wiki" / "systems" / "knowledge-base" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("# Knowledge Base\n\n[[agent-operating-profile]]")

    text = build_primer(vault_root=tmp_path)

    assert "Knowledge-base memory index" in text
    assert "[[agent-operating-profile]]" in text
    assert f"capped at {KNOWLEDGE_BASE_INDEX_MAX_CHARS} chars" in text


def test_build_primer_truncates_large_knowledge_base_index(tmp_path: Path):
    index = tmp_path / "wiki" / "systems" / "knowledge-base" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("x" * (KNOWLEDGE_BASE_INDEX_MAX_CHARS + 100))

    text = build_primer(vault_root=tmp_path)

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
    monkeypatch.setattr("hookslib.primer.resolve_target", lambda _cwd: target)

    text = build_primer(vault_root=tmp_path)

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
    monkeypatch.setattr("hookslib.primer.resolve_target", lambda _cwd: target)

    text = build_primer(vault_root=tmp_path)

    assert f"Read {memory_file} at session start" in text
    assert "No MEMORY.md exists yet" not in text


def test_build_primer_uses_canonical_module_without_path_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hooks_dir = str(Path(__file__).parents[1] / "hooks")
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != hooks_dir])

    text = build_primer(vault_root=tmp_path, cwd=str(tmp_path))

    assert hooks_dir not in sys.path
    assert "Agent memory for this host" in text
