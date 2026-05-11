"""Tests for recall_init_lib (primer build)."""
from hookslib import recall_init_lib  # noqa: E402


class TestBuildPrimer:
    def test_includes_all_five_directives(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert "harness" in primer.lower()
        assert "memory" in primer.lower()
        assert "rg" in primer
        assert "remember-conversations" in primer
        assert "/improve-harness" in primer
        assert "frustration" in primer.lower()

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
