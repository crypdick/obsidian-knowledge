"""Unit tests for scan-vault-secrets known-leaked literal blacklist."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK_PATH = PLUGIN_ROOT / "hooks" / "scan-vault-secrets.py"


@pytest.fixture(scope="module")
def hook_module():
    """Import scan-vault-secrets.py as a module despite the hyphenated name."""
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    spec = importlib.util.spec_from_file_location("scan_vault_secrets", HOOK_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestLoadKnownLeaked:
    def test_missing_file_returns_empty(self, tmp_path, hook_module):
        assert hook_module.load_known_leaked(str(tmp_path)) == []

    def test_reads_one_literal_per_line(self, tmp_path, hook_module):
        (tmp_path / ".secrets.known-leaked").write_text("alpha\nbeta\ngamma\n")
        assert hook_module.load_known_leaked(str(tmp_path)) == [
            "alpha",
            "beta",
            "gamma",
        ]

    def test_skips_blank_and_comment_lines(self, tmp_path, hook_module):
        (tmp_path / ".secrets.known-leaked").write_text(
            "# leading comment\n"
            "alpha\n"
            "\n"
            "  # indented comment\n"
            "beta\n"
            "\n"
        )
        assert hook_module.load_known_leaked(str(tmp_path)) == ["alpha", "beta"]

    def test_strips_whitespace(self, tmp_path, hook_module):
        (tmp_path / ".secrets.known-leaked").write_text("  alpha  \n\tbeta\t\n")
        assert hook_module.load_known_leaked(str(tmp_path)) == ["alpha", "beta"]

    def test_unreadable_file_returns_empty(self, tmp_path, hook_module):
        # Pass a path that doesn't exist by giving a non-directory parent.
        assert hook_module.load_known_leaked(str(tmp_path / "nope")) == []


class TestScanKnownLeaked:
    def test_no_paths_or_no_literals(self, tmp_path, hook_module):
        f = tmp_path / "a.md"
        f.write_text("alpha")
        assert hook_module.scan_known_leaked([], ["alpha"]) == (0, 0, [])
        assert hook_module.scan_known_leaked([str(f)], []) == (0, 0, [])

    def test_finds_single_match(self, tmp_path, hook_module):
        f = tmp_path / "a.md"
        f.write_text("line one\nthe alpha is here\nline three\n")
        total, files, sample = hook_module.scan_known_leaked([str(f)], ["alpha"])
        assert total == 1
        assert files == 1
        assert len(sample) == 1
        assert "a.md:2" in sample[0]
        assert ":: alpha" in sample[0]

    def test_counts_all_occurrences_across_files(self, tmp_path, hook_module):
        f1 = tmp_path / "a.md"
        f1.write_text("alpha\nalpha\n")
        f2 = tmp_path / "b.md"
        f2.write_text("alpha\nbeta\n")
        total, files, _ = hook_module.scan_known_leaked(
            [str(f1), str(f2)], ["alpha", "beta"]
        )
        assert total == 4
        assert files == 2

    def test_sample_capped_at_limit(self, tmp_path, hook_module):
        f = tmp_path / "a.md"
        # Write 20 occurrences; sample should cap at KNOWN_LEAKED_SAMPLE_LIMIT.
        f.write_text("alpha\n" * 20)
        total, _, sample = hook_module.scan_known_leaked([str(f)], ["alpha"])
        assert total == 20
        assert len(sample) == hook_module.KNOWN_LEAKED_SAMPLE_LIMIT

    def test_multiple_literals_on_same_line_each_count(self, tmp_path, hook_module):
        f = tmp_path / "a.md"
        f.write_text("alpha and beta together\n")
        total, files, sample = hook_module.scan_known_leaked(
            [str(f)], ["alpha", "beta"]
        )
        assert total == 2
        assert files == 1
        # Sample contains entries for each literal that matched.
        assert any(":: alpha" in s for s in sample)
        assert any(":: beta" in s for s in sample)

    def test_unreadable_file_skipped_not_raised(self, tmp_path, hook_module):
        f = tmp_path / "a.md"
        f.write_text("alpha\n")
        missing = tmp_path / "nope.md"
        total, files, _ = hook_module.scan_known_leaked(
            [str(f), str(missing)], ["alpha"]
        )
        assert total == 1
        assert files == 1

    def test_substring_match_inside_word(self, tmp_path, hook_module):
        # `in` is substring match — a literal like "richard1" matches even
        # when wrapped in markdown formatting (e.g. `richard1` in
        # backticks). Important: dictionary substrings will also match
        # (this is by design — the user curates the blacklist).
        f = tmp_path / "a.md"
        f.write_text("scanning for `alpha` in vault\n")
        total, _, _ = hook_module.scan_known_leaked([str(f)], ["alpha"])
        assert total == 1
