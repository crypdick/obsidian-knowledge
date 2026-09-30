"""Structured search output reports the retrieval used for each query."""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import memweave
import pytest

from lib.vault_index import cli, indexer
from lib.vault_index.config import VaultIndexConfig


@pytest.fixture
def keyword_index(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("# Orchids\n\nPurple orchids grow in the greenhouse.\n")
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), vector_enabled=False)
    instance.full_reindex()
    try:
        yield instance
    finally:
        asyncio.run(instance._store.close())


def test_keyword_report_contains_hits_and_empty_results(keyword_index):
    report = keyword_index.search_report("greenhouse", top_k=1)
    assert report.mode == "keyword"
    assert report.degraded_reason == "disabled-by-caller"
    assert len(report.hits) == 1
    assert report.hits[0].path == "wiki/orchid.md"
    assert report.hits[0].score == 0.0
    assert report.hits[0].weight_applied == 1.0
    assert "greenhouse" in report.hits[0].snippet
    assert keyword_index.search("greenhouse", top_k=1) == report.hits
    empty = keyword_index.search_report("nonexistentzzzz")
    assert empty.mode == "keyword"
    assert empty.degraded_reason == "disabled-by-caller"
    assert empty.hits == []


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("query_vec (got None)", "query embedding unavailable"),
        ("no such table: chunks_vec", "vector index unavailable"),
    ],
)
def test_report_tracks_query_fallback_then_hybrid_success(tmp_path, monkeypatch, message, reason):
    (tmp_path / "note.md").write_text("An orchid note.")
    instance = indexer.Indexer(tmp_path, tmp_path / "cache", VaultIndexConfig(), skip_probe=True)
    calls = 0

    async def retrieve(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise memweave.SearchError(message)
        return [SimpleNamespace(path=str(tmp_path / "note.md"), score=0.5)]

    monkeypatch.setattr(instance._store, "search", retrieve)
    try:
        fallback = instance.search_report("orchid", allow_rebuild=False)
        assert fallback.mode == "keyword"
        assert fallback.degraded_reason == reason
        assert instance.vector_enabled is True
        hybrid = instance.search_report("orchid", allow_rebuild=False)
        assert hybrid.mode == "hybrid"
        assert hybrid.degraded_reason is None
        assert [hit.model_dump() for hit in hybrid.hits] == [
            {"path": "note.md", "score": 50.0, "weight_applied": 1.0, "snippet": "An orchid note."}
        ]
    finally:
        asyncio.run(instance._store.close())


@pytest.mark.parametrize("query", ["orchids", "nonexistentzzzz"])
def test_search_json_stdout_is_one_document(keyword_index, monkeypatch, capsys, query):
    monkeypatch.setattr(indexer, "Indexer", lambda **kwargs: keyword_index)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "obsidian-knowledge",
            "search",
            query,
            "--json",
            "--all",
            "--top-k",
            "1",
            "--vault",
            str(keyword_index.vault_root),
        ],
    )
    assert cli.main() == 0
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert set(report) == {"mode", "degraded_reason", "hits"}
    assert report["mode"] == "keyword"
    assert report["degraded_reason"] == "disabled-by-caller"
    assert "search ranking degraded" in output.err
    if query == "orchids":
        assert report["hits"][0]["path"] == "wiki/orchid.md"
        assert set(report["hits"][0]) == {"path", "score", "weight_applied", "snippet"}
    else:
        assert report["hits"] == []


def test_json_search_errors_do_not_emit_success(keyword_index, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise cli.SearchTimeoutError("search deadline exhausted")

    monkeypatch.setattr(indexer, "Indexer", lambda **kwargs: keyword_index)
    monkeypatch.setattr(keyword_index, "search_report", fail)
    monkeypatch.setattr(cli, "_exit_hard", lambda code: (_ for _ in ()).throw(SystemExit(code)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["obsidian-knowledge", "search", "orchids", "--json", "--vault", str(keyword_index.vault_root)],
    )
    with pytest.raises(SystemExit) as error:
        cli.cli_main()
    assert error.value.code == 124
    output = capsys.readouterr()
    assert output.out == ""
    assert "timed out" in output.err
