"""Cache producers and consumers must choose the same identity."""

from pathlib import Path

import pytest

from lib.vault_index import cache_paths
from lib.vault_index.cli import default_cache_dir_for_vault
from lib.vault_index.indexer import default_cache_dir


@pytest.mark.parametrize("restricted", [False, True])
def test_locator_agrees_across_readers_and_writers(tmp_path, monkeypatch, restricted):
    preferred = tmp_path / "missing" / "parents" / "cache"
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", raising=False)
    monkeypatch.setattr(cache_paths.platformdirs, "user_cache_dir", lambda _name: str(preferred))
    monkeypatch.setattr(cache_paths.os, "access", lambda _path, _mode: not restricted)
    vault = tmp_path / "vault"
    selected = default_cache_dir(vault)
    assert selected == default_cache_dir_for_vault(vault)
    expected_base = Path("/tmp/obsidian-knowledge-cache/obsidian-knowledge") if restricted else preferred
    assert selected.parent == expected_base
    assert not preferred.exists()  # inspection never creates a cache


def test_explicit_cache_location_does_not_silently_fall_back(tmp_path, monkeypatch):
    override = tmp_path / "explicit"
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(override))
    monkeypatch.setattr(cache_paths.os, "access", lambda _path, _mode: False)
    assert default_cache_dir(tmp_path).parent == override / "obsidian-knowledge"
    assert default_cache_dir(tmp_path) == default_cache_dir_for_vault(tmp_path)
