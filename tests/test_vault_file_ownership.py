"""Atomic replacement must preserve the existing note's access ownership."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from lib.vault_index.vault_files import write_vault_file


def test_replacement_applies_original_owner_before_mode_and_publication(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_bytes(b"original")
    target.chmod(0o660)
    before = target.stat()
    calls = []
    chown = os.fchown
    chmod = os.fchmod

    def preserve_owner(fd, uid, gid):
        assert target.read_bytes() == b"original"
        calls.append(("owner", uid, gid))
        chown(fd, uid, gid)

    def preserve_mode(fd, mode):
        calls.append(("mode", mode))
        chmod(fd, mode)

    monkeypatch.setattr(os, "fchown", preserve_owner)
    monkeypatch.setattr(os, "fchmod", preserve_mode)
    write_vault_file(tmp_path, Path("note.txt"), b"replacement", replace=True)
    after = target.stat()
    assert calls == [("owner", before.st_uid, before.st_gid), ("mode", 0o660)]
    assert (after.st_uid, after.st_gid, stat.S_IMODE(after.st_mode)) == (before.st_uid, before.st_gid, 0o660)
    assert target.read_bytes() == b"replacement"


def test_ownership_failure_preserves_original_inode_and_removes_temporary(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_bytes(b"original")
    before = target.stat()

    def denied(fd, uid, gid):
        raise PermissionError("ownership preservation denied")

    monkeypatch.setattr(os, "fchown", denied)
    with pytest.raises(PermissionError, match="ownership preservation denied"):
        write_vault_file(tmp_path, Path("note.txt"), b"replacement", replace=True)
    after = target.stat()
    assert (after.st_ino, after.st_uid, after.st_gid, after.st_mode) == (
        before.st_ino,
        before.st_uid,
        before.st_gid,
        before.st_mode,
    )
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]
