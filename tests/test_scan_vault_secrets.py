"""Unit tests for scan-vault-secrets known-leaked literal blacklist."""

from __future__ import annotations

import importlib.util
import json
import os
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
            "# leading comment\nalpha\n\n  # indented comment\nbeta\n\n"
        )
        assert hook_module.load_known_leaked(str(tmp_path)) == ["alpha", "beta"]

    def test_strips_whitespace(self, tmp_path, hook_module):
        (tmp_path / ".secrets.known-leaked").write_text("  alpha  \n\tbeta\t\n")
        assert hook_module.load_known_leaked(str(tmp_path)) == ["alpha", "beta"]

    def test_unreadable_file_returns_empty(self, tmp_path, hook_module):
        # Pass a path that doesn't exist by giving a non-directory parent.
        assert hook_module.load_known_leaked(str(tmp_path / "nope")) == []


class TestScanKnownLeaked:
    """`scan_known_leaked(vault_root, rel_paths, literals)` greps each
    vault-relative path under `vault_root` for every literal and
    returns `(total_matches, files_with_matches, sample)`. Sample
    entries look like `<rel_path>:<lineno> :: <literal>`.
    """

    def test_no_paths_or_no_literals(self, tmp_path, hook_module):
        (tmp_path / "a.md").write_text("alpha")
        assert hook_module.scan_known_leaked(str(tmp_path), [], ["alpha"]) == (0, 0, [])
        assert hook_module.scan_known_leaked(str(tmp_path), ["a.md"], []) == (0, 0, [])

    def test_finds_single_match(self, tmp_path, hook_module):
        (tmp_path / "a.md").write_text("line one\nthe alpha is here\nline three\n")
        total, files, sample = hook_module.scan_known_leaked(str(tmp_path), ["a.md"], ["alpha"])
        assert total == 1
        assert files == 1
        assert len(sample) == 1
        assert "a.md:2" in sample[0]
        assert ":: alpha" in sample[0]

    def test_counts_all_occurrences_across_files(self, tmp_path, hook_module):
        (tmp_path / "a.md").write_text("alpha\nalpha\n")
        (tmp_path / "b.md").write_text("alpha\nbeta\n")
        total, files, _ = hook_module.scan_known_leaked(str(tmp_path), ["a.md", "b.md"], ["alpha", "beta"])
        assert total == 4
        assert files == 2

    def test_sample_capped_at_limit(self, tmp_path, hook_module):
        # Write 20 occurrences; sample should cap at KNOWN_LEAKED_SAMPLE_LIMIT.
        (tmp_path / "a.md").write_text("alpha\n" * 20)
        total, _, sample = hook_module.scan_known_leaked(str(tmp_path), ["a.md"], ["alpha"])
        assert total == 20
        assert len(sample) == hook_module.KNOWN_LEAKED_SAMPLE_LIMIT

    def test_multiple_literals_on_same_line_each_count(self, tmp_path, hook_module):
        (tmp_path / "a.md").write_text("alpha and beta together\n")
        total, files, sample = hook_module.scan_known_leaked(str(tmp_path), ["a.md"], ["alpha", "beta"])
        assert total == 2
        assert files == 1
        # Sample contains entries for each literal that matched.
        assert any(":: alpha" in s for s in sample)
        assert any(":: beta" in s for s in sample)

    def test_unreadable_file_skipped_not_raised(self, tmp_path, hook_module):
        (tmp_path / "a.md").write_text("alpha\n")
        total, files, _ = hook_module.scan_known_leaked(str(tmp_path), ["a.md", "nope.md"], ["alpha"])
        assert total == 1
        assert files == 1

    def test_substring_match_inside_word(self, tmp_path, hook_module):
        # Literal match is a plain substring — `alpha` matches even when
        # wrapped in markdown formatting (e.g. backticks). Important:
        # dictionary substrings will also match (by design — the user
        # curates the blacklist).
        (tmp_path / "a.md").write_text("scanning for `alpha` in vault\n")
        total, _, _ = hook_module.scan_known_leaked(str(tmp_path), ["a.md"], ["alpha"])
        assert total == 1

    def test_sample_paths_are_vault_relative(self, tmp_path, hook_module):
        # Nested file: ensure reported sample uses vault-relative path.
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.md").write_text("alpha\n")
        rel = "sub/a.md"
        _, _, sample = hook_module.scan_known_leaked(str(tmp_path), [rel], ["alpha"])
        assert sample == [f"{rel}:1 :: alpha"]


