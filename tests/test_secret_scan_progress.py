"""Secret progress must represent scanned content, never timestamps or failed work."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from hookslib.secret_progress import ScanProgress

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

    from hookslib.secret_progress import content_version

    state = tmp_path / "progress.json"
    assert ScanProgress.load(state).files == {}
    state.write_text("invalid json")
    assert ScanProgress.load(state).files == {}
    progress = ScanProgress(revision=1, files={"note.md": ("content-digest", "findings-digest")})
    progress.save(state)
    assert ScanProgress.load(state) == progress
    assert content_version(tmp_path / "missing.md") is None
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
    assert hook_module.run_scan(baseline, str(tmp_path), ["note.md"], ["note.md"]) == {}
    assert "note.md" not in json.loads(baseline.read_text())["results"]


@pytest.mark.parametrize("failure", ["stat", "walk"])
def test_incomplete_discovery_preserves_baseline_and_checkpoint(tmp_path, hook_module, monkeypatch, failure):
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


@pytest.mark.parametrize("after_baseline_write", [False, True])
def test_interruption_keeps_prior_scan_batches(tmp_path, hook_module, monkeypatch, after_baseline_write):
    configure_vault(hook_module, monkeypatch, tmp_path)
    monkeypatch.setattr(hook_module, "CHECKPOINT_FILES", 1)
    for name in ("first.md", "second.md"):
        (tmp_path / name).write_text(WEAK)
    monkeypatch.setattr(hook_module, "find_files", lambda root: ["first.md", "second.md"])
    real_scan = hook_module.run_scan
    attempted = []

    def interrupted(baseline, root, paths, all_paths):
        attempted.extend(paths)
        if paths != ["second.md"]:
            return real_scan(baseline, root, paths, all_paths)
        if after_baseline_write:
            real_scan(baseline, root, paths, all_paths)
        raise InterruptedError("stopped")

    monkeypatch.setattr(hook_module, "run_scan", interrupted)
    with pytest.raises(InterruptedError):
        run_stop(hook_module)
    assert attempted == ["first.md", "second.md"]
    with hook_module.baseline_lock(str(tmp_path)) as lock:
        assert set(ScanProgress.load(lock.with_suffix(".json")).files) == {"first.md"}

    attempted.clear()

    def resume(baseline, root, paths, all_paths):
        attempted.extend(paths)
        return real_scan(baseline, root, paths, all_paths)

    monkeypatch.setattr(hook_module, "run_scan", resume)
    run_stop(hook_module)
    assert attempted == ["second.md"]
    assert set(json.loads((tmp_path / ".secrets.baseline").read_text())["results"]) == {
        "first.md",
        "second.md",
    }


def test_background_stop_reports_on_next_turn_without_waiting_for_lock(
    tmp_path, hook_module, monkeypatch, capsys
):
    configure_vault(hook_module, monkeypatch, tmp_path)
    (tmp_path / "note.md").write_text(WEAK)
    with hook_module.baseline_lock(str(tmp_path)):
        with pytest.raises(SystemExit) as stopped:
            hook_module.main(["--background"])
        assert stopped.value.code == 0
    assert not (tmp_path / ".secrets.baseline").exists()
    hook_module.main(["--background"])
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {"systemMessage"}
    assert "note.md:1" in report["systemMessage"]


def test_external_baseline_change_only_retries_affected_file(tmp_path, hook_module, monkeypatch):
    configure_vault(hook_module, monkeypatch, tmp_path)
    (tmp_path / "first.md").write_text(WEAK)
    (tmp_path / "second.md").write_text(WEAK)
    monkeypatch.setattr(hook_module, "find_files", lambda root: ["first.md", "second.md"])
    run_stop(hook_module)
    baseline = tmp_path / ".secrets.baseline"
    data = json.loads(baseline.read_text())
    del data["results"]["second.md"]
    baseline.write_text(json.dumps(data))
    real_scan = hook_module.run_scan
    attempted = []

    def resume(baseline, root, paths, all_paths):
        attempted.extend(paths)
        return real_scan(baseline, root, paths, all_paths)

    monkeypatch.setattr(hook_module, "run_scan", resume)
    run_stop(hook_module)
    assert attempted == ["second.md"]
    assert set(json.loads(baseline.read_text())["results"]) == {"first.md", "second.md"}


def test_manual_scan_reports_io_failure(tmp_path, hook_module, monkeypatch):
    configure_vault(hook_module, monkeypatch, tmp_path)

    def unavailable(*args, **kwargs):
        raise BlockingIOError("state unavailable")

    monkeypatch.setattr(hook_module, "scan_and_track", unavailable)
    with pytest.raises(BlockingIOError, match="state unavailable"):
        hook_module.main(["--manual"])
