"""Tests for the obsidian-knowledge CLI."""
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from lib.vault_index.cli import (
    default_cache_dir_for_vault,
    format_remember_candidates,
    init_vault_index,
    link_hermes_memories,
    resolve_vault,
    search_ttl,
    SearchTimeoutError,
)


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


def test_init_vault_index_rejects_malformed_yaml(tmp_path: Path, capsys):
    yaml_path = tmp_path / ".claude" / "obsidian-knowledge.yaml"
    yaml_path.parent.mkdir()
    yaml_path.write_text("foo: [\n  - unclosed")
    with pytest.raises(SystemExit) as exc_info:
        init_vault_index(yaml_path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "malformed YAML" in captured.err


def test_resolve_vault_defaults_to_first_configured_vault(tmp_path: Path, monkeypatch):
    """Commands default to the first configured vault when no --vault is supplied."""
    first = tmp_path / "first-vault"
    second = tmp_path / "second-vault"
    first.mkdir()
    second.mkdir()
    config = tmp_path / "vaults.yaml"
    config.write_text(f"vaults:\n  - {first}\n  - {second}\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(config))

    assert resolve_vault(None, cwd=tmp_path / "outside") == first.resolve()


def test_resolve_vault_prefers_containing_configured_vault(tmp_path: Path, monkeypatch):
    """A cwd inside a configured vault wins over the first configured vault."""
    first = tmp_path / "first-vault"
    second = tmp_path / "second-vault"
    cwd = second / "wiki" / "topic"
    first.mkdir()
    cwd.mkdir(parents=True)
    config = tmp_path / "vaults.yaml"
    config.write_text(f"vaults:\n  - {first}\n  - {second}\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(config))

    assert resolve_vault(None, cwd=cwd) == second.resolve()


def test_format_remember_candidates_prints_scored_paths():
    """remember reports potential homes with scores and does not write anything."""

    class Hit:
        def __init__(self, score, path):
            self.score = score
            self.path = path

    text = format_remember_candidates([
        Hit(42.25, "wiki/repos/acme/app/memory/project_codex.md"),
        Hit(9.5, "wiki/codex.md"),
    ])

    assert "Potential homes:" in text
    assert "42.2  wiki/repos/acme/app/memory/project_codex.md" in text
    assert " 9.5  wiki/codex.md" in text


def test_default_cache_dir_for_vault_honors_cache_root_env(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    cache_root = tmp_path / "cache-root"
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(cache_root))

    cache_dir = default_cache_dir_for_vault(vault)

    assert cache_dir.parent == cache_root / "obsidian-knowledge"
    assert cache_dir.name.startswith("vault-")


def test_default_cache_dir_for_vault_falls_back_when_cache_unwritable(
    tmp_path: Path, monkeypatch
):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", raising=False)
    monkeypatch.setattr("lib.vault_index.cli.os.access", lambda _path, _mode: False)

    cache_dir = default_cache_dir_for_vault(vault)

    assert cache_dir.parent == Path("/tmp/obsidian-knowledge-cache/obsidian-knowledge")
    assert cache_dir.name.startswith("vault-")


def test_search_ttl_raises_for_stuck_work():
    with pytest.raises(SearchTimeoutError):
        with search_ttl(1):
            signal_pause()


def signal_pause() -> None:
    import signal

    signal.pause()


def test_private_hook_entrypoint_runs_existing_hook(tmp_path: Path):
    """_hook dispatches through the installed CLI surface to existing hook code."""
    payload = {
        "session_id": "abc",
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
    }
    env = {
        **os.environ,
        "OBSIDIAN_KNOWLEDGE_CACHE_ROOT": str(tmp_path / "cache"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "_hook",
            "post-tool-use",
            "--kind",
            "reflect-nudge",
            "--agent",
            "codex",
        ],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
        env=env,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_codex_hooks_template_uses_installed_cli():
    """Codex hooks should use the uv-tool-installed CLI, not repo-local paths."""
    template = json.loads((Path(__file__).parents[1] / "hooks" / "hooks.json").read_text())
    rendered = json.dumps(template)
    assert "obsidian-knowledge _hook pre-tool-use" in rendered
    assert "${CLAUDE_PLUGIN_ROOT}" not in rendered
    assert "/home/" not in rendered


def test_codex_marketplace_uses_structured_local_source():
    """Codex rejects Claude-style string sources such as './' as an empty path."""
    marketplace = json.loads(
        (Path(__file__).parents[1] / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    plugin = marketplace["plugins"][0]

    assert plugin["name"] == "obsidian-knowledge"
    assert plugin["source"] == {"source": "local", "path": "./plugins/obsidian-knowledge"}
    assert plugin["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }


def test_codex_marketplace_points_to_packaged_plugin():
    """The Git marketplace must point at a plugin directory below the marketplace root."""
    root = Path(__file__).parents[1]
    plugin_root = root / "plugins" / "obsidian-knowledge"

    manifest = json.loads((plugin_root / ".codex-plugin" / "plugin.json").read_text())
    package = tomllib.loads((root / "pyproject.toml").read_text())["project"]

    assert manifest["name"] == "obsidian-knowledge"
    assert manifest["version"] == package["version"]
    assert "hooks" not in manifest
    assert (plugin_root / "skills" / "obsidian-knowledge" / "SKILL.md").exists()
    assert (plugin_root / "hooks" / "hooks.json").exists()


def test_legacy_marketplace_uses_codex_compatible_source():
    """Codex also reads this marketplace path when no .agents marketplace exists."""
    marketplace = json.loads(
        (Path(__file__).parents[1] / ".claude-plugin" / "marketplace.json").read_text()
    )
    plugin = marketplace["plugins"][0]

    assert plugin["source"] == {"source": "local", "path": "./."}
    package = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())[
        "project"
    ]
    assert plugin["version"] == package["version"]


# ---------------------------------------------------------------------------
# Task 11 — reindex subprocess smoke test
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "sample_vault"


def test_cli_reindex_smoke(tmp_path: Path):
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE, vault)
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "reindex", "--vault", str(vault)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # discard LiteLLM stderr noise to avoid pipe-buffer deadlock
        text=True,
        cwd=Path(__file__).parents[1],  # repo root
        env=env,
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


def test_repo_root_is_hermes_plugin():
    root = Path(__file__).parents[1]
    assert (root / "plugin.yaml").exists()
    assert (root / "__init__.py").exists()
    manifest = (root / "plugin.yaml").read_text()
    assert "name: obsidian-vault" in manifest
    assert "pre_tool_call" in manifest
