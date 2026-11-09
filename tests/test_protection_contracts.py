"""Cross-consumer protection contracts through the neutral checker boundary."""

import json
import os
from pathlib import Path

import pytest

from tests.test_i_insist_rules import file_event, run_check


@pytest.mark.parametrize(
    "path,blocked",
    [
        ("wiki/locked/note.md", True),
        ("wiki/locked.md", False),
        ("wiki/locked-other/note.md", False),
        ("records/private.md", True),
    ],
)
def test_nested_readonly_policy_uses_path_boundaries(tmp_path, path, blocked):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "ai_readonly_folders: [wiki/locked]\nai_readonly_root_files: [records/private.md]\n"
    )
    result = run_check(tmp_path, "ai-readonly", file_event(tmp_path, path))
    assert result.returncode == 0, result.stderr
    assert (json.loads(result.stdout) is not None) is blocked


@pytest.mark.parametrize("basename", ["2026-W45.md", "2026-M11.md", "2026-Y.md", "All years.md"])
def test_periodic_journal_creation_matches_gardener(tmp_path, basename):
    result = run_check(tmp_path, "dated-filenames", file_event(tmp_path, "Journal/" + basename))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is None


@pytest.mark.parametrize("opening,closing", [("\ufeff---\n", "---\n"), ("--- \r\n", "... \r\n")])
def test_published_envelope_variants_need_consent(tmp_path, opening, closing):
    (tmp_path / "live.md").write_bytes((opening + "dg-publish: true\n" + closing + "body").encode())
    result = run_check(tmp_path, "published-files", file_event(tmp_path, "live.md", "replacement"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is not None


@pytest.mark.parametrize(
    "command",
    [
        "printf changed > wiki/locked/note.md",
        "rm wiki/locked/note.md",
        "sed -i s/old/new/ records/private.md",
    ],
)
def test_shell_respects_nested_readonly_paths(tmp_path, command):
    Path(os.environ["OBSIDIAN_KNOWLEDGE_CONFIG"]).write_text(
        "ai_readonly_folders: [wiki/locked]\nai_readonly_root_files: [records/private.md]\n"
    )
    event = {"kind": "shell", "cwd": str(tmp_path), "command": command, "changes": []}
    result = run_check(tmp_path, "ai-readonly", event)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is not None


@pytest.mark.parametrize("entry", ["", ".", "..", "../locked", "/locked", "wiki//locked", "wiki\\locked"])
def test_readonly_configuration_rejects_unusable_paths(entry):
    from hookslib.vault_policy import VaultPolicy
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="vault-relative"):
        VaultPolicy(ai_readonly_folders=(entry,))
