"""Durable work tracks quiet files without dropping edits during indexing."""

from lib.vault_index.dirty_paths import DirtyPaths


def test_edits_coalesce_and_reset_quiet_period(tmp_path):
    queue = DirtyPaths(tmp_path / "pending.sqlite", quiet_seconds=30)
    queue.mark("a.md", "one", now=0)
    queue.mark("a.md", "two", now=20)
    assert queue.ready(now=49) is None
    assert queue.ready(now=50) == ("a.md", 2)


def test_unchanged_scan_does_not_delay_and_restart_retains_work(tmp_path):
    db = tmp_path / "pending.sqlite"
    queue = DirtyPaths(db, quiet_seconds=30)
    queue.mark("a.md", "one", now=0)
    queue.mark("a.md", "one", now=20)
    assert DirtyPaths(db, quiet_seconds=30).ready(now=30) == ("a.md", 1)


def test_completion_cannot_clear_newer_edit_and_busy_files_do_not_starve_quiet(tmp_path):
    queue = DirtyPaths(tmp_path / "pending.sqlite", quiet_seconds=30)
    queue.mark("a.md", "one", now=0)
    queue.mark("b.md", "one", now=1)
    assert queue.ready(now=30) == ("a.md", 1)
    queue.mark("a.md", "two", now=31)
    queue.complete("a.md", 1)
    assert queue.ready(now=32) == ("b.md", 1)
    queue.complete("b.md", 1)
    assert queue.ready(now=61) == ("a.md", 2)
    queue.complete("a.md", 2)
    queue.mark("a.md", "two", now=62)
    assert queue.ready(now=100) is None
