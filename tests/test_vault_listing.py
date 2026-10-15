"""Public behavior of bounded vault directory discovery."""

from pathlib import Path

import pytest

from lib.vault_index.vault_listing import list_vault_files


def test_lists_immediate_entries_in_name_order(tmp_path: Path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "note.md").write_text("nested")
    (tmp_path / "image.png").write_bytes(b"PNG")
    report = list_vault_files(tmp_path)
    assert report.model_dump() == {
        "entries": [
            {"path": "image.png", "name": "image.png", "is_directory": False, "size_bytes": 3},
            {"path": "wiki", "name": "wiki", "is_directory": True, "size_bytes": None},
        ],
        "next_offset": None,
    }


def test_recursive_depth_first_and_depth_ceiling(tmp_path: Path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "deep.md").write_text("deep")
    (tmp_path / "a" / "note.md").write_text("note")
    (tmp_path / "z.md").write_text("last")
    assert [entry.path for entry in list_vault_files(tmp_path, recursive=True, depth=2).entries] == [
        "a",
        "a/b",
        "a/note.md",
        "z.md",
    ]
    assert [entry.path for entry in list_vault_files(tmp_path, recursive=True, depth=3).entries] == [
        "a",
        "a/b",
        "a/b/deep.md",
        "a/note.md",
        "z.md",
    ]


def test_pattern_is_relative_to_requested_directory(tmp_path: Path):
    folder = tmp_path / "wiki" / "sub"
    folder.mkdir(parents=True)
    (folder / "note.md").write_text("yes")
    (folder / "image.png").write_bytes(b"no")
    report = list_vault_files(tmp_path, Path("wiki"), recursive=True, depth=2, pattern="sub/*.md")
    assert [entry.path for entry in report.entries] == ["wiki/sub/note.md"]
    assert [
        entry.path
        for entry in list_vault_files(tmp_path, Path("wiki"), recursive=True, pattern="*.md").entries
    ] == ["wiki/sub/note.md"]


def test_paginates_only_matching_entries(tmp_path: Path):
    for name in ("a.md", "b.png", "c.md", "d.md"):
        (tmp_path / name).touch()
    first = list_vault_files(tmp_path, pattern="*.md", limit=2)
    assert [entry.name for entry in first.entries] == ["a.md", "c.md"]
    assert first.next_offset == 2
    last = list_vault_files(tmp_path, pattern="*.md", limit=2, offset=2)
    assert [entry.name for entry in last.entries] == ["d.md"]
    assert last.next_offset is None
    assert list_vault_files(tmp_path, offset=100).entries == []


@pytest.mark.parametrize(
    "options", [{"limit": 0}, {"limit": 501}, {"offset": -1}, {"depth": 0}, {"depth": 11}]
)
def test_rejects_invalid_bounds(tmp_path: Path, options: dict[str, int]):
    with pytest.raises(ValueError):
        list_vault_files(
            tmp_path,
            limit=options.get("limit", 100),
            offset=options.get("offset", 0),
            depth=options.get("depth", 3),
        )


@pytest.mark.parametrize(
    "relative", ["../outside", ".hidden", "node_modules", "_sources", "wiki/a.sync-conflict-copy.md"]
)
def test_rejects_disallowed_requested_paths(tmp_path: Path, relative: str):
    with pytest.raises(ValueError):
        list_vault_files(tmp_path, Path(relative))


def test_rejects_absolute_requested_path(tmp_path: Path):
    with pytest.raises(ValueError, match="vault-relative"):
        list_vault_files(tmp_path, tmp_path)


def test_rejects_symlink_components(tmp_path: Path):
    folder = tmp_path / "real"
    folder.mkdir()
    (tmp_path / "link").symlink_to(folder, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        list_vault_files(tmp_path, Path("link/sub"))


def test_excludes_hidden_protected_conflict_and_symlink_paths(tmp_path: Path):
    for name in (".hidden", "node_modules", "_sources", "a.sync-conflict-copy"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "note.md").touch()
    (tmp_path / ".hidden.md").touch()
    (tmp_path / "note.sync-conflict-copy.md").touch()
    (tmp_path / "note.md").write_text("visible")
    (tmp_path / "link.md").symlink_to(tmp_path / "note.md")
    (tmp_path / "broken").symlink_to(tmp_path / "absent")
    (tmp_path / "linked-folder").symlink_to(tmp_path / "_sources", target_is_directory=True)
    report = list_vault_files(tmp_path, recursive=True)
    assert [entry.path for entry in report.entries] == ["note.md"]


def test_rejects_missing_or_non_directory_roots_and_targets(tmp_path: Path):
    with pytest.raises(ValueError, match="vault does not exist"):
        list_vault_files(tmp_path / "missing")
    file = tmp_path / "note.md"
    file.touch()
    with pytest.raises(ValueError, match="vault is not a directory"):
        list_vault_files(file)
    with pytest.raises(NotADirectoryError):
        list_vault_files(tmp_path, Path("note.md"))
    with pytest.raises(FileNotFoundError):
        list_vault_files(tmp_path, Path("missing"))


def test_empty_directory_and_exact_page_boundary(tmp_path: Path):
    assert list_vault_files(tmp_path).model_dump() == {"entries": [], "next_offset": None}
    (tmp_path / "note.md").touch()
    assert list_vault_files(tmp_path, limit=1).next_offset is None
