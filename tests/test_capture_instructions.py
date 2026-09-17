"""Regression tests for durable-note capture instructions."""

from __future__ import annotations

import json
from pathlib import Path

from hookslib.capture import build_reason, capture_session_key, main, resolve_capture_vault

ROOT = Path(__file__).parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_capture_uses_verified_filesystem_writes_without_cli_placeholders() -> None:
    skill = _read("skills/remember-conversations/SKILL.md")

    assert "obsidian-knowledge write" in skill
    assert "Wrote and verified" in skill
    assert "note first" in skill
    assert "obsidian vault=" not in skill
    assert "create the empty file" not in skill
    assert "content=" not in skill


def test_general_skill_uses_configured_verified_vault_io() -> None:
    skill = _read("skills/obsidian-knowledge/SKILL.md")

    assert "obsidian-knowledge read" in skill
    assert "obsidian-knowledge write" in skill
    assert "/Users/ricardo/" not in skill
    assert "cat >" not in skill
    assert "echo " not in skill


def test_changelog_capture_never_requires_a_shared_index() -> None:
    capture_surfaces = (
        "hooks/hookslib/capture.py",
        "skills/remember-conversations/SKILL.md",
        "skills/vault-organizer/SKILL.md",
        "skills/vault-organizer/lib/state-files.md",
    )

    for path in capture_surfaces:
        text = _read(path)
        assert "Immediately add" not in text, path
        assert "Add the new changelog file" not in text, path

    assert "do not edit a shared changelog index" in build_reason("/vault").lower()
    assert "index_path" not in _read("hooks/hookslib/capture.py")
    assert "do not create or update `changelog/index.md`" in _read(
        "skills/vault-organizer/lib/state-files.md"
    )
    assert "Utility\nzone is excluded" in _read("skills/vault-organizer/lib/state-files.md")


def test_manifests_register_one_capture_hook() -> None:
    codex = json.loads(_read("hooks/codex-hooks.json"))
    claude = json.loads(_read(".claude-plugin/plugin.json"))

    codex_commands = [
        hook["command"]
        for group in codex["hooks"]["Stop"]
        for hook in group["hooks"]
        if "capture" in hook["command"] or "changelog" in hook["command"] or "convos" in hook["command"]
    ]
    claude_commands = [
        hook["command"]
        for group in claude["hooks"]["Stop"]
        for hook in group["hooks"]
        if "capture" in hook["command"] or "changelog" in hook["command"] or "convos" in hook["command"]
    ]

    # Keep one legacy kind in the manifest for new-plugin/old-CLI rolling
    # compatibility. CLI 3.22.30+ dispatches it to capture-session.py.
    assert codex_commands == ["obsidian-knowledge _hook stop --kind remind-convos --agent codex"]
    assert claude_commands == ["python3 ${CLAUDE_PLUGIN_ROOT}/hooks/capture-session.py"]


def test_capture_policy_reverses_old_overcapture_defaults() -> None:
    reason = build_reason("/vault")
    skill = _read("skills/remember-conversations/SKILL.md")
    primer = _read("lib/vault_index/primer.py")

    assert "Default: file nothing" in reason
    assert "If you cannot state it, do not file" in reason
    assert "Default output for any Q&A" not in skill
    assert "Every durable note must be self-contained" in skill
    assert "In doubt for educational Q&A" not in skill
    assert "Always preserve user's questions" not in skill
    assert "Single session can produce multiple types" not in skill
    assert "### Always" not in skill
    assert "filing nothing as success" in primer
    assert "at most 20 bullets or 6000 characters" in primer
    assert "second generated memory/index.md" in primer


def test_capture_session_key_is_absent_without_session_identity() -> None:
    assert capture_session_key(None) is None
    assert capture_session_key("") is None


def test_capture_reason_without_session_key_explains_fallback_reuse() -> None:
    reason = build_reason("/vault")
    assert "Search current-day fragments" in reason
    assert "capture key" not in reason


def test_capture_vault_resolution_requires_unambiguous_destination(monkeypatch) -> None:
    monkeypatch.setattr("hookslib.capture.load_vault_roots", lambda: ["/first", "/second"])
    monkeypatch.setattr("hookslib.capture.matching_vault_root", lambda cwd, roots: None)
    assert resolve_capture_vault("/outside") is None


def test_capture_main_is_silent_without_resolved_vault(monkeypatch) -> None:
    monkeypatch.setattr("hookslib.capture.read_input", lambda: {"session_id": "session"})
    monkeypatch.setattr("hookslib.capture.resolve_capture_vault", lambda cwd: None)
    assert main() == 0
