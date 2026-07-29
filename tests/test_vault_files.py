"""Regression tests for verified vault filesystem I/O."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lib.vault_index.vault_files import read_vault_file, resolve_vault_file, write_vault_file

ROOT = Path(__file__).parents[1]


def test_cli_write_and_read_preserve_literal_markdown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    content = "# Durable note\n\n`identifier` stays literal; so do `$()` and [[links]].\n"

    written = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "write",
            "wiki/note.md",
            "--vault",
            str(vault),
        ],
        cwd=ROOT,
        input=content,
        capture_output=True,
        text=True,
    )
    read = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "read",
            "wiki/note.md",
            "--vault",
            str(vault),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert written.returncode == 0, written.stderr
    assert "Wrote and verified" in written.stdout
    assert (vault / "wiki" / "note.md").read_text() == content
    assert read.returncode == 0, read.stderr
    assert read.stdout == content


def test_vault_file_path_rejects_absolute_and_escaping_paths(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="vault-relative"):
        resolve_vault_file(vault, tmp_path / "outside.md")
    with pytest.raises(ValueError, match="outside the vault"):
        resolve_vault_file(vault, Path("../outside.md"))


def test_vault_file_path_rejects_symlink_escape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the vault"):
        resolve_vault_file(vault, Path("escape/note.md"))


def test_write_refuses_empty_content_and_unintended_overwrite(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="empty"):
        write_vault_file(vault, Path("wiki/empty.md"), b"")

    target = write_vault_file(vault, Path("wiki/note.md"), b"first\n")
    with pytest.raises(FileExistsError):
        write_vault_file(vault, Path("wiki/note.md"), b"second\n")

    write_vault_file(vault, Path("wiki/note.md"), b"second\n", replace=True)
    assert target.read_bytes() == b"second\n"
    assert read_vault_file(vault, Path("wiki/note.md")) == b"second\n"


def test_write_fails_if_final_filesystem_bytes_do_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = (vault / "wiki" / "note.md").resolve()
    real_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == target and path.exists():
            return b"corrupt"
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    with pytest.raises(OSError, match="verification failed"):
        write_vault_file(vault, Path("wiki/note.md"), b"expected\n")
