"""Integration tests for reflect-nudge PostToolUse hook."""
import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK = PLUGIN_ROOT / "hooks" / "reflect-nudge.py"


def run_hook(stdin_payload: dict, cache_root: Path) -> tuple[int, dict]:
    env = os.environ.copy()
    env["OBSIDIAN_KNOWLEDGE_CACHE_ROOT"] = str(cache_root)
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        env=env,
    )
    try:
        out = json.loads(result.stdout) if result.stdout else {}
    except json.JSONDecodeError:
        out = {"_raw_stdout": result.stdout}
    return result.returncode, out


def make_payload(session_id: str = "test-session") -> dict:
    return {
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }


class TestReflectNudge:
    def test_does_not_fire_before_threshold(self, tmp_path):
        """First 9 calls produce no systemMessage."""
        for i in range(9):
            code, out = run_hook(make_payload(), tmp_path)
            assert code == 0
            assert "systemMessage" not in out, f"fired prematurely at call {i+1}"

    def test_fires_at_tenth_call(self, tmp_path):
        """10th call produces a reflection nudge."""
        for _ in range(9):
            run_hook(make_payload(), tmp_path)
        code, out = run_hook(make_payload(), tmp_path)
        assert code == 0
        assert "systemMessage" in out
        assert "remember-conversations" in out["systemMessage"]
        assert "/improve-harness" not in out["systemMessage"]

    def test_fires_continuously_at_multiples(self, tmp_path):
        """Fires at 10, 20, 30 — no per-session suppression."""
        fire_counts = []
        for i in range(1, 31):
            code, out = run_hook(make_payload(), tmp_path)
            if "systemMessage" in out:
                fire_counts.append(i)
        assert fire_counts == [10, 20, 30]

    def test_isolates_per_session(self, tmp_path):
        """Different session_ids have independent counters."""
        for _ in range(9):
            run_hook(make_payload("session-A"), tmp_path)
        # Session B at call 1 should NOT fire
        code, out = run_hook(make_payload("session-B"), tmp_path)
        assert "systemMessage" not in out
        # Session A at call 10 SHOULD fire
        code, out = run_hook(make_payload("session-A"), tmp_path)
        assert "systemMessage" in out
