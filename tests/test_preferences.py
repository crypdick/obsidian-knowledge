"""Shared settings and host-local vault registration are independent."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from vault_preferences import load_preferences, preferences_path

from lib.vault_index.cli import resolve_vault
from lib.vault_index.config import load_config


def test_preferences_default_to_xdg_config_independently_of_registry(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_CONFIG")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(tmp_path / "host.yaml"))
    assert preferences_path() == tmp_path / "config/obsidian-knowledge/config.yaml"
    assert load_preferences().root == {}


def test_preferences_default_to_user_home_and_expand_override(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_CONFIG")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert preferences_path() == tmp_path / ".config/obsidian-knowledge/config.yaml"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CONFIG", "~/synced/preferences.yaml")
    assert preferences_path() == tmp_path / "synced/preferences.yaml"


@pytest.mark.parametrize("content", [None, "", "{}", "# preferences\n"])
def test_absent_or_empty_preferences_use_defaults(tmp_path, content):
    config = tmp_path / "shared.yaml"
    if content is not None:
        config.write_text(content)
    assert load_preferences(config).root == {}


@pytest.mark.parametrize("content", ["- invalid", "vaults: [/host/vault]"])
def test_preferences_reject_non_mappings_and_host_locations(tmp_path, content):
    config = tmp_path / "shared.yaml"
    config.write_text(content)
    with pytest.raises(ValidationError):
        load_preferences(config)


def test_malformed_preferences_are_not_ignored(tmp_path):
    config = tmp_path / "shared.yaml"
    config.write_text("[unterminated")
    with pytest.raises(yaml.YAMLError):
        load_preferences(config)


def test_registry_change_does_not_change_shared_search_preferences(tmp_path, monkeypatch):
    config = Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"])
    config.write_text("vault_index:\n  top_k: 17\n")
    original = config.read_bytes()
    registry = tmp_path / "host.yaml"
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(registry))
    for name in ("host-a-vault", "host-b-vault"):
        vault = tmp_path / name
        vault.mkdir()
        registry.write_text(f"vaults: [{vault}]\n")
        assert resolve_vault(None, cwd=tmp_path) == vault
        assert load_config().top_k == 17
    assert config.read_bytes() == original
