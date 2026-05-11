"""Shared test fixtures for obsidian-knowledge plugin hooks."""
import os
import sys
from pathlib import Path

import pytest

# Make hooks and hermes_plugin importable
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
# hermes_plugin/ lives at the repo root — insert root so `import hermes_plugin` works
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture(autouse=True)
def _disable_ollama_probe(monkeypatch):
    """Force Indexer to skip the live Ollama probe in tests.

    Returns (False, "test-stub: probe disabled") so vector_enabled flips off
    and tests stay FTS-only without 1.5s timeouts per construction.
    """
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (False, "test-stub: probe disabled"),
    )


@pytest.fixture(autouse=True)
def _isolated_user_cache(tmp_path_factory, monkeypatch):
    """Redirect `platformdirs.user_cache_dir` into a per-session tmp dir.

    Without this, any test that calls `default_cache_dir(vault_root)` writes
    into the real user cache (`~/.cache/obsidian-knowledge/` on Linux,
    `~/Library/Caches/obsidian-knowledge/` on macOS), leaking pytest tmp
    paths into production state. Discovered 2026-05-11 after finding an
    orphan `vault-a34e8ad8/` dir from `tmp_path/"vault"` fixtures.
    """
    fake_cache = tmp_path_factory.mktemp("user_cache")
    monkeypatch.setattr(
        "lib.vault_index.indexer.platformdirs.user_cache_dir",
        lambda app_name: str(fake_cache / app_name),
    )


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
