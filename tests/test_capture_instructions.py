"""Regression tests for durable-note capture instructions."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remember_conversations_places_global_vault_option_before_command() -> None:
    skill = _read("skills/remember-conversations/SKILL.md")

    assert 'obsidian vault="<vault-name>" create' in skill
    assert "obsidian create path=" not in skill
    assert 'create path="<subtree>/<concept>.md" content=' not in skill
    assert 'create path="{subtree}/convos/YYYY-MM-DD-slug.md" content=' not in skill


def test_changelog_capture_never_requires_a_shared_index() -> None:
    capture_surfaces = (
        "hooks/update-changelog.py",
        "skills/remember-conversations/SKILL.md",
        "skills/vault-organizer/SKILL.md",
        "skills/vault-organizer/lib/state-files.md",
    )

    for path in capture_surfaces:
        text = _read(path)
        assert "Immediately add" not in text, path
        assert "Add the new changelog file" not in text, path

    build_reason = runpy.run_path(str(ROOT / "hooks" / "update-changelog.py"))["build_reason"]
    assert "Do not edit a shared changelog index" in build_reason("/vault")
    assert "index_path" not in _read("hooks/update-changelog.py")
    assert "do not create or update `changelog/index.md`" in _read(
        "skills/vault-organizer/lib/state-files.md"
    )
    assert "Utility\nzone is excluded" in _read("skills/vault-organizer/lib/state-files.md")
