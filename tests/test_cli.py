"""Tests for the obsidian-knowledge CLI."""
import shutil
import subprocess
import sys
from pathlib import Path

from lib.vault_index.cli import init_vault_index, link_hermes_memories


# ---------------------------------------------------------------------------
# Task 10 — init-vault-index
# ---------------------------------------------------------------------------


def test_init_vault_index_creates_template(tmp_path: Path):
    yaml_path = tmp_path / ".claude" / "obsidian-knowledge.yaml"
    yaml_path.parent.mkdir()
    init_vault_index(yaml_path)
    assert yaml_path.exists()
    text = yaml_path.read_text()
    assert "vault_index:" in text
    assert "deny_regex" in text


def test_init_vault_index_preserves_existing_yaml(tmp_path: Path):
    yaml_path = tmp_path / ".claude" / "obsidian-knowledge.yaml"
    yaml_path.parent.mkdir()
    yaml_path.write_text("ai_managed:\n  - wiki\n")
    init_vault_index(yaml_path)
    text = yaml_path.read_text()
    assert "ai_managed:" in text
    assert "vault_index:" in text


def test_init_vault_index_does_not_clobber_existing_section(tmp_path: Path):
    yaml_path = tmp_path / ".claude" / "obsidian-knowledge.yaml"
    yaml_path.parent.mkdir()
    yaml_path.write_text("vault_index:\n  top_k: 99\n")
    init_vault_index(yaml_path)
    text = yaml_path.read_text()
    assert "top_k: 99" in text  # preserved


# ---------------------------------------------------------------------------
# Task 11 — reindex subprocess smoke test
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "sample_vault"


def test_cli_reindex_smoke(tmp_path: Path):
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE, vault)
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "reindex", "--vault", str(vault)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # discard LiteLLM stderr noise to avoid pipe-buffer deadlock
        text=True,
        cwd=Path(__file__).parents[1],  # repo root
    )
    assert result.returncode == 0, "reindex subprocess exited non-zero"
    assert "Indexed:" in result.stdout


# ---------------------------------------------------------------------------
# Task 12 — link-hermes-memories
# ---------------------------------------------------------------------------


def test_link_hermes_memories_creates_symlinks(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    hermes_dir = tmp_path / "hermes_memories"
    hermes_dir.mkdir()
    (hermes_dir / "MEMORY.md").write_text("# memory\n§\nfirst entry\n")
    (hermes_dir / "USER.md").write_text("# user\n§\nfact\n")

    link_hermes_memories(vault, hermes_dir)

    link_dir = vault / "Utility" / "obsidian-knowledge" / "hermes"
    assert (link_dir / "MEMORY.md").is_symlink()
    assert (link_dir / "USER.md").is_symlink()
    assert (link_dir / "MEMORY.md").read_text() == "# memory\n§\nfirst entry\n"


def test_link_hermes_memories_idempotent(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    hermes_dir = tmp_path / "hermes_memories"
    hermes_dir.mkdir()
    (hermes_dir / "MEMORY.md").write_text("a")
    (hermes_dir / "USER.md").write_text("b")

    link_hermes_memories(vault, hermes_dir)
    link_hermes_memories(vault, hermes_dir)  # second call must not error

    link_dir = vault / "Utility" / "obsidian-knowledge" / "hermes"
    assert (link_dir / "MEMORY.md").is_symlink()
