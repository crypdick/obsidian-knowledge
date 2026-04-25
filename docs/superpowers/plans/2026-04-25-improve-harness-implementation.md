# Improve-Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a SessionStart harness primer hook, a continuous reflect-nudge hook, a one-time `/setup-harness` migration command, and an `improve-harness` skill (with deploy-harness companion) that orchestrates a multi-phase headless side-quest workflow for self-improving the harness.

**Architecture:** Two layers. (1) **Substrate**: SessionStart hook injects a 5-directive primer (memory, recall, capture, friction reflection, user-frustration reflection) into every session; PostToolUse hook fires every 10 bash calls to nudge reflection; `/setup-harness` rsync-migrates `~/.claude/projects/` into the vault and replaces with a symlink. (2) **Meta-improvement loop**: `improve-harness` skill organized for progressive disclosure (thin SKILL.md + sub-asset files for phases / templates / conventions) drives a 6-phase workflow via `claude -p --worktree` headless side quests, with two-layer review (inner subagent ping-pong + outer main-agent executive review) and human approval gates before merge/deploy.

**Tech Stack:** Python 3 (existing hook pattern with `hooks/lib/` shared modules), bash, claude-code plugin manifest, git worktrees, caveman skill (full intensity) for skill-body authoring.

---

## Reference

Spec: `docs/superpowers/specs/2026-04-25-improve-harness-design.md`
Existing hook style: `hooks/protect-vault.py` + `hooks/lib/`
Plugin manifest: `.claude-plugin/plugin.json`

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `hooks/recall-init.py` | NEW | SessionStart: verify symlink, inject harness primer |
| `hooks/reflect-nudge.py` | NEW | PostToolUse on Bash: fire every 10 calls |
| `hooks/lib/recall_init_lib.py` | NEW | Shared symlink-check + primer-build logic |
| `hooks/lib/reflect_counter.py` | NEW | Shared per-session bash-call counter |
| `commands/improve-harness.md` | NEW | Slash command shim |
| `commands/setup-harness.md` | NEW | One-time migration command |
| `skills/improve-harness/SKILL.md` | NEW | Thin index (~80 lines caveman-full) |
| `skills/improve-harness/phases.md` | NEW | Per-phase mechanics |
| `skills/improve-harness/templates.md` | NEW | Incident report / proposal / synopsis structures |
| `skills/improve-harness/conventions.md` | NEW | Caveman, exceptions, token-burn, sub-asset discipline |
| `skills/deploy-harness/SKILL.md` | NEW | Single-file deploy routine |
| `tests/test_recall_init.py` | NEW | Unit tests for recall-init.py |
| `tests/test_reflect_nudge.py` | NEW | Unit tests for reflect-nudge.py |
| `.gitignore` | UPDATE | Add `.improve-harness/` |
| `.claude-plugin/plugin.json` | UPDATE | Register new hooks |
| `README.md` | UPDATE | Document setup, primer, triggers, phases |

---

## Task 1: Create test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create empty tests package**

```bash
mkdir -p /home/ricardo/src/PERSONAL/obsidian-knowledge/tests
touch /home/ricardo/src/PERSONAL/obsidian-knowledge/tests/__init__.py
```

- [ ] **Step 2: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
"""Shared test fixtures for obsidian-knowledge plugin hooks."""
import json
import os
import sys
from pathlib import Path

import pytest

