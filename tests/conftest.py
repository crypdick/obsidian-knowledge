"""Shared test fixtures for obsidian-knowledge plugin hooks."""
import json
import os
import sys
from pathlib import Path

import pytest

# Make hooks importable
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a fake vault root with required structure."""
    vault = tmp_path / "vault"
    (vault / "wiki" / "systems" / "repos").mkdir(parents=True)
    return vault


@pytest.fixture
def tmp_claude_projects(tmp_path):
    """Create a fake ~/.claude/projects dir."""
    projects = tmp_path / "claude" / "projects"
    projects.mkdir(parents=True)
    return projects


@pytest.fixture
def tmp_vaults_yaml(tmp_path, monkeypatch, tmp_vault):
    """Create vaults.yaml pointing to tmp_vault and patch CONFIG_PATH."""
    config_dir = tmp_path / "config" / "obsidian-knowledge"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "vaults.yaml"
    config_file.write_text(f"vaults:\n  - {tmp_vault}\n")
    monkeypatch.setattr(
        "lib.vault_config.CONFIG_PATH", config_file
    )
    return config_file
