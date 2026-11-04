"""Behavior tests for vault root matching."""

from pathlib import Path

from hookslib.vault_config import matching_vault_root


def test_matching_vault_root_matches_root_and_descendants(tmp_path: Path):
    first = tmp_path / "vault"
    second = tmp_path / "vault-longer"
    roots = [str(first), str(second)]

    assert matching_vault_root(str(first), roots) == str(first)
    assert matching_vault_root(str(second / "wiki" / "note.md"), roots) == str(second)
    assert matching_vault_root(str(tmp_path / "outside.md"), roots) is None