# Make hooks importable
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a fake vault root with required structure."""
    vault = tmp_path / "vault"
    (vault / "wiki" / "systems" / "repos").mkdir(parents=True)
    return vault


@pytest.fixture
def tmp_claude_projects(tmp_path):
    """Create a fake ~/.claude/projects dir."""
    projects = tmp_path / "claude" / "projects"
    projects.mkdir(parents=True)
    return projects


@pytest.fixture
def tmp_vaults_yaml(tmp_path, monkeypatch, tmp_vault):
    """Create vaults.yaml pointing to tmp_vault and patch CONFIG_PATH."""
    config_dir = tmp_path / "config" / "obsidian-knowledge"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "vaults.yaml"
    config_file.write_text(f"vaults:\n  - {tmp_vault}\n")
    monkeypatch.setattr(
        "lib.vault_config.CONFIG_PATH", config_file
    )
    return config_file
```

- [ ] **Step 3: Verify pytest discovers tests**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/ -v`
Expected: `no tests ran` (no test files yet) — confirms pytest works.

- [ ] **Step 4: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "chore(tests): scaffold pytest infrastructure for hooks"
```

---

## Task 2: Add `.improve-harness/` to .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Read current .gitignore**

```bash
cat /home/ricardo/src/PERSONAL/obsidian-knowledge/.gitignore
```

Expected current content: contains `__pycache__/` or similar; possibly empty/short.

- [ ] **Step 2: Append new entry**

Append to `.gitignore` (use Edit tool):

```
.improve-harness/
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore .improve-harness/ state directories"
```

---

## Task 3: Build symlink-verification library

**Files:**
- Create: `hooks/lib/recall_init_lib.py`
- Create: `tests/test_recall_init_lib.py`

- [ ] **Step 1: Write failing test for symlink verification**

Create `tests/test_recall_init_lib.py`:

```python
"""Tests for recall_init_lib (symlink verification + primer build)."""
import os
from pathlib import Path

import pytest

from lib import recall_init_lib  # noqa: E402


class TestVerifySymlink:
    def test_returns_ok_when_symlinked_correctly(self, tmp_vault, tmp_claude_projects, tmp_path):
        """Symlink exists and points to vault repos dir."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        symlink = tmp_path / "claude_projects_link"
        symlink.symlink_to(target)
        result = recall_init_lib.verify_symlink(symlink, target)
        assert result.ok is True
        assert result.error is None

    def test_returns_error_when_path_missing(self, tmp_vault, tmp_path):
        """Path doesn't exist at all."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        symlink = tmp_path / "missing"
        result = recall_init_lib.verify_symlink(symlink, target)
        assert result.ok is False
        assert "not configured" in result.error.lower()

    def test_returns_error_when_real_dir_not_symlink(self, tmp_vault, tmp_path):
        """Path exists but is a real directory, not a symlink."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        real_dir = tmp_path / "real_projects"
        real_dir.mkdir()
        result = recall_init_lib.verify_symlink(real_dir, target)
        assert result.ok is False
        assert "not configured" in result.error.lower()

    def test_returns_error_when_symlinked_to_wrong_target(self, tmp_path):
        """Symlink exists but points elsewhere."""
        wrong = tmp_path / "wrong"
        wrong.mkdir()
        symlink = tmp_path / "claude_projects_link"
        symlink.symlink_to(wrong)
        expected = tmp_path / "expected"
        expected.mkdir()
        result = recall_init_lib.verify_symlink(symlink, expected)
        assert result.ok is False
        assert "not configured" in result.error.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_recall_init_lib.py -v`
Expected: FAIL with "No module named 'lib.recall_init_lib'" (or ImportError)

- [ ] **Step 3: Implement recall_init_lib**

Create `hooks/lib/recall_init_lib.py`:

```python
"""Helpers for the SessionStart recall-init hook.

Verifies that ~/.claude/projects/ is symlinked to the vault repos dir,
and builds the harness primer that gets injected into every session.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    ok: bool
    error: str | None = None


def verify_symlink(claude_projects: Path, expected_target: Path) -> VerifyResult:
    """Check that claude_projects is a symlink pointing to expected_target."""
    if not claude_projects.is_symlink():
        return VerifyResult(
            ok=False,
            error="Memory symlink not configured. Run /setup-harness to migrate.",
        )
    actual = claude_projects.resolve()
    if actual != expected_target.resolve():
        return VerifyResult(
            ok=False,
            error=(
                f"Memory symlink not configured correctly: points to {actual}, "
                f"expected {expected_target}. Run /setup-harness to fix."
            ),
        )
    return VerifyResult(ok=True)


def build_primer(vault_root: Path, plugin_root: Path) -> str:
    """Build the harness primer text injected into every session.

    Loaded into every session's context. Must stand alone — agents that
    read only this primer should know what to do.
    """
    wiki = vault_root / "wiki"
    return (
        "You are operating under the obsidian-knowledge harness.\n"
        f"- Memory: per-project memory lives at {vault_root}/wiki/systems/repos/. "
        f"~/.claude/projects/ is symlinked there.\n"
        f"- Recall: before answering non-trivial questions, search the wiki: "
        f"`rg <pattern> {wiki}/`.\n"
        "- Capture: at session end, file conversation outcomes (use the "
        "`remember-conversations` skill) and update the changelog.\n"
        "- Reflect on friction: if you struggle with the harness, hit unexpected "
        "blocks, or repeat the same workaround, invoke `/improve-harness`.\n"
        "- Reflect on user frustration: if the user expresses frustration "
        "('fuck', 'wtf', 'this keeps happening'), invoke `/improve-harness`. "
        "The agent is not the unit of analysis — the system is."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_recall_init_lib.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Add primer-build test**

Append to `tests/test_recall_init_lib.py`:

```python
class TestBuildPrimer:
    def test_includes_all_five_directives(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert "harness" in primer.lower()
        assert "memory" in primer.lower()
        assert "rg" in primer
        assert "remember-conversations" in primer
        assert "/improve-harness" in primer
        assert "frustration" in primer.lower()

    def test_primer_includes_vault_path(self, tmp_vault, tmp_path):
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        primer = recall_init_lib.build_primer(tmp_vault, plugin_root)
        assert str(tmp_vault) in primer
```

- [ ] **Step 6: Run all tests**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_recall_init_lib.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add hooks/lib/recall_init_lib.py tests/test_recall_init_lib.py
git commit -m "feat(hooks): add recall_init_lib (symlink check + primer build)"
```

---

## Task 4: Build recall-init.py SessionStart hook

**Files:**
- Create: `hooks/recall-init.py`
- Create: `tests/test_recall_init.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_recall_init.py`:

```python
"""Integration tests for recall-init SessionStart hook."""
import json
import os
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK = PLUGIN_ROOT / "hooks" / "recall-init.py"


def run_hook(stdin_payload: dict, env_overrides: dict | None = None) -> tuple[int, dict]:
    """Run the hook subprocess; return (exit_code, parsed_stdout_json)."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
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


