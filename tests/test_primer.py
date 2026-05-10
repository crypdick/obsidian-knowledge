"""Tests for build_primer."""
from pathlib import Path

from lib.vault_index.primer import build_primer


def test_build_primer_mentions_vault_root(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert str(tmp_path) in text


def test_build_primer_mentions_wiki_path(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert "wiki" in text.lower()


def test_build_primer_mentions_improve_harness(tmp_path: Path):
    text = build_primer(vault_root=tmp_path, plugin_root=tmp_path / "plugin")
    assert "/improve-harness" in text
