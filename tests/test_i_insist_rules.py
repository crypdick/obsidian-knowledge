"""Provider protocol exercised through the executable checker."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_check(tmp_path, rule, event):
    registry = tmp_path / "vaults.yaml"
    registry.write_text("vaults:\n  - " + str(tmp_path) + "\n")
    env = {**os.environ, "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(registry)}
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks/i_insist.py"), rule],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


@pytest.mark.parametrize("kind", ["file_write", "file_edit"])
def test_checker_protects_all_neutral_paths(tmp_path, kind):
    event = {
        "kind": kind,
        "cwd": str(tmp_path),
        "paths": [str(tmp_path / "safe.md"), str(tmp_path / "_sources/original.pdf")],
        "tool_name": "any_native_tool",
        "tool_input": {},
    }
    result = run_check(tmp_path, "protected-dirs", event)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is True
    event["paths"] = [str(tmp_path / "safe.md")]
    assert json.loads(run_check(tmp_path, "protected-dirs", event).stdout) is False


def test_checker_blocks_shell_writes_in_vault(tmp_path):
    event = {
        "kind": "shell",
        "cwd": str(tmp_path),
        "paths": [],
        "command": "rm -rf _sources",
        "tool_input": {},
    }
    result = run_check(tmp_path, "protected-dirs", event)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is True


def test_non_overridable_policy_metadata():
    import tomllib

    rules = tomllib.loads((ROOT / "hooks/i-insist.toml").read_text())["rules"]
    protected = {r["id"] for r in rules if not r.get("overridable", True)}
    assert protected == {
        "publish-allowlist",
        "generic-filenames",
        "illegal-filenames",
        "memory-routing",
        "wikilinks",
        "dated-filenames",
        "frontmatter",
    }


def test_checker_rejects_malformed_event(tmp_path):
    result = run_check(tmp_path, "protected-dirs", {})
    assert result.returncode != 0
    assert not result.stdout


@pytest.mark.parametrize(
    ("rule", "event", "error"),
    [
        ("unknown", {"kind": "other", "cwd": "/"}, "unknown rule"),
        ("protected-dirs", {"kind": "other", "cwd": "relative"}, "absolute cwd"),
        ("protected-dirs", {"kind": "shell", "cwd": "/"}, "needs command"),
        ("protected-dirs", {"kind": "file_write", "cwd": "/", "paths": [""]}, "needs paths"),
    ],
)
def test_checker_rejects_invalid_protocol_fields(tmp_path, rule, event, error):
    result = run_check(tmp_path, rule, event)
    assert result.returncode == 2
    assert error in result.stderr


def test_checker_ignores_other_events(tmp_path):
    result = run_check(tmp_path, "protected-dirs", {"kind": "other", "cwd": str(tmp_path)})
    assert result.returncode == 0
    assert json.loads(result.stdout) is False


@pytest.mark.parametrize(
    ("rule", "path", "content", "blocked"),
    [
        ("wikilinks", "note.md", "See [[target.md]]", True),
        ("wikilinks", "note.md", "See [[target]]", False),
        ("frontmatter", "note.md", "---\ntitle: [broken\n---", True),
        ("frontmatter", "note.md", "---\ntitle: valid\n---", False),
        ("dated-filenames", "Journal/note.md", "text", True),
        ("dated-filenames", "Journal/2026-09-17 note.md", "text", False),
    ],
)
def test_checker_enforces_content_conventions(tmp_path, rule, path, content, blocked):
    (tmp_path / "Journal").mkdir(exist_ok=True)
    event = {
        "kind": "file_write",
        "cwd": str(tmp_path),
        "paths": [path],
        "tool_input": {"content": content},
    }
    result = run_check(tmp_path, rule, event)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) is blocked


def test_checker_adapts_multi_edit_content(tmp_path):
    event = {
        "kind": "file_edit",
        "cwd": str(tmp_path),
        "paths": ["note.md"],
        "tool_input": {"edits": [{"new_string": "See [[target.md]]"}, None]},
    }
    assert json.loads(run_check(tmp_path, "wikilinks", event).stdout) is True


def test_checker_adapts_patch_paths_and_content(tmp_path):
    event = {
        "kind": "file_write",
        "cwd": str(tmp_path),
        "paths": [str(tmp_path / "note.md")],
        "tool_input": ("*** Begin Patch\n*** Add File: note.md\n+See [[target.md]]\n*** End Patch"),
    }
    assert json.loads(run_check(tmp_path, "wikilinks", event).stdout) is True


def test_installer_bootstraps_runner_and_preserves_user_rules(tmp_path, monkeypatch):
    from lib.vault_index.guard_install import install_rules

    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    monkeypatch.setenv("PATH", str(binary))
    monkeypatch.setenv("CALL_LOG", str(log))
    monkeypatch.setenv("RUNNER_BIN", str(binary / "i-insist"))
    uv = binary / "uv"
    uv.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
printf '#!/bin/sh\\nprintf "ensure\\\\n" >> "$CALL_LOG"\\n' > "$RUNNER_BIN"
/bin/chmod +x "$RUNNER_BIN"
""")
    uv.chmod(0o755)
    path = install_rules(tmp_path)
    assert log.read_text().splitlines() == [
        "tool install git+https://github.com/crypdick/i-insist@main",
        "ensure",
    ]
    assert path == tmp_path / ".i-insist/obsidian-knowledge.toml"
    path.write_text('[[rules]]\nid="disabled"\nenabled=false\n')
    install_rules(tmp_path)
    assert path.read_text() == '[[rules]]\nid="disabled"\nenabled=false\n'
    assert log.read_text().splitlines()[-1] == "ensure"


def test_installer_keeps_rules_unchanged_when_runner_disabled(tmp_path, monkeypatch):
    from lib.vault_index.guard_install import install_rules

    monkeypatch.setenv("PATH", str(tmp_path))
    runner = tmp_path / "i-insist"
    runner.write_text("#!/bin/sh\nexit 2\n")
    runner.chmod(0o755)
    with pytest.raises(subprocess.CalledProcessError):
        install_rules(tmp_path)
    assert not (tmp_path / ".i-insist").exists()
