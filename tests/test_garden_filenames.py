"""Filename policy findings through the combined, read-only vault audit."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gardener.cli import main


@pytest.mark.parametrize("character", ["<", ">", "?", ":", '"', "|", "*", "\\"])
def test_audit_reports_illegal_file_and_folder_names(tmp_path: Path, capsys, character: str) -> None:
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        json.dumps({"ai_managed": [], "illegal_filename_chars": ["<", ">", "?", ":", '"', "|", "*", "\\"]})
    )
    note = tmp_path / f"Inbox/Question{character}.md"
    attachment = tmp_path / f"assets/photo{character}.png"
    folder = tmp_path / f"Projects/folder{character}"
    for path in (note, attachment, folder / "safe.md"):
        path.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Original note\n")
    attachment.write_bytes(b"\x00\xff\x01")
    (folder / "safe.md").write_text("# Safe child\n")

    assert main(["audit", "--vault", str(tmp_path)]) == 0
    findings = {
        line for line in capsys.readouterr().out.splitlines() if line.startswith("ILLEGAL_FILENAME\t")
    }
    assert findings == {
        f"ILLEGAL_FILENAME\tInbox/Question{character}.md\tchars={character!r}",
        f"ILLEGAL_FILENAME\tassets/photo{character}.png\tchars={character!r}",
        f"ILLEGAL_FILENAME\tProjects/folder{character}\tchars={character!r}",
    }
    assert note.read_text() == "# Original note\n"
    assert attachment.read_bytes() == b"\x00\xff\x01"
    assert (folder / "safe.md").read_text() == "# Safe child\n"


def test_audit_uses_only_configured_characters(tmp_path: Path, capsys) -> None:
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        'ai_managed: []\nillegal_filename_chars: ["?", "<", ">"]\n'
    )
    (tmp_path / "why??<now>.md").write_text("# Note\n")
    (tmp_path / "allowed: café.md").write_text("# Note\n")
    assert main(["audit", "--vault", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "ILLEGAL_FILENAME\twhy??<now>.md\tchars='?<>'\n"


def test_audit_filename_checks_are_opt_in(tmp_path: Path, capsys) -> None:
    (tmp_path / "allowed?.png").write_bytes(b"\xff")
    assert main(["audit", "--vault", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "OK: no structural or convention issues found\n"


def test_audit_keeps_filename_scan_exclusions(tmp_path: Path, capsys) -> None:
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        'ai_managed: []\nillegal_filename_chars: ["?"]\n'
    )
    for relative in (
        ".hidden?.md",
        ".stversions/old?.md",
        ".trash/deleted?.md",
        "wiki/.hidden?/note?.md",
        "wiki/_sources/source?.md",
        "wiki/node_modules/package?.json",
        "wiki/.venv/library?.py",
        "wiki/old.sync-conflict-20261105-120000-host?.md",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Excluded\n")
    (tmp_path / "linked?.md").symlink_to(tmp_path / "wiki/_sources/source?.md")
    (tmp_path / "linked?folder").symlink_to(tmp_path / "wiki", target_is_directory=True)

    assert main(["audit", "--vault", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "OK: no structural or convention issues found\n"
