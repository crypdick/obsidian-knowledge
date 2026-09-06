"""Integration tests for the consolidated selective capture Stop hook."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
CAPTURE_HOOK = PLUGIN_ROOT / "hooks" / "capture-session.py"
LEGACY_HOOKS = (
    PLUGIN_ROOT / "hooks" / "update-changelog.py",
    PLUGIN_ROOT / "hooks" / "remind-convos.py",
)


def _transcript(tmp_path: Path, messages: int) -> Path:
    path = tmp_path / "transcript.jsonl"
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": f"message {i}"}})
        for i in range(messages)
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def _run(hook: Path, payload: dict, *, cwd: Path, env: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout else {}


def _payload(tmp_path: Path, *, messages: int = 1, active: bool = False) -> dict:
    return {
        "session_id": f"capture-{uuid.uuid4()}",
        "stop_hook_active": active,
        "transcript_path": str(_transcript(tmp_path, messages)),
    }


def test_capture_hook_uses_sole_configured_vault_from_repo_cwd(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    outside = tmp_path / "outside"
    outside.mkdir()

    output = _run(CAPTURE_HOOK, _payload(tmp_path), cwd=outside, env=env)

    assert output["decision"] == "block"
    assert str(vault / "Utility" / "obsidian-knowledge" / "changelog") in output["reason"]


def test_capture_hook_is_silent_without_a_configured_vault(tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    assert _run(CAPTURE_HOOK, _payload(tmp_path), cwd=outside, env={"HOME": str(home)}) == {}


def test_capture_hook_does_not_guess_between_multiple_vaults(tmp_path):
    home = tmp_path / "home"
    config = home / ".config" / "obsidian-knowledge"
    config.mkdir(parents=True)
    first = tmp_path / "vault-one"
    second = tmp_path / "vault-two"
    outside = tmp_path / "outside"
    first.mkdir()
    second.mkdir()
    outside.mkdir()
    (config / "vaults.yaml").write_text(f"vaults:\n  - {first}\n  - {second}\n")

    assert _run(CAPTURE_HOOK, _payload(tmp_path), cwd=outside, env={"HOME": str(home)}) == {}


def test_capture_hook_emits_selective_gate_inside_vault(tmp_path, subprocess_vault):
    vault, env = subprocess_vault

    output = _run(CAPTURE_HOOK, _payload(tmp_path), cwd=vault, env=env)

    assert output["decision"] == "block"
    reason = output["reason"]
    assert "Default: file nothing" in reason
    assert "durable, novel delta" in reason
    assert "Search the vault first" in reason
    assert "at most one durable wiki note" in reason
    assert "transient status/PIDs/job IDs/worktrees" in reason
    assert "do not log code, git, or host changes" in reason
    assert "The capture key is" in reason
    assert "-session-" in reason


def test_same_user_message_generation_emits_once(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = _payload(tmp_path)

    first = _run(CAPTURE_HOOK, payload, cwd=vault, env=env)
    second = _run(CAPTURE_HOOK, payload, cwd=vault, env=env)

    assert first["decision"] == "block"
    assert second == {}


def test_new_user_message_allows_new_capture_decision(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = _payload(tmp_path)
    transcript = Path(payload["transcript_path"])

    assert _run(CAPTURE_HOOK, payload, cwd=vault, env=env)["decision"] == "block"
    with transcript.open("a") as handle:
        handle.write(json.dumps({"type": "user", "message": {"content": "new message"}}) + "\n")

    assert _run(CAPTURE_HOOK, payload, cwd=vault, env=env)["decision"] == "block"


def test_legacy_aliases_share_one_capture_claim(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = _payload(tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(executor.map(lambda hook: _run(hook, payload, cwd=vault, env=env), LEGACY_HOOKS))

    assert sum(output.get("decision") == "block" for output in outputs) == 1


def test_stop_hook_continuation_is_silent(tmp_path, subprocess_vault):
    vault, env = subprocess_vault

    assert _run(CAPTURE_HOOK, _payload(tmp_path, active=True), cwd=vault, env=env) == {}


def test_missing_transcript_claims_once_per_session(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = {"session_id": f"capture-no-transcript-{uuid.uuid4()}"}

    first = _run(CAPTURE_HOOK, payload, cwd=vault, env=env)
    second = _run(CAPTURE_HOOK, payload, cwd=vault, env=env)

    assert first["decision"] == "block"
    assert second == {}


def test_missing_transcript_legacy_aliases_claim_atomically(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = {"session_id": f"capture-no-transcript-race-{uuid.uuid4()}"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(executor.map(lambda hook: _run(hook, payload, cwd=vault, env=env), LEGACY_HOOKS))

    assert sum(output.get("decision") == "block" for output in outputs) == 1


def test_codex_hook_and_goal_continuations_do_not_rearm_capture(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    payload = _payload(tmp_path)
    transcript = Path(payload["transcript_path"])

    def append_user(text):
        with transcript.open("a") as handle:
            handle.write(
                json.dumps({
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    },
                })
                + "\n"
            )

    transcript.write_text("")
    append_user("Please review the code")
    assert _run(CAPTURE_HOOK, payload, cwd=vault, env=env)["decision"] == "block"
    append_user('<hook_prompt hook_run_id="stop:1">Capture once</hook_prompt>')
    append_user('<codex_internal_context source="goal">Continue</codex_internal_context>')
    assert _run(CAPTURE_HOOK, payload, cwd=vault, env=env) == {}
    append_user("Here is a new decision to remember")
    assert _run(CAPTURE_HOOK, payload, cwd=vault, env=env)["decision"] == "block"


def test_capture_without_transcript_does_not_rearm_when_time_passes(monkeypatch):
    from hookslib.stop_hook import capture_debounce

    payload = {"session_id": f"no-transcript-{uuid.uuid4()}"}
    monkeypatch.setattr("hookslib.stop_hook.time.time", lambda: 1000)
    assert capture_debounce(payload) is False
    monkeypatch.setattr("hookslib.stop_hook.time.time", lambda: 5000)
    assert capture_debounce(payload) is True


def test_capture_without_session_identity_is_silent():
    from hookslib.stop_hook import capture_debounce

    assert capture_debounce({}) is True
