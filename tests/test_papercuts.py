"""Tests for durable papercut recording."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lib.vault_index.papercuts import (
    GLOBAL_PAPERCUTS_RELATIVE_PATH,
    PAPERCUTS_FILENAME,
    record_papercut,
)


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    knowledge_base = vault / "wiki" / "systems" / "knowledge-base"
    knowledge_base.mkdir(parents=True)
    (knowledge_base / "index.md").write_text("# Knowledge Base\n\n## Unindexed\n")
    return vault


def _git_init(path: Path, remote: str | None = None) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", "origin", remote],
            check=True,
        )


@pytest.mark.parametrize(
    ("remote", "owner", "repo"),
    [
        ("git@github.com:acme/agent-tools.git", "acme", "agent-tools"),
        ("https://github.com/acme/agent-tools.git", "acme", "agent-tools"),
        ("ssh://git@github.com/acme/agent-tools", "acme", "agent-tools"),
        ("git+ssh://git@github.com/acme/agent-tools", "acme", "agent-tools"),
        ("git@gitlab.com:group/sub/project.git", "sub", "project"),
    ],
)
def test_record_papercut_scopes_log_to_safe_hosted_origins(
    tmp_path: Path,
    remote: str,
    owner: str,
    repo: str,
):
    vault = _make_vault(tmp_path)
    repository = tmp_path / "work"
    _git_init(repository, remote)
    workdir = repository / "deep" / "nested"
    workdir.mkdir(parents=True)

    record = record_papercut(vault, "The repository-specific command was unclear", cwd=workdir)

    assert record.path == vault / "wiki" / "repos" / owner / repo / PAPERCUTS_FILENAME
    text = record.path.read_text()
    assert "scope: repo" in text
    assert f"repository: {owner}/{repo}" in text
    assert f"# Papercuts — {owner}/{repo}" in text
    assert not (vault / GLOBAL_PAPERCUTS_RELATIVE_PATH).exists()


def test_record_papercut_appends_entry_to_global_log(tmp_path: Path):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    legacy_report = vault / "wiki" / "systems" / "knowledge-base" / "papercuts" / "old-entry.md"
    legacy_report.parent.mkdir()
    legacy_report.write_text("A legacy report with no safe repository scope.\n")

    record = record_papercut(
        vault,
        "Search hung after automatic rebuild",
        cwd=workdir,
        now=datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC),
    )

    assert record.path == vault / GLOBAL_PAPERCUTS_RELATIVE_PATH
    text = record.path.read_text()
    assert "type: papercut-log" in text
    assert "scope: global" in text
    assert "# Papercuts" in text
    assert "## 2026-07-13 12:34:56 UTC" in text
    assert "- Status: open" in text
    assert "Search hung after automatic rebuild" in text
    assert f"Working directory: `{workdir.resolve()}`" in text
    assert "updated:" not in text

    parent_index = (vault / "wiki" / "systems" / "knowledge-base" / "index.md").read_text()
    assert parent_index == "# Knowledge Base\n\n## Unindexed\n"
    assert legacy_report.read_text() == "A legacy report with no safe repository scope.\n"


@pytest.mark.parametrize(
    "remote",
    [
        None,
        "file:///tmp/acme/agent-tools.git",
        "/tmp/acme/agent-tools.git",
        "not-a-url",
        "https://github.com/only-one-path-component",
        "git@github.com:../escape",
        "https://github.com/acme/..",
    ],
)
def test_record_papercut_uses_global_fallback_without_a_safe_origin(
    tmp_path: Path,
    remote: str | None,
):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    _git_init(workdir, remote)

    record = record_papercut(vault, "A local prototype had no safe remote", cwd=workdir)

    assert record.path == vault / GLOBAL_PAPERCUTS_RELATIVE_PATH


def test_record_papercut_uses_global_fallback_when_git_is_unavailable(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    def unavailable_git(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("lib.vault_index.papercuts.subprocess.run", unavailable_git)

    record = record_papercut(vault, "Git was unavailable while recording", cwd=workdir)

    assert record.path == vault / GLOBAL_PAPERCUTS_RELATIVE_PATH


def test_record_papercut_preserves_repeated_reports_as_separate_occurrences(tmp_path: Path):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    timestamp = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)

    first = record_papercut(vault, "The same command failed twice", cwd=workdir, now=timestamp)
    second = record_papercut(vault, "The same command failed twice", cwd=workdir, now=timestamp)

    assert first.path == second.path == vault / GLOBAL_PAPERCUTS_RELATIVE_PATH
    text = first.path.read_text()
    assert text.count("## 2026-07-13 12:34:56 UTC") == 2
    assert text.count("The same command failed twice") == 2


def test_record_papercut_handles_concurrent_reports_without_interleaving_entries(tmp_path: Path):
    vault = _make_vault(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    timestamp = datetime(2026, 7, 13, 12, 34, 56, tzinfo=UTC)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(
            pool.map(
                lambda number: record_papercut(
                    vault,
                    f"concurrent friction {number}",
                    cwd=workdir,
                    now=timestamp,
                ),
                range(8),
            )
        )

    assert {record.path for record in records} == {vault / GLOBAL_PAPERCUTS_RELATIVE_PATH}
    text = (vault / GLOBAL_PAPERCUTS_RELATIVE_PATH).read_text()
    assert text.count("## 2026-07-13 12:34:56 UTC") == 8
    for number in range(8):
        assert f"concurrent friction {number}" in text


def test_record_papercut_keeps_yaml_looking_text_in_the_log_entry(tmp_path: Path):
    vault = _make_vault(tmp_path)
    report = "---\nstatus: solved\n---\nThe tool still made us retry."

    record = record_papercut(vault, report, cwd=tmp_path)

    text = record.path.read_text()
    assert text.count("---") == 4
    assert "- Status: open\n- Working directory:" in text
    assert "\n\n---\nstatus: solved\n---" in text


def test_record_papercut_rejects_blank_descriptions(tmp_path: Path):
    vault = _make_vault(tmp_path)

    with pytest.raises(ValueError, match="must not be blank"):
        record_papercut(vault, "  \n\t")


def test_record_papercut_rejects_missing_vault(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        record_papercut(tmp_path / "missing", "This cannot be written")


def test_record_papercut_surfaces_log_write_failures(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)

    def fail_append(*_args) -> None:
        raise OSError("simulated full disk")

    monkeypatch.setattr("lib.vault_index.papercuts._append_papercut", fail_append)

    with pytest.raises(OSError, match="simulated full disk"):
        record_papercut(vault, "The log must not claim a failed write succeeded", cwd=tmp_path)
