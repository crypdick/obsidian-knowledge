"""Vault sweeps use write-time patterns without scanning protected files."""

from pathlib import Path

from gardener.conventions import sweep


def test_dates_periodic_journals_and_wikilink_extensions(tmp_path: Path) -> None:
    content = {
        "Journal/index.md": "# Journal\n",
        "Journal/2026-W40.md": "# Week\n",
        "Journal/2026-M10.md": "# Month\n",
        "Journal/undated.md": "# Undated\n",
        "wiki/topic/diary/index.md": "# Diary\n",
        "wiki/topic/diary/2026-10-03-entry.md": "# Entry\n",
        "wiki/topic/diary/2026-W40.md": "# Needs full date\n",
        "wiki/topic/diary/undated.md": "# Needs date\n",
        "wiki/note.md": "# Note\n[[valid]] [[wrong.md]] ![[image.png]]\n`[[example.md]]`\n```markdown\n[[example.md]]\n```\n",
        "wiki/_sources/private.md": "[[protected.md]]\n",
    }
    for relative, text in content.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    issues = sweep(tmp_path)
    assert set(issues) == {
        "UNDATED_FILE\tJournal/undated.md",
        "UNDATED_FILE\twiki/topic/diary/2026-W40.md",
        "UNDATED_FILE\twiki/topic/diary/undated.md",
        "WIKILINK_EXT\twiki/note.md:2\t[[wrong.md]]",
    }


def test_yaml_errors_are_single_lines_and_missing_files_are_skipped(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    malformed = folder / "malformed.md"
    malformed.write_text("---\ntitle: [broken\n---\n# Note\n")
    unavailable = folder / "unavailable.md"
    unavailable.write_text("[[wrong.md]]\n")
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == unavailable:
            raise OSError("file disappeared during sync")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    issues = sweep(tmp_path)
    assert len(issues) == 1
    assert issues[0].startswith("YAML_ERR\twiki/malformed.md\t")
    assert "expected ',' or ']'" in issues[0]
    assert " | " in issues[0]
    assert "\n" not in issues[0]
