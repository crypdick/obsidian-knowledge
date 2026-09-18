"""Behavior tests for per-vault hook policy loading."""

from pathlib import Path

import pytest
import yaml
from hookslib.vault_policy import find_containing_vault, load_vault_policy


def test_load_vault_policy_returns_empty_when_config_is_absent(tmp_path: Path):
    assert load_vault_policy(str(tmp_path)) == {}


def test_load_vault_policy_loads_and_caches_mapping(tmp_path: Path):
    config = tmp_path / ".claude" / "obsidian-knowledge.yaml"
    config.parent.mkdir()
    config.write_text("publishable_zones:\n  - wiki\n")

    assert load_vault_policy(str(tmp_path)) == {"publishable_zones": ["wiki"]}

    config.write_text("publishable_zones:\n  - Journal\n")
    assert load_vault_policy(str(tmp_path)) == {"publishable_zones": ["wiki"]}


def test_load_vault_policy_distinguishes_empty_from_invalid_yaml(tmp_path: Path):
    empty_vault = tmp_path / "empty"
    invalid_vault = tmp_path / "invalid"
    for vault, content in ((empty_vault, ""), (invalid_vault, "[unterminated")):
        config = vault / ".claude" / "obsidian-knowledge.yaml"
        config.parent.mkdir(parents=True)
        config.write_text(content)

    assert load_vault_policy(str(empty_vault)) == {}
    with pytest.raises(yaml.YAMLError):
        load_vault_policy(str(invalid_vault))


def test_find_containing_vault_matches_root_and_descendants(tmp_path: Path):
    first = tmp_path / "vault"
    second = tmp_path / "vault-longer"
    roots = [str(first), str(second)]

    assert find_containing_vault(str(first), roots) == str(first)
    assert find_containing_vault(str(second / "wiki" / "note.md"), roots) == str(second)
    assert find_containing_vault(str(tmp_path / "outside.md"), roots) is None