def test_scan_policy_requires_readable_current_version(tmp_path, hook_module):
    baseline = tmp_path / ".secrets.baseline"
    assert not hook_module.scan_policy_is_current(baseline)
    baseline.write_text("not json")
    assert not hook_module.scan_policy_is_current(baseline)
    baseline.write_text('{"vault_scan_policy": 0}')
    assert not hook_module.scan_policy_is_current(baseline)
    baseline.write_text(f'{{"vault_scan_policy": {hook_module.SCAN_POLICY_VERSION}}}')
    assert hook_module.scan_policy_is_current(baseline)


def test_find_files_filters_noise_and_honors_mtime(tmp_path, hook_module, monkeypatch):
    (tmp_path / "new.md").write_text("new")
    (tmp_path / "old.md").write_text("old")
    (tmp_path / "image.png").write_bytes(b"image")
    (tmp_path / ".secrets.baseline").write_text("state")
    (tmp_path / ".secrets.known-leaked").write_text("secret")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "hidden.md").write_text("hidden")
    sources = tmp_path / "_sources"
    sources.mkdir()
    (sources / "source.md").write_text("source")
    real_getmtime = os.path.getmtime

    def selective_mtime(path):
        if str(path).endswith("old.md"):
            return 1
        return real_getmtime(path)

    monkeypatch.setattr(hook_module.os.path, "getmtime", selective_mtime)
    assert hook_module.find_files(str(tmp_path), since_mtime=2) == ["new.md"]


def test_find_files_skips_file_removed_during_walk(tmp_path, hook_module, monkeypatch):
    note = tmp_path / "vanished.md"
    note.write_text("content")
    monkeypatch.setattr(
        hook_module.os.path,
        "getmtime",
        lambda path: (_ for _ in ()).throw(OSError("vanished")),
    )
    assert hook_module.find_files(str(tmp_path)) == []


def test_corrupt_baseline_is_rebuilt_from_scratch(tmp_path, hook_module):
    note = tmp_path / "note.md"
    note.write_text('password="synthetic-weak-password"\n')  # pragma: allowlist secret
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_text("corrupt")

    hook_module.run_scan(baseline, str(tmp_path), ["note.md"], ["note.md"])

    assert hook_module.scan_policy_is_current(baseline)
    assert hook_module.count_unaudited(baseline)[0] == 1


def test_count_unaudited_handles_missing_file_and_caps_sample(tmp_path, hook_module):
    baseline = tmp_path / ".secrets.baseline"
    assert hook_module.count_unaudited(baseline) == (0, [])
    findings = [
        {"is_secret": None, "line_number": line, "type": "Synthetic"}
        for line in range(hook_module.UNAUDITED_SAMPLE_LIMIT + 2)
    ]
    findings.append({"is_secret": False, "line_number": 99, "type": "Audited"})
    baseline.write_text(json.dumps({"results": {"note.md": findings}}))

    count, sample = hook_module.count_unaudited(baseline)
    assert count == hook_module.UNAUDITED_SAMPLE_LIMIT + 2
    assert len(sample) == hook_module.UNAUDITED_SAMPLE_LIMIT


def test_manual_mode_reports_outside_vault(tmp_path, hook_module, monkeypatch, capsys):
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: False)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main(["--manual"])
    assert stopped.value.code == 1
    assert "Not inside a configured vault root" in capsys.readouterr().err


def test_hook_mode_is_silent_outside_vault(tmp_path, hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: False)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main([])
    assert stopped.value.code == 0


def test_hook_mode_honors_cooldown_before_scanning(tmp_path, hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: True)
    monkeypatch.setattr(hook_module, "read_input", lambda: {"session_id": "session"})
    monkeypatch.setattr(hook_module, "in_cooldown", lambda payload, marker_basename: True)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main([])
    assert stopped.value.code == 0


