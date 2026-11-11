"""Secret progress must represent scanned content, never timestamps or failed work."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.secret_scanner import WEAK, configure_vault, run_stop
from tests.secret_scanner import hook_module as hook_module


def test_audit_after_content_edit_cannot_advance_scan_progress(tmp_path, hook_module, monkeypatch):
    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    note.write_text("plain\n")
    run_stop(hook_module)
    note.write_text(WEAK)
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_text(baseline.read_text() + "\n")  # External audit/save after content edit.
    os.utime(baseline, (note.stat().st_mtime + 100, note.stat().st_mtime + 100))
    run_stop(hook_module)
    assert "note.md" in json.loads(baseline.read_text())["results"]


def test_restored_mtime_content_edit_is_rescanned(tmp_path, hook_module, monkeypatch):
    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    note.write_text("plain\n")
    run_stop(hook_module)
    previous = note.stat()
    note.write_text(WEAK)
    os.utime(note, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    run_stop(hook_module)
    assert "note.md" in json.loads((tmp_path / ".secrets.baseline").read_text())["results"]


def test_edit_during_scan_remains_pending_and_unchanged_scan_is_incremental(
    tmp_path, hook_module, monkeypatch
):
    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    note.write_text("plain\n")
    real_scan = hook_module.run_scan
    scanned = []

    def scan_then_edit(baseline, root, paths, all_paths):
        scanned.append(paths)
        completed = real_scan(baseline, root, paths, all_paths)
        if len(scanned) == 1:
            note.write_text(WEAK)
        return completed

    monkeypatch.setattr(hook_module, "run_scan", scan_then_edit)
    run_stop(hook_module)
    run_stop(hook_module)
    run_stop(hook_module)
    assert scanned[0] == ["note.md"]
    assert "note.md" in scanned[1]
    assert "note.md" not in scanned[2]
    assert "note.md" in json.loads((tmp_path / ".secrets.baseline").read_text())["results"]


def test_progress_tracks_only_readable_stable_versions(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hookslib.secret_progress import ScanProgress, content_digest, content_version

    state = tmp_path / "progress.json"
    assert ScanProgress.load(state).files == {}
    state.write_text("invalid json")
    assert ScanProgress.load(state).files == {}
    progress = ScanProgress(revision=1, baseline="digest", files={"note.md": "content-digest"})
    progress.save(state)
    assert ScanProgress.load(state) == progress
    assert content_version(tmp_path / "missing.md") is None
    assert content_digest(tmp_path / "missing.md") == ""
    note = tmp_path / "note.md"
    note.write_text("plain")
    states = iter(
        [
            SimpleNamespace(st_mtime_ns=1, st_ctime_ns=1, st_size=5),
            SimpleNamespace(st_mtime_ns=2, st_ctime_ns=2, st_size=5),
        ]
    )
    monkeypatch.setattr(os, "fstat", lambda fd: next(states))
    assert content_version(note) is None


def test_unreadable_content_is_not_marked_scanned(tmp_path, hook_module, monkeypatch):
    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    note.write_text(WEAK)
    real_version = hook_module.content_version
    monkeypatch.setattr(
        hook_module, "content_version", lambda path: None if path == note else real_version(path)
    )
    run_stop(hook_module)
    assert "note.md" not in json.loads((tmp_path / ".secrets.baseline").read_text())["results"]
    monkeypatch.setattr(hook_module, "content_version", real_version)
    run_stop(hook_module)
    assert "note.md" in json.loads((tmp_path / ".secrets.baseline").read_text())["results"]


@pytest.mark.parametrize("before,after", [("plain\n", WEAK), (WEAK, "plain\n")])
def test_backend_swallowed_read_error_retains_findings_and_retries(
    tmp_path, hook_module, monkeypatch, before, after
):
    import builtins

    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    baseline = tmp_path / ".secrets.baseline"
    note.write_text(before)
    run_stop(hook_module)
    note.write_text(after)
    real_open = builtins.open
    failed = []

    def unavailable_once(filename, mode="r", *args, **kwargs):
        if str(filename) == str(note) and mode == "r" and not failed:
            failed.append(True)
            raise OSError("transient detector read failure")
        return real_open(filename, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", unavailable_once)
    run_stop(hook_module)
    assert failed
    assert ("note.md" in json.loads(baseline.read_text())["results"]) is (before == WEAK)
    run_stop(hook_module)
    assert ("note.md" in json.loads(baseline.read_text())["results"]) is (after == WEAK)


def test_backend_partial_findings_do_not_replace_previous_scan(tmp_path, hook_module, monkeypatch):
    import logging

    from detect_secrets.core.secrets_collection import SecretsCollection

    note = tmp_path / "note.md"
    baseline = tmp_path / ".secrets.baseline"
    note.write_text("plain\n")
    hook_module.run_scan(baseline, str(tmp_path), ["note.md"], ["note.md"])
    note.write_text(WEAK)
    real_scan = SecretsCollection.scan_file

    def partial_failure(collection, path):
        real_scan(collection, path)
        logging.getLogger("detect-secrets").warning("synthetic backend failure after partial findings")

    monkeypatch.setattr(SecretsCollection, "scan_file", partial_failure)
    assert hook_module.run_scan(baseline, str(tmp_path), ["note.md"], ["note.md"]) == []
    assert "note.md" not in json.loads(baseline.read_text())["results"]


@pytest.mark.parametrize("failure", ["stat", "walk"])
def test_incomplete_discovery_preserves_baseline_and_checkpoint(tmp_path, hook_module, monkeypatch, failure):
    from hookslib.secret_progress import ScanProgress

    configure_vault(hook_module, monkeypatch, tmp_path)
    note = tmp_path / "note.md"
    baseline = tmp_path / ".secrets.baseline"
    note.write_text(WEAK)
    run_stop(hook_module)
    with hook_module.baseline_lock(str(tmp_path)) as lock:
        progress = Path(lock).with_suffix(".json")
    baseline_before = baseline.read_bytes()
    progress_before = progress.read_bytes()
    original_stat = hook_module.os.stat
    original_walk = hook_module.os.walk

    def blocked_stat(path, *args, **kwargs):
        if str(path) == str(note):
            raise PermissionError("unreadable note")
        return original_stat(path, *args, **kwargs)

    def blocked_walk(root, *, onerror):
        onerror(PermissionError("unreadable subtree"))
        yield from original_walk(root)

    monkeypatch.setattr(hook_module.os, "stat", blocked_stat if failure == "stat" else original_stat)
    monkeypatch.setattr(hook_module.os, "walk", blocked_walk if failure == "walk" else original_walk)
    with pytest.raises(PermissionError, match="unreadable"):
        run_stop(hook_module)
    assert baseline.read_bytes() == baseline_before
    assert progress.read_bytes() == progress_before
    assert ScanProgress.load(progress).files


def test_interrupted_scan_keeps_completed_batches(tmp_path, hook_module, monkeypatch):
    from hookslib.secret_progress import ScanProgress

    configure_vault(hook_module, monkeypatch, tmp_path)
    monkeypatch.setattr(hook_module, "SCAN_BATCH_SIZE", 1)
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("plain\n")
    real_scan = hook_module.run_scan
    calls = []

    def die_on_second_batch(baseline, root, paths, all_paths):
        calls.append(paths)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return real_scan(baseline, root, paths, all_paths)

    monkeypatch.setattr(hook_module, "run_scan", die_on_second_batch)
    with pytest.raises(KeyboardInterrupt):
        run_stop(hook_module)
    with hook_module.baseline_lock(str(tmp_path)) as lock:
        progress = ScanProgress.load(Path(lock).with_suffix(".json"))
    assert list(progress.files) == [calls[0][0]]

    scanned = []

    def record_scan(baseline, root, paths, all_paths):
        scanned.append(paths)
        return real_scan(baseline, root, paths, all_paths)

    monkeypatch.setattr(hook_module, "run_scan", record_scan)
    run_stop(hook_module)
    assert scanned == [[calls[1][0]]]
