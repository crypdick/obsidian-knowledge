"""Tests for durable papercut recording."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.vault_index.papercuts import (
    PAPERCUTS_INDEX_NAME,
    PAPERCUTS_RELATIVE_DIR,
    record_papercut,
)


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    knowledge_base = vault / "wiki" / "systems" / "knowledge-base"
    knowledge_base.mkdir(parents=True)
    (knowledge_base / "index.md").write_text("# Knowledge Base\n\n## Unindexed\n")
    return vault


def test_record_papercut_creates_immutable_report_and_indexes_it(tmp_path: Path):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    record = record_papercut(
        vault,
        "Search hung after automatic rebuild",
        cwd=workdir,
        now=datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC),
    )

    assert record.index_error is None
    assert record.path.parent == vault / PAPERCUTS_RELATIVE_DIR
    assert record.path.name.startswith("2026-07-13-123456-search-hung-after-automatic-rebuild-")
    text = record.path.read_text()
    assert "created: 2026-07-13T12:34:56Z" in text
    assert "type: papercut" in text
    assert "status: open" in text
    assert "Search hung after automatic rebuild" in text
    assert f"Working directory: `{workdir.resolve()}`" in text
    assert "updated:" not in text

    papercuts_index = (vault / PAPERCUTS_RELATIVE_DIR / PAPERCUTS_INDEX_NAME).read_text()
    assert f"[[{record.path.stem}]]" in papercuts_index
    parent_index = (vault / "wiki" / "systems" / "knowledge-base" / "index.md").read_text()
    assert parent_index == "# Knowledge Base\n\n## Unindexed\n"


def test_record_papercut_preserves_repeated_reports_as_separate_occurrences(tmp_path: Path):
    vault = _make_vault(tmp_path)
    timestamp = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)

    first = record_papercut(vault, "The same command failed twice", now=timestamp)
    second = record_papercut(vault, "The same command failed twice", now=timestamp)

    assert first.path != second.path
    reports = sorted((vault / PAPERCUTS_RELATIVE_DIR).glob("*.md"))
    assert len(reports) == 3  # two reports plus index.md
    index = (vault / PAPERCUTS_RELATIVE_DIR / PAPERCUTS_INDEX_NAME).read_text()
    assert f"[[{first.path.stem}]]" in index
    assert f"[[{second.path.stem}]]" in index


def test_record_papercut_handles_concurrent_reports_without_losing_index_entries(tmp_path: Path):
    vault = _make_vault(tmp_path)
    timestamp = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(
            pool.map(
                lambda number: record_papercut(vault, f"concurrent friction {number}", now=timestamp),
                range(8),
            )
        )

    assert len({record.path for record in records}) == 8
    index = (vault / PAPERCUTS_RELATIVE_DIR / PAPERCUTS_INDEX_NAME).read_text()
    for record in records:
        assert f"[[{record.path.stem}]]" in index


def test_record_papercut_keeps_yaml_looking_text_in_the_report_body(tmp_path: Path):
    vault = _make_vault(tmp_path)
    report = "---\nstatus: solved\n---\nThe tool still made us retry."

    record = record_papercut(vault, report)

    text = record.path.read_text()
    assert text.count("---") == 4
    assert "## Friction\n\n---\nstatus: solved\n---" in text


def test_record_papercut_rejects_blank_descriptions(tmp_path: Path):
    vault = _make_vault(tmp_path)

    with pytest.raises(ValueError, match="must not be blank"):
        record_papercut(vault, "  \n\t")


def test_record_papercut_rejects_missing_vault(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        record_papercut(tmp_path / "missing", "This cannot be written")


def test_record_papercut_keeps_report_when_index_update_fails(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)

    def fail_index_update(_papercuts_dir: Path) -> None:
        raise OSError("simulated full disk")

    monkeypatch.setattr(
        "lib.vault_index.papercuts._rebuild_papercuts_index",
        fail_index_update,
    )

    record = record_papercut(vault, "The report itself must survive an index failure")

    assert record.path.is_file()
    assert record.index_error == "simulated full disk"
