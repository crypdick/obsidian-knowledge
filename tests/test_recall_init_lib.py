"""Tests for recall_init_lib (symlink verification + primer build)."""
from lib import recall_init_lib  # noqa: E402


class TestVerifySymlink:
    def test_returns_ok_when_symlinked_correctly(self, tmp_vault, tmp_path):
        """Symlink exists and points to vault repos dir."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        symlink = tmp_path / "claude_projects_link"
        symlink.symlink_to(target)
        result = recall_init_lib.verify_symlink(symlink, target)
        assert result.ok is True
        assert result.error is None

    def test_returns_error_when_path_missing(self, tmp_vault, tmp_path):
        """Path doesn't exist at all."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        symlink = tmp_path / "missing"
        result = recall_init_lib.verify_symlink(symlink, target)
        assert result.ok is False
        assert "not configured" in result.error.lower()

    def test_returns_error_when_real_dir_not_symlink(self, tmp_vault, tmp_path):
        """Path exists but is a real directory, not a symlink."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        real_dir = tmp_path / "real_projects"
        real_dir.mkdir()
        result = recall_init_lib.verify_symlink(real_dir, target)
        assert result.ok is False
        assert "not configured" in result.error.lower()

    def test_returns_error_when_symlinked_to_wrong_target(self, tmp_path):
        """Symlink exists but points elsewhere."""
        wrong = tmp_path / "wrong"
        wrong.mkdir()
        symlink = tmp_path / "claude_projects_link"
        symlink.symlink_to(wrong)
        expected = tmp_path / "expected"
        expected.mkdir()
        result = recall_init_lib.verify_symlink(symlink, expected)
        assert result.ok is False
        assert "not configured" in result.error.lower()


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
