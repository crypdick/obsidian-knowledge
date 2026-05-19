"""Tests for build_primer."""
from pathlib import Path

from lib.vault_index.primer import KNOWLEDGE_BASE_INDEX_MAX_CHARS, build_primer


def test_build_primer_mentions_vault_root(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert str(tmp_path) in text


def test_build_primer_mentions_wiki_path(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert "wiki" in text.lower()


def test_build_primer_mentions_improve_harness(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert "/improve-harness" in text


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
