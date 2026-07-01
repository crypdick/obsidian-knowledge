"""Unit tests for the SessionStart debounce (hookslib.stop_hook.session_debounce).

The debounce re-runs only when BOTH gates open: >= cooldown_seconds elapsed
AND the user sent a new message since the last run. Either gate alone
suppresses an auto-compaction storm (many SessionStart events, no new message).
"""
import json
import os
import uuid

from hookslib.stop_hook import session_debounce

RUN_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _sid(tag: str) -> str:
    return f"s-{RUN_ID}-{tag}"


def _transcript(tmp_path, n_user_msgs: int) -> str:
    f = tmp_path / f"t-{uuid.uuid4().hex[:6]}.jsonl"
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": f"msg {i}"}})
        for i in range(n_user_msgs)
    ]
    f.write_text("\n".join(lines) + ("\n" if lines else ""))
    return str(f)


def test_no_session_id_never_debounces():
    assert session_debounce({}, "unit-nosid") is False


def test_first_fire_runs_then_time_gate_blocks(tmp_path):
    payload = {"session_id": _sid("timegate"), "transcript_path": _transcript(tmp_path, 1)}
    # First fire arms + runs.
    assert session_debounce(payload, "unit-timegate", cooldown_seconds=300) is False
    # Immediate re-fire is inside the cooldown window → skip.
    assert session_debounce(payload, "unit-timegate", cooldown_seconds=300) is True


def test_activity_gate_blocks_when_no_new_message(tmp_path):
    # cooldown_seconds=0 removes the time gate, isolating the activity gate.
    tp = _transcript(tmp_path, 2)
    payload = {"session_id": _sid("activity"), "transcript_path": tp}
    assert session_debounce(payload, "unit-activity", cooldown_seconds=0) is False
    # Same transcript (no new user message) → skip despite cooldown elapsed.
    assert session_debounce(payload, "unit-activity", cooldown_seconds=0) is True


def test_reinjects_when_time_elapsed_and_new_message(tmp_path):
    sid = _sid("both")
    p1 = {"session_id": sid, "transcript_path": _transcript(tmp_path, 1)}
    assert session_debounce(p1, "unit-both", cooldown_seconds=0) is False
    # A new user message arrived AND time gate is open (0s) → run again.
    p2 = {"session_id": sid, "transcript_path": _transcript(tmp_path, 2)}
    assert session_debounce(p2, "unit-both", cooldown_seconds=0) is False


def test_no_transcript_falls_back_to_time_only(tmp_path):
    sid = _sid("notranscript")
    payload = {"session_id": sid}  # no transcript_path → count is None
    # cooldown elapsed and no message data → time-only gate re-runs.
    assert session_debounce(payload, "unit-notranscript", cooldown_seconds=0) is False
    assert session_debounce(payload, "unit-notranscript", cooldown_seconds=0) is False
    # But within the cooldown window it still skips.
    assert session_debounce(payload, "unit-notranscript", cooldown_seconds=300) is True
