"""Behavior tests for per-vault hook policy loading."""

import os
from pathlib import Path

import pytest
import yaml
from hookslib.vault_policy import find_containing_vault, load_vault_policy


def test_load_vault_policy_returns_defaults_when_config_is_absent():
    assert load_vault_policy().ai_readonly_folders == ()


def test_load_vault_policy_reads_shared_rules_and_observes_edits(monkeypatch):
    config = Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"])
    config.write_text("ai_readonly_folders: [Public]\n")
    assert load_vault_policy().ai_readonly_folders == ("Public",)
    config.write_text("ai_readonly_folders: [Archive]\n")
    assert load_vault_policy().ai_readonly_folders == ("Archive",)


def test_load_vault_policy_distinguishes_empty_from_invalid_yaml():
    config = Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"])
    config.write_text("")
    assert load_vault_policy().ai_readonly_folders == ()
    config.write_text("[unterminated")
    with pytest.raises(yaml.YAMLError):
        load_vault_policy()


def test_find_containing_vault_matches_root_and_descendants(tmp_path: Path):
    first = tmp_path / "vault"
    second = tmp_path / "vault-longer"
    roots = [str(first), str(second)]

    assert find_containing_vault(str(first), roots) == str(first)
    assert find_containing_vault(str(second / "wiki" / "note.md"), roots) == str(second)
    assert find_containing_vault(str(tmp_path / "outside.md"), roots) is None
