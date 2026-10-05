"""Public scan and repair boundaries shared by installed gardener commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from gardener import cli, frontmatter
from gardener.io import (
    REPORT_PATH,
    OrganizerPolicy,
    iter_markdown,
    iter_paths,
    resolve_vault,
    validate_relative,
    visible_path,
    write_checked,
)


@pytest.mark.parametrize(
    "relative",
    [
        "",
        "/outside.md",
        "wiki//note.md",
        "wiki/../outside.md",
        "wiki/.hidden/note.md",
        "wiki/node_modules/note.md",
        "wiki/_sources/note.md",
        "wiki/note.sync-conflict-123.md",
    ],
)
def test_paths_reject_unsafe_or_excluded_names(relative: str) -> None:
    with pytest.raises(ValueError, match="not a visible vault path"):
        validate_relative(relative)


def test_policy_uses_defaults_and_loads_configured_write_boundaries(tmp_path: Path) -> None:
    assert OrganizerPolicy.load(tmp_path).ai_managed == ("wiki",)
    config = tmp_path / ".claude/obsidian-knowledge.yaml"
    config.parent.mkdir()
    config.write_text(
        "ai_managed: [records]\nai_readonly_folders: [records/locked]\n"
        "ai_readonly_root_files: [records/private.md]\nstub_link_patterns: ['^skip:']\n"
    )
    policy = OrganizerPolicy.load(tmp_path)
    assert policy.stub_link_patterns == ("^skip:",)
    assert policy.writable(tmp_path, "records/new.md") == tmp_path / "records/new.md"
    assert policy.writable(tmp_path, REPORT_PATH) == tmp_path / REPORT_PATH
    for relative in ("records/locked", "records/locked/note.md", "records/private.md"):
        with pytest.raises(ValueError, match="read-only path"):
            policy.writable(tmp_path, relative)
    with pytest.raises(ValueError, match="outside managed zones"):
        policy.writable(tmp_path, "recordstore/note.md")
    config.write_text("")
    assert OrganizerPolicy.load(tmp_path).ai_managed == ("wiki",)
    config.write_text("ai_managed: ['wiki/../private']\n")
    with pytest.raises(ValidationError):
        OrganizerPolicy.load(tmp_path)


@pytest.mark.parametrize("link_folder", [True, False])
def test_symlink_paths_are_rejected(tmp_path: Path, link_folder: bool) -> None:
    (tmp_path / "wiki").mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "note.md").write_text("# External\n")
    relative = "wiki/linked/note.md" if link_folder else "wiki/note.md"
    if link_folder:
        (tmp_path / "wiki/linked").symlink_to(target, target_is_directory=True)
    else:
        (tmp_path / relative).symlink_to(target / "note.md")
    with pytest.raises(ValueError, match="symlink path"):
        visible_path(tmp_path, relative)


def test_scan_prunes_excluded_trees_and_yields_only_visible_markdown(tmp_path: Path) -> None:
    for relative in (
        "wiki/sub/note.md",
        "wiki/sub/image.png",
        "wiki/root.md",
        "wiki/.hidden/note.md",
        "wiki/_sources/note.md",
        "wiki/node_modules/note.md",
        "wiki/old.sync-conflict-12.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Content\n")
    (tmp_path / "wiki/broken.md").symlink_to(tmp_path / "absent.md")
    (tmp_path / "wiki/link").symlink_to(tmp_path / "wiki/sub", target_is_directory=True)
    assert {p.relative_to(tmp_path).as_posix() for p in iter_markdown(tmp_path)} == {
        "wiki/sub/note.md",
        "wiki/root.md",
    }
    assert {p.relative_to(tmp_path).as_posix() for p in iter_paths(tmp_path, "wiki/sub")} == {
        "wiki/sub",
        "wiki/sub/note.md",
        "wiki/sub/image.png",
    }
    assert list(iter_paths(tmp_path, "absent")) == []


def test_vault_resolution_rejects_missing_and_file_roots(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_vault(tmp_path / "absent")
    note = tmp_path / "note.md"
    note.write_text("# Note\n")
    with pytest.raises(ValueError, match="not a vault directory"):
        resolve_vault(note)
    assert resolve_vault(tmp_path) == tmp_path


def test_vault_resolution_uses_registry_and_rejects_ambiguity(tmp_path: Path, monkeypatch) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gardener.io.load_vault_roots", lambda: [str(first)])
    assert resolve_vault() == first
    monkeypatch.setattr("gardener.io.load_vault_roots", lambda: [str(first), str(second)])
    with pytest.raises(ValueError, match="pass --vault"):
        resolve_vault()
    monkeypatch.chdir(second)
    assert resolve_vault() == second


def test_verified_writes_create_replace_and_refuse_changed_review(tmp_path: Path) -> None:
    relative = "wiki/topic/note.md"
    path = tmp_path / relative
    write_checked(tmp_path, relative, None, "# Before\r\n")
    assert path.read_bytes() == b"# Before\r\n"
    with pytest.raises(ValueError, match="file changed since review"):
        write_checked(tmp_path, relative, "stale baseline", "# Wrong\n")
    assert path.read_bytes() == b"# Before\r\n"
    write_checked(tmp_path, relative, "# Before\r\n", "# After\r\n")
    assert path.read_bytes() == b"# After\r\n"


def test_verified_write_failure_propagates(tmp_path: Path, monkeypatch) -> None:
    def fail_verification(*args, **kwargs):
        raise OSError("temporary write verification failed: wiki/note.md")

    monkeypatch.setattr("gardener.io.write_vault_file", fail_verification)
    with pytest.raises(OSError, match="temporary write verification failed"):
        write_checked(tmp_path, "wiki/note.md", None, "# Note\n")
    assert not (tmp_path / "wiki/note.md").exists()


@pytest.mark.parametrize(
    "body, expected",
    [
        ("# Note\n", "OK"),
        ("---\ntitle: Note\n", "OK"),
        ("---\ntitle: Note\n---\n# Body\n", "OK"),
        ("---\ntitle: Note\n---\n\n---\n# Body\n", "STRAY_DRY"),
        ("---\ntitle: Note\n---\n---\nother: value\n---\n# Body\n", "NEEDS_MERGE"),
    ],
)
def test_frontmatter_preview_preserves_original(tmp_path: Path, body: str, expected: str) -> None:
    path = tmp_path / "wiki/note.md"
    path.parent.mkdir()
    path.write_text(body)
    assert frontmatter.fix_file(tmp_path, "wiki/note.md", False) == expected
    assert path.read_text() == body


def test_frontmatter_apply_preserves_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "wiki/note.md"
    path.parent.mkdir()
    path.write_bytes(b"---\r\ntitle: Note\r\n---\r\n---\r\n# Body\r\n")
    assert frontmatter.fix_file(tmp_path, "wiki/note.md", True) == "STRAY_FIXED"
    assert path.read_bytes() == b"---\r\ntitle: Note\r\n---\r\n# Body\r\n"


@pytest.mark.parametrize("relative", ["wiki/_sources/note.md", "wiki/../private.md", "private.md"])
def test_frontmatter_refuses_protected_paths_in_preview_and_apply(tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    original = "---\ntitle: Note\n---\n---\n# Body\n"
    path.write_text(original)
    for apply in (False, True):
        with pytest.raises(ValueError):
            frontmatter.fix_file(tmp_path, relative, apply)
    assert path.read_text() == original


def test_frontmatter_command_reports_preview_apply_and_manual_merge(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    note = folder / "note.md"
    note.write_text("---\ntitle: Note\n---\n---\n# Body\n")
    args = ["--vault", str(tmp_path), "wiki/note.md"]
    frontmatter.main(args)
    preview = capsys.readouterr()
    assert "WOULD_FIX" in preview.out
    frontmatter.main(["--apply", *args])
    assert "FIXED" in capsys.readouterr().out
    frontmatter.main(["--vault", str(tmp_path), "wiki/note.md"])
    assert capsys.readouterr().out == ""
    note.write_text("---\ntitle: Note\n---\n---\nother: value\n---\n# Body\n")
    with pytest.raises(SystemExit) as exc:
        frontmatter.main(["--vault", str(tmp_path), "wiki/note.md"])
    assert exc.value.code == 1
    report = capsys.readouterr()
    assert "NEEDS_MERGE" in report.out
    assert "merge keys manually" in report.err


def test_frontmatter_refuses_missing_and_nonmarkdown_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        frontmatter.fix_file(tmp_path, "wiki/absent.md", True)
    with pytest.raises(ValueError, match="frontmatter only edits Markdown files"):
        frontmatter.main(["--vault", str(tmp_path), "wiki/image.png"])


def test_frontmatter_duplicate_marker_at_eof_is_repaired(tmp_path: Path) -> None:
    path = tmp_path / "wiki/note.md"
    path.parent.mkdir()
    path.write_text("---\ntitle: Note\n---\n---")
    assert frontmatter.fix_file(tmp_path, "wiki/note.md", True) == "STRAY_FIXED"
    assert path.read_text() == "---\ntitle: Note\n---"


def test_published_frontmatter_allows_preview_and_refuses_apply(tmp_path: Path, capsys) -> None:
    path = tmp_path / "wiki/published.md"
    path.parent.mkdir()
    original = "---\ndg-publish: true\n---\n---\n# Published\n"
    path.write_text(original)
    args = ["frontmatter", "--vault", str(tmp_path), "wiki/published.md"]
    assert cli.main(args) == 0
    assert "WOULD_FIX" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main([*args, "--apply"])
    assert exc.value.code == 1
    assert "published note requires human consent" in capsys.readouterr().err
    assert path.read_text() == original


def test_malformed_published_frontmatter_allows_preview_and_refuses_apply(tmp_path: Path, capsys) -> None:
    path = tmp_path / "wiki/published.md"
    path.parent.mkdir()
    original = "---\ndg-publish: true\nbroken: [\n---\n---\n# Published\n"
    path.write_text(original)
    args = ["frontmatter", "--vault", str(tmp_path), "wiki/published.md"]
    assert cli.main(args) == 0
    assert "WOULD_FIX" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main([*args, "--apply"])
    assert exc.value.code == 1
    assert "cannot safely rewrite malformed frontmatter" in capsys.readouterr().err
    assert path.read_bytes() == original.encode("utf-8")
