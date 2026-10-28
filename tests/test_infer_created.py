"""Opt-in estimates retain their basis and preserve the backfill's safeguards."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.backfill_created import Evidence, EvidenceFile, ScanOptions, apply_plan, make_plan
from scripts.infer_created import InferenceOptions, Observation, Observations, infer_evidence, main


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "wiki").mkdir(parents=True)
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text("ai_managed: [wiki]\n")
    return root


def test_filename_is_authoritative_only_when_explicitly_enabled(vault):
    path = vault / "wiki/2020-01-02 appointment.md"
    path.write_text("# Document about an event\n")
    plan = make_plan(vault, ScanOptions())
    assert not infer_evidence(plan, InferenceOptions()).records
    evidence = infer_evidence(plan, InferenceOptions(filename_dates=True, mtime=True))
    record = evidence.records[0]
    assert record.created.root.isoformat() == "2020-01-02"
    assert not record.estimated
    assert record.source.startswith("Accepted filename date:")
    repaired = make_plan(vault, ScanOptions(evidence=evidence))
    assert apply_plan(vault, repaired).applied == ("wiki/2020-01-02 appointment.md",)


def test_future_and_invalid_filename_dates_fall_back_to_observation(vault):
    for name in ("2099-01-01.md", "2020-99-99.md", "2020-01-011.md"):
        (vault / "wiki" / name).write_text("# Body\n")
    observations = Observations(
        records=tuple(
            Observation(path=f"wiki/{name}", observed="2021-01-01", source="backup")
            for name in ("2099-01-01.md", "2020-99-99.md", "2020-01-011.md")
        )
    )
    evidence = infer_evidence(
        make_plan(vault, ScanOptions()), InferenceOptions(filename_dates=True, observations=observations)
    )
    assert len(evidence.records) == 3
    assert all(item.estimated and item.created.root.isoformat() == "2021-01-01" for item in evidence.records)


def test_oldest_modification_or_backup_observation_wins_with_date_precision(vault):
    path = vault / "wiki/note.md"
    path.write_text("---\nupdated: 2022-01-01\nmodified: 2021-01-01\n---\n# Body\n")
    evidence = infer_evidence(make_plan(vault, ScanOptions()), InferenceOptions(mtime=True))
    assert evidence.records[0].created.root.isoformat() == "2021-01-01"
    assert evidence.records[0].estimated
    observations = Observations(
        records=(Observation(path="wiki/note.md", observed="2020-01-01", source="old snapshot"),)
    )
    evidence = infer_evidence(
        make_plan(vault, ScanOptions()), InferenceOptions(mtime=True, observations=observations)
    )
    assert evidence.records[0].created.root.isoformat() == "2020-01-01"
    assert "old snapshot" in evidence.records[0].source


def test_old_version_modification_beats_recent_rewrite(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Current\n")
    history = tmp_path / "versions/wiki"
    history.mkdir(parents=True)
    old = history / "note~20250101-000000.md"
    old.write_text("# Old\n")
    stamp = datetime(2020, 1, 2, 12, tzinfo=UTC).timestamp()
    os.utime(old, (stamp, stamp))
    evidence = infer_evidence(
        make_plan(vault, ScanOptions()), InferenceOptions(mtime=True, history=history.parent)
    )
    assert evidence.records[0].created.root.isoformat() == "2020-01-02"
    assert str(old) in evidence.records[0].source


def test_historical_created_precedes_modification_and_conflict_is_explicit(vault, tmp_path):
    (vault / "wiki/note.md").write_text("# Current\n")
    history = tmp_path / "versions/wiki"
    history.mkdir(parents=True)
    (history / "note.md").write_text("---\ncreated: 2020-01-02\n---\n# Old\n")
    (history / "note~20250101-000000.md").write_text("---\ncreated: 2020-01-01\n---\n# Old\n")
    evidence = infer_evidence(
        make_plan(vault, ScanOptions()), InferenceOptions(mtime=True, history=history.parent)
    )
    assert evidence.records[0].created.root.isoformat() == "2020-01-01"
    assert "conflicting historical" in evidence.records[0].source
    assert evidence.records[0].estimated


def test_filename_precedes_creation_log_when_explicitly_accepted(vault):
    relative = "wiki/2020-01-01.md"
    (vault / relative).write_text("# Body\n")
    proof = EvidenceFile(records=(Evidence(path=relative, created="2021-01-01", source="creation log"),))
    plan = make_plan(vault, ScanOptions(evidence=proof))
    assert infer_evidence(plan, InferenceOptions()).records[0].created.root.isoformat() == "2021-01-01"
    assert (
        infer_evidence(plan, InferenceOptions(filename_dates=True)).records[0].created.root.isoformat()
        == "2020-01-01"
    )


def test_existing_properties_and_new_protected_paths_are_preserved(vault):
    (vault / "wiki/2020-01-01.md").write_text("# Body\n")
    plan = make_plan(vault, ScanOptions())
    (vault / "wiki/2020-01-01.md").write_text("---\ncreated: \n---\n# Existing explicit empty\n")
    assert not infer_evidence(plan, InferenceOptions(filename_dates=True, mtime=True)).records


def test_estimates_are_bound_to_content_before_application(vault):
    note = vault / "wiki/2020-01-01.md"
    note.write_text("# Original\n")
    evidence = infer_evidence(make_plan(vault, ScanOptions()), InferenceOptions(filename_dates=True))
    note.write_text("# Changed\n")
    plan = make_plan(vault, ScanOptions(evidence=evidence))
    assert not plan.candidates
    assert len(plan.unresolved) == 1


def test_old_filename_dates_are_valid_but_epoch_filesystem_timestamps_are_ignored(vault):
    (vault / "wiki/1960-01-01 record.md").write_text("# Record\n")
    undated = vault / "wiki/undated.md"
    undated.write_text("# Body\n")
    os.utime(undated, (0, 0))
    evidence = infer_evidence(
        make_plan(vault, ScanOptions()), InferenceOptions(filename_dates=True, mtime=True)
    )
    assert len(evidence.records) == 1
    assert evidence.records[0].created.root.isoformat() == "1960-01-01"


def test_estimated_status_survives_review_and_apply_adds_only_created(vault):
    note = vault / "wiki/undated.md"
    note.write_text("---\nupdated: 2020-01-01\n---\n# Body\n")
    evidence = infer_evidence(make_plan(vault, ScanOptions()), InferenceOptions(mtime=True))
    plan = make_plan(vault, ScanOptions(evidence=evidence))
    assert plan.candidates[0].estimated
    apply_plan(vault, plan)
    assert note.read_text() == '---\ncreated: "2020-01-01"\nupdated: 2020-01-01\n---\n# Body\n'


def test_cli_only_writes_private_evidence_and_refuses_overwrite_or_vault_output(vault, tmp_path):
    note = vault / "wiki/2020-01-01.md"
    note.write_text("# Body\n")
    plan = tmp_path / "plan.json"
    plan.write_text(make_plan(vault, ScanOptions()).model_dump_json())
    evidence = tmp_path / "evidence.json"
    args = ["--input-plan", str(plan), "--output-evidence", str(evidence), "--filename-dates"]
    assert main(args) == 0
    assert json.loads(evidence.read_text())["records"][0]["created"] == "2020-01-01"
    assert evidence.stat().st_mode & 0o777 == 0o600
    assert note.read_text() == "# Body\n"
    with pytest.raises(SystemExit):
        main(args)
    with pytest.raises(SystemExit):
        main(["--input-plan", str(plan), "--output-evidence", str(vault / "evidence.json")])