class TestRecallInit:
    def test_emits_primer_when_symlink_ok(self, tmp_vault, tmp_path, monkeypatch):
        """Symlink exists; hook injects systemMessage with primer."""
        target = tmp_vault / "wiki" / "systems" / "repos"
        symlink = tmp_path / "projects"
        symlink.symlink_to(target)

        config_dir = tmp_path / "obsidian-knowledge"
        config_dir.mkdir()
        (config_dir / "vaults.yaml").write_text(f"vaults:\n  - {tmp_vault}\n")

        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(config_dir / "vaults.yaml"),
            "OBSIDIAN_KNOWLEDGE_CLAUDE_PROJECTS": str(symlink),
        }
        code, out = run_hook({"session_id": "abc"}, env)

        assert code == 0
        assert "systemMessage" in out
        assert "harness" in out["systemMessage"].lower()
        assert "/improve-harness" in out["systemMessage"]

    def test_warns_when_symlink_missing(self, tmp_vault, tmp_path, monkeypatch):
        """Symlink missing; hook emits warning systemMessage but does not block."""
        config_dir = tmp_path / "obsidian-knowledge"
        config_dir.mkdir()
        (config_dir / "vaults.yaml").write_text(f"vaults:\n  - {tmp_vault}\n")

        bogus = tmp_path / "nonexistent"
        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(config_dir / "vaults.yaml"),
            "OBSIDIAN_KNOWLEDGE_CLAUDE_PROJECTS": str(bogus),
        }
        code, out = run_hook({"session_id": "abc"}, env)

        assert code == 0  # non-blocking
        assert "systemMessage" in out
        msg = out["systemMessage"].lower()
        assert "not configured" in msg or "/setup-harness" in msg

    def test_errors_on_multi_vault_config(self, tmp_path):
        """vaults.yaml lists 2+ vaults; hook errors with clear message."""
        config_dir = tmp_path / "obsidian-knowledge"
        config_dir.mkdir()
        (config_dir / "vaults.yaml").write_text(
            f"vaults:\n  - {tmp_path}/vault1\n  - {tmp_path}/vault2\n"
        )
        env = {
            "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(config_dir / "vaults.yaml"),
        }
        code, out = run_hook({"session_id": "abc"}, env)
        assert code == 0  # non-blocking warning, not hard error
        assert "multi-vault" in out.get("systemMessage", "").lower() or \
               "not supported" in out.get("systemMessage", "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_recall_init.py -v`
Expected: All 3 tests FAIL with hook script not found / not executable.

- [ ] **Step 3: Implement recall-init.py**

Create `hooks/recall-init.py`:

```python
#!/usr/bin/env python3
"""SessionStart hook: verify memory symlink + inject harness primer.

Runs at every session start. Two responsibilities:

1. Verify ~/.claude/projects/ is symlinked to <vault>/wiki/systems/repos/.
   On failure, emit a non-blocking warning directing the user to
   /setup-harness. (We never block sessions — broken symlink just means
   no vault-backed memory until the user runs the migration.)

2. Inject the harness primer (5 directives: memory location, recall via rg,
   capture via remember-conversations, friction reflection, user-frustration
   reflection) as the SessionStart systemMessage. The primer is the
   load-bearing context for the entire harness — must stand alone.

Multi-vault config not supported in v1.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import recall_init_lib  # noqa: E402
from lib import vault_config  # noqa: E402


def resolve_claude_projects() -> Path:
    """Path to ~/.claude/projects/, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CLAUDE_PROJECTS")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "projects"


def resolve_vaults_config() -> Path:
    """Path to vaults.yaml, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG")
    if override:
        return Path(override)
    return vault_config.CONFIG_PATH


def main() -> int:
    # Read stdin payload (we don't use it but Claude Code may send one)
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    # Resolve vault config
    config_path = resolve_vaults_config()
    if not config_path.exists():
        # No vault configured at all — emit nothing; hook is a no-op
        return 0

    # Read vault roots directly (may need to override CONFIG_PATH via env)
    if config_path != vault_config.CONFIG_PATH:
        vault_config.CONFIG_PATH = config_path
    vault_roots = vault_config.load_vault_roots()

    if len(vault_roots) > 1:
        emit_message(
            "Multi-vault vaults.yaml not supported by obsidian-knowledge "
            "harness. Configure exactly one vault root."
        )
        return 0

    if not vault_roots:
        return 0

    vault_root = Path(vault_roots[0])
    expected_target = vault_root / "wiki" / "systems" / "repos"
    claude_projects = resolve_claude_projects()

    verify = recall_init_lib.verify_symlink(claude_projects, expected_target)
    plugin_root = Path(__file__).resolve().parent.parent
    primer = recall_init_lib.build_primer(vault_root, plugin_root)

    if verify.ok:
        emit_message(primer)
    else:
        # Non-blocking warning + still inject primer so agent has guidance
        emit_message(f"WARNING: {verify.error}\n\n{primer}")

    return 0


def emit_message(message: str) -> None:
    """Emit a SessionStart systemMessage."""
    json.dump({"systemMessage": message}, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make hook executable**

```bash
chmod +x /home/ricardo/src/PERSONAL/obsidian-knowledge/hooks/recall-init.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_recall_init.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hooks/recall-init.py tests/test_recall_init.py
git commit -m "feat(hooks): add recall-init SessionStart hook"
```

---

## Task 5: Build reflect-counter library

**Files:**
- Create: `hooks/lib/reflect_counter.py`
- Create: `tests/test_reflect_counter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reflect_counter.py`:

```python
"""Tests for the per-session bash-call counter."""
from pathlib import Path

import pytest

from lib import reflect_counter


class TestCounter:
    def test_increment_creates_state_file(self, tmp_path):
        path = tmp_path / "session-abc"
        n = reflect_counter.increment(path)
        assert n == 1
        assert (path / "bash-count").exists()

    def test_increment_persists_across_calls(self, tmp_path):
        path = tmp_path / "session-abc"
        reflect_counter.increment(path)
        reflect_counter.increment(path)
        n = reflect_counter.increment(path)
        assert n == 3

    def test_should_fire_at_threshold_multiples(self):
        assert reflect_counter.should_fire(10) is True
        assert reflect_counter.should_fire(20) is True
        assert reflect_counter.should_fire(30) is True

    def test_should_not_fire_off_threshold(self):
        assert reflect_counter.should_fire(0) is False
        assert reflect_counter.should_fire(5) is False
        assert reflect_counter.should_fire(11) is False
        assert reflect_counter.should_fire(19) is False

    def test_custom_threshold(self):
        assert reflect_counter.should_fire(5, threshold=5) is True
        assert reflect_counter.should_fire(10, threshold=5) is True
        assert reflect_counter.should_fire(7, threshold=5) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_reflect_counter.py -v`
Expected: All 5 tests FAIL with ImportError.

- [ ] **Step 3: Implement reflect_counter**

Create `hooks/lib/reflect_counter.py`:

```python
"""Per-session bash-call counter for the reflect-nudge hook.

State lives at ~/.cache/obsidian-knowledge/<session-id>/bash-count
(integer in plain text). Counter is incremented on each PostToolUse
matching Bash; the hook fires its reminder every Nth invocation
(default N=10), continuously — no per-session suppression.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_THRESHOLD = 10


def increment(session_state_dir: Path) -> int:
    """Increment counter for this session; return the new value."""
    session_state_dir.mkdir(parents=True, exist_ok=True)
    counter_file = session_state_dir / "bash-count"
    if counter_file.exists():
        try:
            current = int(counter_file.read_text().strip())
        except (ValueError, OSError):
            current = 0
    else:
        current = 0
    new_value = current + 1
    counter_file.write_text(str(new_value))
    return new_value


def should_fire(count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """Return True if count is a positive multiple of threshold."""
    if count <= 0:
        return False
    return count % threshold == 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_reflect_counter.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hooks/lib/reflect_counter.py tests/test_reflect_counter.py
git commit -m "feat(hooks): add reflect_counter for bash-call tracking"
```

---

## Task 6: Build reflect-nudge.py PostToolUse hook

**Files:**
- Create: `hooks/reflect-nudge.py`
- Create: `tests/test_reflect_nudge.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_reflect_nudge.py`:

```python
"""Integration tests for reflect-nudge PostToolUse hook."""
import json
import os
import subprocess
from pathlib import Path

import pytest

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
        assert "friction" in out["systemMessage"].lower() or \
               "/improve-harness" in out["systemMessage"]

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_reflect_nudge.py -v`
Expected: All 4 tests FAIL (script not found / not executable).

- [ ] **Step 3: Implement reflect-nudge.py**

Create `hooks/reflect-nudge.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook (matcher: Bash): continuous reflection nudge.

Fires every 10 bash invocations within a session. State lives at
~/.cache/obsidian-knowledge/<session-id>/bash-count. Continuous — no
per-session suppression. The continuous cadence is intentional: it
builds reflection into the agent's working rhythm, not a one-time
interruption.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import reflect_counter  # noqa: E402

REMINDER = (
    "Step back: any friction worth feeding back into the harness? "
    "If yes, invoke `/improve-harness` or describe the friction."
)


def resolve_cache_root() -> Path:
    """~/.cache/obsidian-knowledge/, overridable via env for tests."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CACHE_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "obsidian-knowledge"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    session_id = payload.get("session_id", "unknown")
    session_state_dir = resolve_cache_root() / session_id

    count = reflect_counter.increment(session_state_dir)

    if reflect_counter.should_fire(count):
        json.dump({"systemMessage": REMINDER}, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make hook executable**

```bash
chmod +x /home/ricardo/src/PERSONAL/obsidian-knowledge/hooks/reflect-nudge.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/test_reflect_nudge.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hooks/reflect-nudge.py tests/test_reflect_nudge.py
git commit -m "feat(hooks): add reflect-nudge PostToolUse hook"
```

---

## Task 7: Register new hooks in plugin.json

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Read current plugin.json**

Read `/home/ricardo/src/PERSONAL/obsidian-knowledge/.claude-plugin/plugin.json` for context.

- [ ] **Step 2: Add SessionStart and PostToolUse hook registrations**

Use Edit tool. Add new entries to the `hooks` object in plugin.json. After the existing `Stop` block, add:

```json
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/recall-init.py"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/reflect-nudge.py"
          }
        ]
      }
    ]
```

Also bump version to `2.1.0` (minor bump for new feature).

- [ ] **Step 3: Validate JSON**

Run: `python3 -c "import json; json.load(open('/home/ricardo/src/PERSONAL/obsidian-knowledge/.claude-plugin/plugin.json'))"`
Expected: no output (valid JSON).

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat(plugin): register recall-init + reflect-nudge hooks"
```

---

## Task 8: Create /setup-harness command

**Files:**
- Create: `commands/setup-harness.md`

- [ ] **Step 1: Read command-development guidance**

If you need a refresher on slash command structure, read `${CLAUDE_PLUGIN_ROOT}/skills/command-development/SKILL.md` (from plugin-dev plugin if available).

- [ ] **Step 2: Create the command file**

Create `commands/setup-harness.md`:

```markdown
---
description: Migrate Claude Code's per-project memory into the Obsidian vault and replace with a symlink. One-time setup.
---

# Setup Harness

Run the one-time migration that puts Claude Code's per-project memory directly inside the Obsidian vault via a top-level symlink.

## What this does

1. Reads vault root from `~/.config/obsidian-knowledge/vaults.yaml`. Errors if multi-vault.
2. Rsyncs existing `~/.claude/projects/*` → `<vault>/wiki/systems/repos/`.
3. Surfaces collisions (same encoded-cwd dir exists in source and target with divergent content) for manual merge.
4. Replaces `~/.claude/projects/` with a symlink to `<vault>/wiki/systems/repos/`.

## Steps to execute

1. Read `~/.config/obsidian-knowledge/vaults.yaml`. Use `python3 -c "import yaml; print([v for v in yaml.safe_load(open('/home/$USER/.config/obsidian-knowledge/vaults.yaml'))['vaults']])"`. If the file lists more than one vault, stop and tell the user: "Multi-vault config not supported. Configure exactly one vault." Exit.

2. Set `VAULT_ROOT` to the single vault path. Set `TARGET=<VAULT_ROOT>/wiki/systems/repos`.

3. Check current state of `~/.claude/projects/`:
   - If it's already a symlink to `$TARGET`: report "Already configured." Exit.
   - If it's a real directory: proceed to step 4.
   - If it doesn't exist: create `$TARGET` and create the symlink directly (skip rsync). Exit with "Created empty symlink."

4. Ensure target exists: `mkdir -p "$TARGET"`.

5. Rsync with `--ignore-existing` first to find clean copies:
   ```bash
   rsync -av --ignore-existing ~/.claude/projects/ "$TARGET"/
   ```

6. Identify collisions — files that exist in both source and target with different content:
   ```bash
   rsync -avn --existing --checksum ~/.claude/projects/ "$TARGET"/ | grep -v '^$\|sending\|sent\|total'
   ```
   This dry-run lists files that WOULD be transferred (i.e., differ).

7. If collisions exist:
   - List each collision pair to the user.
   - For each, read both versions, present a merged version, ask user to confirm or refine.
   - Write merged version to the target. Leave source as-is for now.
   - Repeat until all collisions resolved.

8. After all conflicts resolved, run a final rsync to mirror everything:
   ```bash
   rsync -av ~/.claude/projects/ "$TARGET"/
   ```

9. Verify all source content has been mirrored to target. Diff to confirm.

10. Replace projects dir with symlink:
    ```bash
    rm -rf ~/.claude/projects
    ln -s "$TARGET" ~/.claude/projects
    ```

11. Verify the symlink resolves correctly:
    ```bash
    readlink -f ~/.claude/projects
    ```
    Should print `$TARGET`.

12. Report success: "Setup complete. Restart Claude Code or open a new session for the harness primer to load."
```

- [ ] **Step 3: Commit**

```bash
git add commands/setup-harness.md
git commit -m "feat(commands): add /setup-harness migration command"
```

---

## Task 9: Create /improve-harness slash command

**Files:**
- Create: `commands/improve-harness.md`

- [ ] **Step 1: Create the command file**

Create `commands/improve-harness.md`:

```markdown
---
description: Trigger a meta-improvement side quest to fix harness friction. Provide a free-text description of what's wrong.
---

# Improve Harness

Trigger the meta-improvement workflow when the harness is causing friction.

Read the skill at `${CLAUDE_PLUGIN_ROOT}/skills/improve-harness/SKILL.md` and execute its workflow with the user's friction description as input.

User-provided friction description: $ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git add commands/improve-harness.md
git commit -m "feat(commands): add /improve-harness slash command"
```

---

## Task 10: Author improve-harness/conventions.md (foundational sub-asset)

**Files:**
- Create: `skills/improve-harness/conventions.md`

- [ ] **Step 1: Create the conventions sub-asset**

Create `skills/improve-harness/conventions.md`. Author in caveman-full style (drop articles, fragments OK, short synonyms — but keep security-sensitive content in normal prose):

```markdown
# Conventions

Rules for any agent authoring or editing the harness.

## Caveman authoring

When write or edit any plugin skill body: use `caveman` skill at **full** intensity. Cut anything not load-bearing. Sentence absent → wrong outcome? No → delete.

## Caveman exceptions (use normal prose)

Drop caveman style for:
- Security warnings (hook guards involving destructive operations).
- Irreversible action confirmations.
- Multi-step sequences where fragment order risks misread.

When in doubt, lean normal prose. Auto-clarity beats brevity.

## Token-burn warning

This skill loaded into every Claude Code session that touches obsidian-knowledge plugin. Multiplicative token burn applies. Add sentence → ask "absence cause wrong outcome?" If no → delete.

## Sub-asset discipline

`SKILL.md` stays thin index. New content → goes in right sub-asset file:
- Phase mechanics → `phases.md`
- Templates (incident, proposal, synopsis) → `templates.md`
- Conventions (caveman, token-burn, this) → `conventions.md`

If `SKILL.md` grows past ~100 lines: refactor into new sub-asset.

## Security-sensitive content

When editing hooks that involve safety guards (e.g., `protect-vault.py`, destructive command guards, published-file blocks):

- Use normal prose, full sentences, explicit warnings
- Test thoroughly before merging — these protect user data
- Default to refusing the change if scope is unclear
- Escalate to user if proposed change weakens an existing guard
```

- [ ] **Step 2: Verify file structure (frontmatter not required for sub-assets)**

Run: `cat /home/ricardo/src/PERSONAL/obsidian-knowledge/skills/improve-harness/conventions.md | head -3`
Expected: starts with `# Conventions`.

- [ ] **Step 3: Commit**

```bash
git add skills/improve-harness/conventions.md
git commit -m "feat(skills): add improve-harness conventions sub-asset"
```

---

## Task 11: Author improve-harness/templates.md (template sub-asset)

**Files:**
- Create: `skills/improve-harness/templates.md`

- [ ] **Step 1: Create the templates sub-asset**

Create `skills/improve-harness/templates.md`:

```markdown
# Templates

Document structures for the three artifacts produced by the workflow.

## Incident report (Phase 0 output)

Path: `<target-repo>/.improve-harness/<slug>/incident-report.md`

Required sections:
- **Friction summary** — what happened, in user's words if available
- **Transcript path** — path to the JSONL transcript at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (find latest by mtime)
- **Classification** — GLOBAL or REPO-SCOPED; TRIVIAL or NON-TRIVIAL
- **Postmortem framing** — explicit instruction: "blameless postmortem; agent is not the unit of analysis, the system is"

Recommended sections:
- **Recent context** — what was the agent doing when friction hit
- **Attempted workarounds** — what didn't work
- **Suspected root cause** — main agent's guess (subagent will verify or refute)

No length cap. Main agent decides how much context the side quest needs.

## Proposal (Phase 1 output)

Path: `<target-repo>/.improve-harness/<slug>/proposal.md`

Required sections:
- **Diagnosis** — what about the system caused the friction (blameless)
- **Proposed change** — what to modify, where (specific files)
- **Why this fixes it** — causal chain from change to outcome
- **Expected outcome** — observable behavior change
- **Scope** — files touched, classification confirmed (TRIVIAL/NON-TRIVIAL)
- **Feasibility notes** — anything tricky about implementing

Reviewer subagent checks: completeness, blameless framing, scope appropriateness, expected-outcome clarity, feasibility.

## Synopsis (Phase 3 output)

Path: `<target-repo>/.improve-harness/<slug>/synopsis.md`

Required sections:
- **What changed** — one paragraph summary
- **Files touched** — explicit list
- **Branch name** — `improve/<slug>`
- **Plugin reload required** — yes (always for v1)
- **Follow-ups** — anything the change surfaced that's not in scope
```

- [ ] **Step 2: Commit**

```bash
git add skills/improve-harness/templates.md
git commit -m "feat(skills): add improve-harness templates sub-asset"
```

---

## Task 12: Author improve-harness/phases.md (mechanics sub-asset)

**Files:**
- Create: `skills/improve-harness/phases.md`

- [ ] **Step 1: Create the phases sub-asset**

Create `skills/improve-harness/phases.md`:

```markdown
# Phases

Detailed mechanics for each of the 6 phases. SKILL.md gives high-level overview; this file is the playbook.

## Phase 0 — Incident report

Main agent writes `<target-repo>/.improve-harness/<slug>/incident-report.md` per template in `templates.md`.

Determines:
- **Slug**: kebab-case from friction description, ≤6 words, append `-YYYY-MM-DD`
- **Target repo**: plugin repo for GLOBAL, working repo for REPO-SCOPED
- **JSONL transcript path**: `~/.claude/projects/<encoded-cwd>/*.jsonl` — latest by mtime

Creates `.improve-harness/<slug>/` state directory. Writes `status` file with content `0`.

## Phase 1 — Proposal subagent (with internal review)

Main agent invokes:

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --add-dir ~/.claude/projects \
  "PHASE 1 of improve-harness workflow.
   Read <plugin-root>/skills/improve-harness/SKILL.md and follow pointers.
   Slug: <slug>.
   Inputs: .improve-harness/<slug>/incident-report.md
   Save your session_id to .improve-harness/<slug>/session_id when done."
```

Side quest internal flow:
1. Read incident report + JSONL transcript via `--add-dir` access
2. Dispatch **author subagent**: conduct blameless postmortem, draft proposal per template
3. Dispatch **proposal-quality reviewer subagent**: critique on completeness, blameless framing, scope, feasibility
4. If reviewer rejects: author revises, reviewer re-reviews. Max 3 iterations. Log to `proposal-review-history.md`.
5. After approval: write `proposal.md`, save own session_id to `.improve-harness/<slug>/session_id`
6. Update `status` to `1`

Side quest does NOT contact main agent during inner loop.

## Phase 2 — Main agent executive review (proposal)

Main agent reads `proposal.md`. **Executive-level critique only**: scope, intent, blameless framing, completeness. NOT line-by-line.

If satisfied: surface proposal to user with summary + "approve to proceed to implementation?"

If not satisfied: append concerns to `exec-review-history.md`, then resume side quest:

```bash
claude -r $(cat .improve-harness/<slug>/session_id) -p \
  --max-budget-usd 30 --output-format json \
  "PHASE 2 follow-up: address these executive-level concerns: <text>"
```

Iteration cap: 3 cycles. After 3 unresolved cycles, escalate to user with explicit "I have outstanding concerns: <list>" — do not silently accept.

Update `status` to `2` after user approval.

## Phase 3 — Implementation subagent (with internal review)

On user approval, main agent invokes:

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --worktree improve/<slug> \
  --permission-mode acceptEdits \
  "PHASE 3 of improve-harness workflow.
   Read <plugin-root>/skills/improve-harness/SKILL.md and follow pointers.
   Resume from session_id: <id>. Slug: <slug>.
   Implement the approved proposal on this worktree branch."
```

Side quest internal flow:
- For NON-TRIVIAL: invoke `superpowers:writing-plans` then `superpowers:subagent-driven-development` (which has its own implementer + spec reviewer + code quality reviewer ping-pong internally).
- For TRIVIAL: implement directly, dispatch one code-quality reviewer subagent.
- Apply caveman skill at full intensity to any plugin skill body modifications. Exceptions per `conventions.md`.
- Leave changes on the worktree branch. DO NOT MERGE.
- Write `synopsis.md` per template
- Update `status` to `3`

## Phase 4 — Main agent executive review (diff)

Main agent runs `git -C <target-repo> diff main...improve/<slug>` and reads `synopsis.md`. Executive-level critique only.

If satisfied: surface synopsis + branch + suggested merge command to user.

If not satisfied: same iteration pattern as Phase 2 (append to `exec-review-history.md`, resume side quest, max 3 cycles, escalate on cap).

Update `status` to `4` after user approval.

## Phase 5 — Deploy

On user approval, main agent invokes the `deploy-harness` skill via:

```bash
cd <plugin-repo> && claude -p \
  --model haiku \
  --max-budget-usd 5 \
  --permission-mode acceptEdits \
  --output-format json \
  "PHASE DEPLOY of improve-harness workflow.
   Read <plugin-root>/skills/deploy-harness/SKILL.md.
   Branch: improve/<slug>."
```

Update `status` to `5` on completion.

## Phase 6 — Reload prompt

Main agent surfaces to user:

> Plugin updated to vX.Y.Z+1. Reload Claude Code plugins to activate (or restart your session).

Update `status` to `6`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/improve-harness/phases.md
git commit -m "feat(skills): add improve-harness phases sub-asset"
```

---

## Task 13: Author improve-harness/SKILL.md (thin index)

**Files:**
- Create: `skills/improve-harness/SKILL.md`

- [ ] **Step 1: Create the thin top-level index**

Create `skills/improve-harness/SKILL.md`. Aim for ~80 lines, caveman-full:

```markdown
---
name: improve-harness
description: Use when the harness causes friction or the user expresses frustration. Triggers a multi-phase headless side quest to fix the system. Triggered by /improve-harness slash command, frustration phrases ("fuck", "wtf", "this keeps happening"), or repeated friction patterns.
---

# Improve Harness

Multi-phase side-quest workflow to fix harness friction.

> **Author note:** Loaded into every session that touches the obsidian-knowledge plugin. Multiplicative token burn. Cut anything not load-bearing. See `conventions.md`.

## When to invoke

- User runs `/improve-harness <description>`
- User expresses frustration with system: "fuck", "wtf", "this keeps happening", "the harness just blocked me"
- Main agent observes repeated friction (same workaround N times across session)

Do NOT invoke for:
- One-off mistakes the agent made (use normal correction)
- Friction with code outside the harness (file in vault as project insight)
- Brand-new patterns where root cause is unclear (gather more data first)

## Classification (two axes)

Before forking, classify:

**Scope**:
- **GLOBAL** — friction in plugin behavior (hooks, skills, plugin CLAUDE.md). Side quest works on `obsidian-knowledge` plugin repo.
- **REPO-SCOPED** — friction with project-specific convention. Side quest works on user's working repo.

**Complexity**:
- **TRIVIAL** — single file, pattern-level (regex, allowlist, CLAUDE.md line). Side quest implements directly + one reviewer.
- **NON-TRIVIAL** — multi-file, abstraction, behavior change. Side quest uses `superpowers:writing-plans` + `superpowers:subagent-driven-development`.

## Slug generation

Main agent picks kebab-case slug from friction description. ≤6 words. Append `-YYYY-MM-DD`.

Example: "the protect-vault hook blocked a benign ls" → `protect-vault-ls-false-positive-2026-04-25`

User never picks slug.

## Workflow overview

| Phase | What | Output |
|---|---|---|
| 0 | Main agent writes incident report | `incident-report.md` |
| 1 | Side quest: proposal subagent (with internal review) | `proposal.md` |
| 2 | Main agent: executive review of proposal | approve or iterate |
| 3 | Side quest: implementation (with internal review via subagent-driven-development) | branch + `synopsis.md` |
| 4 | Main agent: executive review of diff | approve or iterate |
| 5 | Deploy via `deploy-harness` skill | merged to main, version bumped |
| 6 | Prompt user to reload plugins | done |

State dir: `<target-repo>/.improve-harness/<slug>/`. Each phase writes its outputs there.

## Pointers

- Phase mechanics, exact invocations, iteration caps → `phases.md`
- Incident report / proposal / synopsis structures → `templates.md`
- Caveman authoring, security exceptions, token-burn warning → `conventions.md`

## Safety properties

- Iteration cap (3) per main-agent review phase. Escalate on cap.
- Side quest never merges. Always leaves branch for human approval.
- All headless invocations have `--max-budget-usd 30` cap.
- Worktree isolation: side quest works on `improve/<slug>` branch in `--worktree`.
- Memory symlink (per substrate) means changes Synced across machines via the vault.
```

- [ ] **Step 2: Verify SKILL.md is ≤100 lines**

Run: `wc -l /home/ricardo/src/PERSONAL/obsidian-knowledge/skills/improve-harness/SKILL.md`
Expected: ≤100 lines. If over, refactor into sub-assets per `conventions.md`.

- [ ] **Step 3: Commit**

```bash
git add skills/improve-harness/SKILL.md
git commit -m "feat(skills): add improve-harness top-level index"
```

---

## Task 14: Author deploy-harness/SKILL.md

**Files:**
- Create: `skills/deploy-harness/SKILL.md`

- [ ] **Step 1: Create the deploy-harness skill**

Create `skills/deploy-harness/SKILL.md`:

```markdown
---
name: deploy-harness
description: Merge an approved improve-harness branch into main, bump patch version, push to origin. Callable from improve-harness Phase 5 OR manually for hand-edited changes.
---

# Deploy Harness

Single-purpose skill: ship a branch.

## Inputs

- `<branch>` — branch name to merge (typically `improve/<slug>`)
- Cwd: must be the plugin repo

## Steps

1. Verify cwd is plugin repo:
   ```bash
   git remote get-url origin
   ```
   Confirm origin is the obsidian-knowledge repo.

2. Verify branch exists locally:
   ```bash
   git branch --list <branch>
   ```

3. Checkout main and pull latest:
   ```bash
   git checkout main && git pull origin main
   ```

4. Merge no-ff:
   ```bash
   git merge --no-ff <branch>
   ```
   If merge conflicts: STOP. Surface to user. Do not attempt resolution autonomously.

5. Bump patch version in `.claude-plugin/plugin.json`:
   - Read current version (e.g., "2.1.0")
   - Bump patch (→ "2.1.1")
   - Write back, preserving JSON formatting

6. Stage version bump:
   ```bash
   git add .claude-plugin/plugin.json
   git commit -m "chore(harness): release v<X.Y.Z+1>"
   ```

7. Push to origin:
   ```bash
   git push origin main
   ```

8. Report to caller:
   - Final SHA: `git rev-parse HEAD`
   - New version: `<X.Y.Z+1>`
   - Branch deleted (locally): `git branch -d <branch>`

## Safety

- Never force-push.
- Never skip pre-commit hooks.
- Never run on a non-plugin repo.
- Never merge if `git status` shows uncommitted changes — abort with message.
```

- [ ] **Step 2: Commit**

```bash
git add skills/deploy-harness/SKILL.md
git commit -m "feat(skills): add deploy-harness skill"
```

---

## Task 15: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README**

Read `/home/ricardo/src/PERSONAL/obsidian-knowledge/README.md` to understand current structure.

- [ ] **Step 2: Add new sections**

Use Edit tool to add a new section after the "Hooks" section (and before "Requirements"). Suggested content:

```markdown
### recall-init (SessionStart)

`recall-init.py` runs at every session start. Two responsibilities:

1. **Verify the memory symlink.** Checks that `~/.claude/projects/` is symlinked to `<vault-root>/wiki/systems/repos/`. If not, emits a non-blocking warning telling the user to run `/setup-harness`.
2. **Inject the harness primer.** Adds a 5-directive context block to the session: memory location, recall via `rg`, capture at session end, friction reflection, user-frustration reflection. The primer stands alone — agents that read only this know how to operate within the harness.

### reflect-nudge (PostToolUse on Bash)

`reflect-nudge.py` fires every 10 bash invocations within a session. Continuous — no per-session suppression. Reminds the agent to step back and consider whether observed friction warrants a harness improvement.

## Skills (added in v2.1)

### improve-harness

Multi-phase side-quest workflow to fix harness friction. Triggered by `/improve-harness <description>` or natural-language frustration phrases. Side quest runs as a headless `claude -p --worktree` session that produces a proposal (with internal review), receives main-agent executive review, then implements (with internal review via `subagent-driven-development`) and leaves a branch for human approval.

The skill is organized for progressive disclosure: `SKILL.md` is a thin index; sub-asset files (`phases.md`, `templates.md`, `conventions.md`) hold the details and load only when needed.

### deploy-harness

Single-purpose skill: merge an approved `improve/<slug>` branch into main, bump patch version, push to origin. Called from `improve-harness` Phase 5 or invokable manually.

## Commands (added in v2.1)

### /setup-harness

One-time migration. Rsyncs `~/.claude/projects/*` into `<vault>/wiki/systems/repos/`, surfaces collisions for manual merge, then replaces `~/.claude/projects/` with a symlink. Idempotent re-runs are safe.

### /improve-harness <description>

Triggers the meta-improvement workflow. The argument is the friction description — main agent uses it to seed the incident report and generate a slug.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document v2.1 hooks, skills, commands"
```

---

## Task 16: End-to-end smoke validation

**Files:** none modified — this is a verification task

- [ ] **Step 1: Validate all hook configurations parse**

Run: `python3 -c "import json; json.load(open('/home/ricardo/src/PERSONAL/obsidian-knowledge/.claude-plugin/plugin.json'))"`
Expected: no output.

- [ ] **Step 2: Run full test suite**

Run: `cd /home/ricardo/src/PERSONAL/obsidian-knowledge && python3 -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 3: Verify hook scripts are executable**

```bash
test -x /home/ricardo/src/PERSONAL/obsidian-knowledge/hooks/recall-init.py && echo "recall-init OK"
test -x /home/ricardo/src/PERSONAL/obsidian-knowledge/hooks/reflect-nudge.py && echo "reflect-nudge OK"
```
Expected: both print "OK".

- [ ] **Step 4: Verify skill structure**

```bash
ls /home/ricardo/src/PERSONAL/obsidian-knowledge/skills/improve-harness/
```
Expected: `SKILL.md`, `phases.md`, `templates.md`, `conventions.md`.

```bash
ls /home/ricardo/src/PERSONAL/obsidian-knowledge/skills/deploy-harness/
```
Expected: `SKILL.md`.

- [ ] **Step 5: Verify SKILL.md frontmatter parses**

```bash
python3 -c "
import yaml
for path in [
    '/home/ricardo/src/PERSONAL/obsidian-knowledge/skills/improve-harness/SKILL.md',
    '/home/ricardo/src/PERSONAL/obsidian-knowledge/skills/deploy-harness/SKILL.md',
]:
    with open(path) as f:
        text = f.read()
    parts = text.split('---', 2)
    fm = yaml.safe_load(parts[1])
    assert 'name' in fm and 'description' in fm, f'missing fields in {path}'
    print(f'OK: {path}')
"
```
Expected: prints "OK:" for each skill.

- [ ] **Step 6: Verify SKILL.md line count**

```bash
wc -l /home/ricardo/src/PERSONAL/obsidian-knowledge/skills/improve-harness/SKILL.md
```
Expected: ≤100 lines (per progressive disclosure discipline).

- [ ] **Step 7: Verify command structure**

```bash
ls /home/ricardo/src/PERSONAL/obsidian-knowledge/commands/
```
Expected: `setup-harness.md`, `improve-harness.md`.

- [ ] **Step 8: Manual smoke (optional, requires user)**

The user should:
1. Run `/setup-harness` (verify migration works on their machine)
2. Restart Claude Code
3. Verify the SessionStart primer appears in next session
4. Trigger 10+ bash commands and verify reflect-nudge fires
5. Run `/improve-harness "test friction"` with a low-stakes friction and observe the workflow

This is documented for the user but not automated.

- [ ] **Step 9: Commit any final touch-ups**

If steps 1-7 surfaced any issues, fix them inline as separate small commits. Otherwise, no additional commit needed.

---

## Summary

After completing all tasks, the plugin will have:

- ✅ SessionStart `recall-init.py` injecting the harness primer
- ✅ PostToolUse `reflect-nudge.py` firing every 10 bash calls
- ✅ `/setup-harness` command for one-time symlink migration
- ✅ `/improve-harness` slash command shim
- ✅ `improve-harness` skill with progressive-disclosure structure (SKILL.md + 3 sub-assets)
- ✅ `deploy-harness` companion skill
- ✅ Test coverage for both new hooks
- ✅ README documentation
- ✅ Updated plugin.json (version 2.1.0)
- ✅ Existing hooks untouched

Acceptance criteria from spec are satisfied. Ready for end-to-end smoke testing in real usage.
