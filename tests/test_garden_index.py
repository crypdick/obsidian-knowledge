"""Reviewed index input rejects ambiguity and preserves untouched sections."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gardener import index


def run_index(vault: Path, review: dict, monkeypatch, relative: str = "wiki/index.md") -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(review)))
    index.main(["--vault", str(vault), relative])


@pytest.mark.parametrize(
    "review",
    [
        {"title": "", "entries": []},
        {"section": "Bad\nHeading", "entries": []},
        {"entries": [{"target": "", "description": "note"}]},
        {"entries": [{"target": "note", "label": "[bad]", "description": "note"}]},
        {"entries": [{"target": "note", "description": ""}]},
        {"entries": [{"target": "note", "description": "two\nlines"}]},
        {"entries": []},
        {"title": "Wiki", "section": "Notes", "entries": []},
    ],
)
def test_invalid_review_cannot_create_index(tmp_path: Path, monkeypatch, capsys, review: dict) -> None:
    (tmp_path / "wiki").mkdir()
    with pytest.raises(SystemExit) as exc:
        run_index(tmp_path, review, monkeypatch)
    assert exc.value.code == 1
    assert "Error:" in capsys.readouterr().err
    assert not (tmp_path / "wiki/index.md").exists()


@pytest.mark.parametrize(
    ("before", "review", "error"),
    [
        ("# Wiki\n\n## Notes\n", {"entries": []}, "explicit section"),
        ("# Wiki\n\n## Notes\n### Child\n", {"section": "Notes", "entries": []}, "leaf section"),
        (
            "# Wiki\n\n- [[index]] — self\n",
            {"entries": [{"target": "index", "description": "self"}]},
            "link to itself",
        ),
        (
            "# Wiki\n\n- [[note]] — first\n- [[wiki/note]] — duplicate\n",
            {"entries": [{"target": "note", "description": "update"}]},
            "duplicate existing entries",
        ),
        ("# Wiki\n\n- [[note]] — first\n\n- [[other]] — second\n", {"entries": []}, "multiple entry blocks"),
    ],
)
def test_ambiguous_existing_index_stays_intact(
    tmp_path: Path, monkeypatch, capsys, before, review, error
) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    destination = folder / "index.md"
    destination.write_text(before)
    (folder / "note.md").write_text("# Note\n")
    with pytest.raises(SystemExit):
        run_index(tmp_path, review, monkeypatch)
    assert error in capsys.readouterr().err
    assert destination.read_text() == before


def test_existing_missing_targets_are_preserved_during_review(tmp_path: Path, monkeypatch, capsys) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    destination = folder / "index.md"
    before = "# Wiki\n\n- [[missing]] — retain for review\n- [[note]] — old\n"
    destination.write_text(before)
    (folder / "note.md").write_text("# Note\n")
    run_index(tmp_path, {"entries": [{"target": "note", "description": "updated"}]}, monkeypatch)
    assert capsys.readouterr().out == "# Wiki\n\n- [[missing]] — retain for review\n- [[note]] — updated\n"
    assert destination.read_text() == before


@pytest.mark.parametrize(
    ("before", "review", "expected"),
    [
        ("", {"entries": [{"target": "note", "description": "note"}]}, "- [[note]] — note\n"),
        ("# Wiki", {"entries": [{"target": "note", "description": "note"}]}, "# Wiki\n\n- [[note]] — note\n"),
        (
            "# Wiki\n",
            {"entries": [{"target": "note", "description": "note"}]},
            "# Wiki\n\n- [[note]] — note\n",
        ),
        (
            "# Wiki\n## Notes\n## Other\nKeep.\n",
            {"section": "Notes", "entries": [{"target": "note", "description": "note"}]},
            "# Wiki\n## Notes\n\n- [[note]] — note\n\n## Other\nKeep.\n",
        ),
        ("# Wiki\n## Notes\n\n", {"section": "Notes", "entries": []}, "# Wiki\n## Notes\n\n"),
        (
            "# Wiki\n\n- [[note]] — old\nTrailing prose.\n",
            {"entries": [{"target": "note", "description": "note"}]},
            "# Wiki\n\n- [[note]] — note\nTrailing prose.\n",
        ),
    ],
)
def test_empty_sections_and_prose_preserve_layout(
    tmp_path: Path, monkeypatch, capsys, before, review, expected
) -> None:
    folder = tmp_path / "wiki"
    folder.mkdir()
    (folder / "index.md").write_text(before)
    (folder / "note.md").write_text("# Note\n")
    run_index(tmp_path, review, monkeypatch)
    assert capsys.readouterr().out == expected
    assert (folder / "index.md").read_text() == before


def test_only_index_filename_is_editable(tmp_path: Path, monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit):
        run_index(tmp_path, {"entries": []}, monkeypatch, "wiki/note.md")
    assert "only edits index.md" in capsys.readouterr().err
