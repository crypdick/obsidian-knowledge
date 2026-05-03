"""Shared test fixtures for obsidian-knowledge plugin hooks."""
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


@pytest.fixture
def subprocess_vault(tmp_path):
    """Set up a vault discoverable by subprocess hooks via HOME override.

    Returns (vault_path, env) where env can be passed to subprocess.run
    to make the hook resolve `~/.config/obsidian-knowledge/vaults.yaml`
    against the temp HOME.
    """
    home = tmp_path / "home"
    home.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = home / ".config" / "obsidian-knowledge"
    cfg.mkdir(parents=True)
    (cfg / "vaults.yaml").write_text(f"vaults:\n  - {vault}\n")
    env = {**os.environ, "HOME": str(home)}
    return vault, env