@pytest.mark.parametrize("manual", [False, True])
def test_scan_handles_vault_registry_changing_during_startup(
    tmp_path, hook_module, monkeypatch, capsys, manual
):
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: True)
    monkeypatch.setattr(hook_module, "read_input", dict)
    monkeypatch.setattr(hook_module, "in_cooldown", lambda payload, marker_basename: False)
    monkeypatch.setattr(hook_module, "load_vault_roots", list)
    monkeypatch.setattr(hook_module, "find_containing_vault", lambda cwd, roots: None)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main(["--manual"] if manual else [])
    assert stopped.value.code == (1 if manual else 0)
    if manual:
        assert "cwd not inside any configured vault" in capsys.readouterr().err


def _stub_main_scan(hook_module, monkeypatch, tmp_path, *, count=0, leaked=0):
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: True)
    monkeypatch.setattr(hook_module, "find_containing_vault", lambda cwd, roots: str(tmp_path))
    monkeypatch.setattr(hook_module, "load_vault_roots", lambda: [str(tmp_path)])
    monkeypatch.setattr(hook_module, "find_files", lambda root, since_mtime=0: ["note.md"])
    monkeypatch.setattr(hook_module, "scan_policy_is_current", lambda path: False)
    monkeypatch.setattr(hook_module, "run_scan", lambda *args: None)
    monkeypatch.setattr(hook_module, "count_unaudited", lambda path: (count, ["note.md:1 (Synthetic)"]))
    monkeypatch.setattr(hook_module, "load_known_leaked", lambda root: ["leaked"] if leaked else [])
    monkeypatch.setattr(
        hook_module,
        "scan_known_leaked",
        lambda root, paths, literals: (leaked, 1, ["note.md:1 :: leaked"]),
    )


def test_manual_mode_reports_clean_and_findings(tmp_path, hook_module, monkeypatch, capsys):
    _stub_main_scan(hook_module, monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main(["--manual"])
    assert stopped.value.code == 0
    assert "detect-secrets: clean" in capsys.readouterr().out

    _stub_main_scan(hook_module, monkeypatch, tmp_path, count=1, leaked=1)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main(["--manual"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "unaudited finding" in output
    assert "Known-leaked literal" in output


def test_hook_mode_emits_only_when_findings_exist(tmp_path, hook_module, monkeypatch):
    _stub_main_scan(hook_module, monkeypatch, tmp_path)
    monkeypatch.setattr(hook_module, "read_input", dict)
    monkeypatch.setattr(hook_module, "in_cooldown", lambda payload, marker_basename: False)
    emitted = []
    monkeypatch.setattr(hook_module, "emit_block", emitted.append)
    with pytest.raises(SystemExit) as stopped:
        hook_module.main([])
    assert stopped.value.code == 0
    assert emitted == []

    _stub_main_scan(hook_module, monkeypatch, tmp_path, count=1)
    hook_module.main([])
    assert len(emitted) == 1
    assert "unaudited finding" in emitted[0]


def test_incremental_scan_uses_baseline_mtime(tmp_path, hook_module, monkeypatch, capsys):
    baseline = tmp_path / hook_module.BASELINE_FILENAME
    baseline.write_text(f'{{"vault_scan_policy": {hook_module.SCAN_POLICY_VERSION}}}')
    monkeypatch.setattr(hook_module, "is_in_vault", lambda cwd: True)
    monkeypatch.setattr(hook_module, "find_containing_vault", lambda cwd, roots: str(tmp_path))
    monkeypatch.setattr(hook_module, "load_vault_roots", lambda: [str(tmp_path)])
    calls = []

    def find_files(root, since_mtime=0):
        calls.append(since_mtime)
        return ["all.md"] if since_mtime == 0 else ["changed.md"]

    scanned = []
    monkeypatch.setattr(hook_module, "find_files", find_files)
    monkeypatch.setattr(hook_module, "run_scan", lambda path, root, paths, all_paths: scanned.append(paths))
    monkeypatch.setattr(hook_module, "count_unaudited", lambda path: (0, []))
    monkeypatch.setattr(hook_module, "load_known_leaked", lambda root: [])

    with pytest.raises(SystemExit) as stopped:
        hook_module.main(["--manual"])
    assert stopped.value.code == 0
    assert calls[0] == 0
    assert calls[1] == baseline.stat().st_mtime
    assert scanned == [["changed.md"]]
    assert "Scanned 1 file(s) out of 1" in capsys.readouterr().out
