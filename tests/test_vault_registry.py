"""Tests for dependency-light standalone-hook vault registry loading."""

from pathlib import Path

import pytest
import yaml
from vault_registry import load_vault_roots


def test_vault_registry_distinguishes_missing_from_malformed_file(tmp_path: Path):
    assert load_vault_roots(tmp_path / "missing.yaml") == []

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("vaults: [unterminated")
    with pytest.raises(yaml.YAMLError):
        load_vault_roots(malformed)


def test_vault_registry_normalizes_valid_roots(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults:\n  - {vault / '..' / 'vault'}\n")

    assert load_vault_roots(registry) == [str(vault.resolve())]


@pytest.mark.parametrize("content", ["", "{}", "write_command: [example]", "vaults: []"])
def test_empty_and_partial_registry_agree_across_adapters(tmp_path, monkeypatch, content):
    from hookslib import vault_config

    from lib.vault_index.cli import load_configured_vaults, vaults_config_path

    registry = tmp_path / "vaults.yaml"
    registry.write_text(content)
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    assert vaults_config_path() == registry
    assert load_vault_roots() == vault_config.load_vault_roots() == load_configured_vaults() == []
