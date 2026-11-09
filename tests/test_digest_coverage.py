"""Digest notes stay findable while other notes dominate keyword matches or indexing."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lib.vault_index.config import DigestFilter, VaultIndexConfig
from lib.vault_index.index_generations import publish_generation
from lib.vault_index.indexer import Indexer

CONFIG = VaultIndexConfig(digest=DigestFilter(allow_regex=["^wiki/"]))


def make_vault(root: Path) -> Path:
    vault = root / "vault"
    (vault / "Utility").mkdir(parents=True)
    (vault / "wiki").mkdir()
    for number in range(200):
        (vault / f"Utility/run{number:03}.md").write_text(
            f"# Run {number}\n\nworkaround workaround workaround\n"
        )
    (vault / "wiki/fix.md").write_text(
        "# Fix\n\nThe documented workaround for the sync bug, explained at length.\n"
    )
    return vault


def test_keyword_search_finds_digest_note_crowded_out_by_other_matches(tmp_path):
    vault = make_vault(tmp_path)
    instance = Indexer(vault, tmp_path / "cache", CONFIG, vector_enabled=False)
    try:
        instance.full_reindex()
        report = instance.search_report("workaround")
        everything = instance.search_report("workaround", override_digest_filter=True)
    finally:
        asyncio.run(instance._store.close())
    assert report.mode == "keyword"
    assert [hit.path for hit in report.hits] == ["wiki/fix.md"]
    assert len(everything.hits) == CONFIG.top_k


def test_rebuild_embeds_digest_notes_first(tmp_path, fake_ollama):
    vault = make_vault(tmp_path)
    instance = Indexer(vault, tmp_path / "cache", CONFIG)
    try:
        instance.full_reindex()
    finally:
        asyncio.run(instance._store.close())
    assert "documented workaround" in fake_ollama.texts[0]


def test_empty_digest_result_reports_matches_outside_digest(tmp_path, monkeypatch, capsys):
    import json
    import sys

    from lib.vault_index import cli, indexer

    vault = tmp_path / "vault"
    (vault / "Utility").mkdir(parents=True)
    (vault / "Utility/run.md").write_text("# Run\n\nA papercut appeared.\n")
    cache = cli.default_cache_dir_for_vault(vault)
    generation = cache / "generation-a"
    instance = Indexer(vault, generation, CONFIG, vector_enabled=False)
    instance.full_reindex()
    publish_generation(cache, generation)
    try:
        report = instance.search_report("papercut")
        assert (report.hits, report.outside_digest_matches) == ([], 1)
        assert instance.search_report("absentzzz").outside_digest_matches == 0
        assert instance.search_report("papercut", override_digest_filter=True).outside_digest_matches == 0

        monkeypatch.setattr(indexer, "Indexer", lambda **kwargs: instance)
        for json_output in (False, True):
            arguments = ["obsidian-knowledge", "search", "papercut", "--vault", str(vault)]
            monkeypatch.setattr(sys, "argv", arguments + (["--json"] if json_output else []))
            assert cli.main() == 0
            output = capsys.readouterr()
            assert "1 matching note outside the default digest; rerun with --all" in output.err
            if json_output:
                assert json.loads(output.out)["outside_digest_matches"] == 1
    finally:
        asyncio.run(instance._store.close())


def test_hybrid_search_finds_digest_note_crowded_out_by_other_matches(tmp_path, fake_ollama):
    vault = make_vault(tmp_path)
    instance = Indexer(vault, tmp_path / "cache", CONFIG)
    try:
        instance.full_reindex()
        report = instance.search_report("workaround")
        assert report.mode == "hybrid"
        assert [hit.path for hit in report.hits] == ["wiki/fix.md"]
        assert len(instance.search_report("workaround", override_digest_filter=True).hits) == CONFIG.top_k
        # Per-request eligibility must not leak into later searches on same Indexer.
        assert [hit.path for hit in instance.search_report("workaround").hits] == ["wiki/fix.md"]
    finally:
        asyncio.run(instance._store.close())
