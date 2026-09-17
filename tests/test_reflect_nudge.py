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


def run_raw_hook(stdin_payload: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(HOOK)],
        input=stdin_payload,
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def make_payload(session_id: str = "test-session") -> dict:
    return {
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }


def set_count(cache_root: Path, count: int, session_id: str = "test-session") -> None:
    state = cache_root / session_id
    state.mkdir(parents=True, exist_ok=True)
    (state / "bash-count").write_text(str(count))


class TestReflectNudge:
    def test_invalid_payload_is_silent(self, tmp_path):
        result = run_raw_hook("{", {"OBSIDIAN_KNOWLEDGE_CACHE_ROOT": str(tmp_path)})
        assert result.returncode == 0
        assert result.stdout == ""

    def test_default_cache_root_uses_home(self, tmp_path):
        env = {**os.environ, "HOME": str(tmp_path)}
        env.pop("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", None)
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(make_payload("home-session")),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0
        assert (tmp_path / ".cache/obsidian-knowledge/home-session/bash-count").read_text() == "1"

    def test_does_not_fire_before_threshold(self, tmp_path):
        """99th call produces no systemMessage."""
        set_count(tmp_path, 98)
        code, out = run_hook(make_payload(), tmp_path)
        assert code == 0
        assert "systemMessage" not in out

    def test_fires_at_hundredth_call(self, tmp_path):
        """100th call produces a reflection nudge."""
        set_count(tmp_path, 99)
        code, out = run_hook(make_payload(), tmp_path)
        assert code == 0
        assert "systemMessage" in out
        assert "remember-conversations" not in out["systemMessage"]
        assert "obsidian-knowledge papercut" in out["systemMessage"]
        assert "/improve-harness" not in out["systemMessage"]

    def test_fires_continuously_at_multiples(self, tmp_path):
        """Fires at 100, 200, 300 — no per-session suppression."""
        fire_counts = []
        for i in (100, 101, 200, 201, 300):
            set_count(tmp_path, i - 1)
            code, out = run_hook(make_payload(), tmp_path)
            if "systemMessage" in out:
                fire_counts.append(i)
        assert fire_counts == [100, 200, 300]

    def test_isolates_per_session(self, tmp_path):
        """Different session_ids have independent counters."""
        set_count(tmp_path, 99, "session-A")
        # Session B at call 1 should NOT fire
        code, out = run_hook(make_payload("session-B"), tmp_path)
        assert "systemMessage" not in out
        # Session A at call 100 SHOULD fire
        code, out = run_hook(make_payload("session-A"), tmp_path)
        assert "systemMessage" in out
