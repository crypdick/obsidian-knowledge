"""Tests for recall_init_lib (primer build)."""

import os
import subprocess
import sys
from pathlib import Path

from hookslib import recall_init_lib


class TestBuildPrimer:
    def test_includes_core_harness_directives(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert "harness" in primer.lower()
        assert "memory" in primer.lower()
        assert "obsidian-knowledge search" in primer
        assert "remember-conversations" in primer
        assert "durable, novel delta" in primer
        assert "filing nothing as success" in primer
        assert "at most 20 bullets or 6000 characters" in primer
        assert "obsidian-knowledge papercut" in primer
        assert "/improve-harness" not in primer
        assert "frustration" not in primer.lower()

    def test_primer_does_not_mention_vault_search_slash_command(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert "/vault-search" not in primer

    def test_primer_includes_vault_path(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert str(tmp_vault) in primer

    def test_primer_does_not_mention_symlink(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert "symlink" not in primer.lower()
        assert "setup-harness" not in primer


def test_adapter_reuses_already_loaded_primer_module():
    hooks = Path(__file__).parents[1] / "hooks"
    script = """
import sys
from types import SimpleNamespace
sentinel = object()
sys.modules['vault_index.primer'] = SimpleNamespace(build_primer=sentinel)
from hookslib import recall_init_lib
assert recall_init_lib.build_primer is sentinel
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(hooks)},
    )
    assert result.returncode == 0, result.stderr
