"""Python hooks run via `uv run --script` with only their PEP 723 dependencies.

Hooks must not rely on the system interpreter's packages or on the project
venv: each declares what it imports (including through hookslib) in its
inline `# /// script` block, and uv builds an isolated env from exactly that.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
MANIFEST = REPO / ".claude-plugin" / "plugin.json"
LAUNCHER = "uv run --script ${CLAUDE_PLUGIN_ROOT}/"


def hook_commands() -> list[str]:
    hooks = json.loads(MANIFEST.read_text())["hooks"]
    return [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]


def python_hooks() -> list[str]:
    return sorted(c.removeprefix(LAUNCHER) for c in hook_commands() if c.endswith(".py"))


def test_python_hooks_use_uv_script_launcher():
    offenders = [c for c in hook_commands() if c.endswith(".py") and not c.startswith(LAUNCHER)]
    assert offenders == [], "launch Python hooks with `uv run --script` and a PEP 723 block"
    assert "hooks/doctor.py" in python_hooks()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
@pytest.mark.parametrize("script", python_hooks())
def test_hook_imports_with_declared_dependencies_only(script, tmp_path):
    # `--exact` prunes packages a cached script env kept from older metadata,
    # so a dropped dependency fails here instead of passing on stale state.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["HOME"] = str(tmp_path)
    env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    proc = subprocess.run(
        ["uv", "run", "--exact", "--script", str(REPO / script)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
