from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "vault-organizer" / "recover-unresolved-links.py"


def run_recover(vault: Path, items: list[dict[str, str]], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), *args],
        input=json.dumps(items),
        text=True,
        capture_output=True,
        check=True,
    )


def test_classifies_unique_normalized_match_without_applying(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text("See [[renamed_file]].\n", encoding="utf-8")

    result = run_recover(
        tmp_path,
        [{"link": "renamed_file", "count": "1", "sources": "wiki/source.md"}],
    )

    assert "high-confidence moved/renamed file\trenamed_file" in result.stdout
    assert "wiki/Renamed File.md" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(encoding="utf-8") == "See [[renamed_file]].\n"


def test_skips_broken_markdown_symlinks(tmp_path: Path) -> None:
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "valid.md").write_text("# Valid\n", encoding="utf-8")
    (tmp_path / "wiki" / "broken.md").symlink_to(tmp_path / "missing.md")

    result = run_recover(tmp_path, [])

    assert result.returncode == 0


def test_apply_rewrites_only_auto_fixable_links(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "Renamed File.md").write_text("# Renamed\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text(
        "See [[renamed_file|display]] and [[plain concept]].\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [
            {"link": "renamed_file", "count": "1", "sources": "wiki/source.md"},
            {"link": "plain concept", "count": "1", "sources": "wiki/source.md"},
        ],
        "--apply",
    )

    assert "# applied_rewrites\t1" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(
        encoding="utf-8"
    ) == "See [[wiki/Renamed File|display]] and [[plain concept]].\n"


def test_path_and_date_references_are_missing_not_concept_stubs(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "source.md").write_text(
        "[[2026-04-05-missing]] [[scripts/foo.py]]\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [
            {"link": "2026-04-05-missing", "count": "1", "sources": "wiki/source.md"},
            {"link": "scripts/foo.py", "count": "1", "sources": "wiki/source.md"},
            {"link": "attention head", "count": "1", "sources": "wiki/source.md"},
        ],
        "--include-stubs",
    )

    assert "missing-note/date/path reference\t2026-04-05-missing" in result.stdout
    assert "missing-note/date/path reference\tscripts/foo.py" in result.stdout
    assert "likely intentional concept stub\tattention head" in result.stdout


def test_path_like_links_do_not_fall_back_to_unrelated_basename(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki" / "real").mkdir(parents=True)
    (tmp_path / "Utility" / "obsidian-knowledge").mkdir(parents=True)
    (tmp_path / "wiki" / "real" / "changelog.md").write_text("# Wrong basename\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text(
        "[[Utility/obsidian-knowledge/changelog]]\n", encoding="utf-8"
    )

    result = run_recover(
        tmp_path,
        [{"link": "Utility/obsidian-knowledge/changelog", "count": "1", "sources": "wiki/source.md"}],
        "--apply",
    )

    assert "# applied_rewrites\t0" in result.stdout
    assert "missing-note/date/path reference\tUtility/obsidian-knowledge/changelog" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(
        encoding="utf-8"
    ) == "[[Utility/obsidian-knowledge/changelog]]\n"


def test_ambiguous_fuzzy_candidates_are_not_applied(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "obsidian-knowledge.yaml").write_text("ai_managed: [wiki]\n", encoding="utf-8")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "vault merge design.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "wiki" / "vault merge designs.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "wiki" / "source.md").write_text("[[vault merge desgn]]\n", encoding="utf-8")

    result = run_recover(
        tmp_path,
        [{"link": "vault merge desgn", "count": "1", "sources": "wiki/source.md"}],
        "--apply",
    )

    assert "# applied_rewrites\t0" in result.stdout
    assert "ambiguous candidate\tvault merge desgn" in result.stdout
    assert (tmp_path / "wiki" / "source.md").read_text(encoding="utf-8") == "[[vault merge desgn]]\n"
