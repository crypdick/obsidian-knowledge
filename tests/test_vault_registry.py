"""Tests for dependency-light standalone-hook vault registry loading."""

from pathlib import Path

from vault_registry import load_vault_roots


def test_vault_registry_missing_or_malformed_file_yields_no_roots(tmp_path: Path):
    assert load_vault_roots(tmp_path / "missing.yaml") == []

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("vaults: [unterminated")
    assert load_vault_roots(malformed) == []


def test_vault_registry_normalizes_valid_roots(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    registry = tmp_path / "vaults.yaml"
    registry.write_text(f"vaults:\n  - {vault / '..' / 'vault'}\n")

    assert load_vault_roots(registry) == [str(vault.resolve())]
