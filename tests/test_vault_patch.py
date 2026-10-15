"""Behavior tests for confined, exact text edits."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from lib.vault_index.vault_files import patch_vault_file, write_vault_file


def test_patch_preserves_frontmatter_crlf_unicode_and_permissions(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    before = "---\r\ntitle: café\r\n---\r\n\r\nOld paragraph.\r\nUntouched.\r\n".encode()
    target.write_bytes(before)
    target.chmod(0o640)

    result = patch_vault_file(
        tmp_path,
        Path("note.md"),
        "Old paragraph.",
        "New paragraph.",
        expected_sha256=hashlib.sha256(before).hexdigest(),
    )

    assert result == target
    assert target.read_bytes() == "---\r\ntitle: café\r\n---\r\n\r\nNew paragraph.\r\nUntouched.\r\n".encode()
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_patch_frontmatter_without_reserializing(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"---\ntitle: 'Old' # keep this comment\n---\nBody\n")

    patch_vault_file(tmp_path, Path("note.md"), "title: 'Old'", "title: 'New'")

    assert target.read_bytes() == b"---\ntitle: 'New' # keep this comment\n---\nBody\n"


@pytest.mark.parametrize(
    ("before", "old", "message"),
    [
        (b"note", "", "old_str must not be empty"),
        (b"note", "absent", "exactly once"),
        (b"note note", "note", "exactly once"),
        (b"aaa", "aa", "exactly once"),
    ],
)
def test_patch_rejects_missing_empty_or_ambiguous_match(
    tmp_path: Path, before: bytes, old: str, message: str
) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(before)

    with pytest.raises(ValueError, match=message):
        patch_vault_file(tmp_path, Path("note.md"), old, "replacement")

    assert target.read_bytes() == before


@pytest.mark.parametrize("replacement", ["", " \n\t"])
def test_patch_refuses_blank_result(tmp_path: Path, replacement: str) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"note")

    with pytest.raises(ValueError, match="empty vault content"):
        patch_vault_file(tmp_path, Path("note.md"), "note", replacement)

    assert target.read_bytes() == b"note"


def test_patch_allows_deleting_part_of_note(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"Keep. Remove.")

    patch_vault_file(tmp_path, Path("note.md"), " Remove.", "")

    assert target.read_bytes() == b"Keep."


def test_patch_rejects_stale_hash(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"current note")

    with pytest.raises(ValueError, match="SHA-256"):
        patch_vault_file(tmp_path, Path("note.md"), "note", "replacement", expected_sha256="0" * 64)

    assert target.read_bytes() == b"current note"


def test_patch_refuses_non_utf8_and_missing_files(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        patch_vault_file(tmp_path, Path("note.md"), "old", "new")
    with pytest.raises(FileNotFoundError, match="vault file does not exist"):
        patch_vault_file(tmp_path, Path("missing.md"), "old", "new")


@pytest.mark.parametrize("escape", ["../outside.md", "escape/outside.md"])
def test_patch_rejects_escape(tmp_path: Path, escape: str) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"original")
    (vault / "escape").symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the vault"):
        patch_vault_file(vault, Path(escape), "original", "changed")

    assert outside.read_bytes() == b"original"


def test_patch_rejects_misplaced_utility(tmp_path: Path) -> None:
    target = tmp_path / "wiki" / "Utility" / "note.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")

    with pytest.raises(ValueError, match="Utility paths must be vault-relative"):
        patch_vault_file(tmp_path, Path("wiki/Utility/note.md"), "original", "changed")

    assert target.read_bytes() == b"original"


def test_patch_detects_edit_while_writing_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"original")
    real_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path.suffix == ".tmp":
            target.write_bytes(b"concurrent edit")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    with pytest.raises(ValueError, match="changed since it was read"):
        patch_vault_file(tmp_path, Path("note.md"), "original", "patched")

    assert target.read_bytes() == b"concurrent edit"
    assert list(tmp_path.iterdir()) == [target]


def test_writer_refuses_stale_expected_content(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_bytes(b"concurrent edit")

    with pytest.raises(ValueError, match="changed since it was read"):
        write_vault_file(
            tmp_path, Path("note.md"), b"replacement", replace=True, expected_content=b"original"
        )

    assert target.read_bytes() == b"concurrent edit"
    assert list(tmp_path.iterdir()) == [target]
