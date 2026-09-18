"""Exercise the installed CLI against a disposable vault and the live embedding service.

Run with `python scripts/cli_smoke_test.py [--executable /path/to/obsidian-knowledge]`.
The user's registry, vault, cache, and Claude plugin installation are not changed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def exercise(executable: str, root: Path) -> None:
    vault = root / "vault"
    vault.mkdir()
    env = {
        **os.environ,
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "home/.codex"),
        "CLAUDE_CONFIG_DIR": str(root / "home/.claude"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "UV_TOOL_DIR": str(root / "tools"),
        "UV_TOOL_BIN_DIR": str(root / "bin"),
        "PATH": os.pathsep.join(
            (str(root / "bin"), str(Path(executable).parent), os.environ.get("PATH", ""))
        ),
        "XDG_CONFIG_HOME": str(root / "home/.config"),
        "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG": str(root / "vaults.yaml"),
        "OBSIDIAN_KNOWLEDGE_CACHE_ROOT": str(root / "cache"),
        "TMPDIR": str(root),
    }
    checks = 0

    def run(*args: str, content: str = "", expected: int = 0) -> str:
        nonlocal checks
        result = subprocess.run(
            [executable, *args],
            input=content,
            capture_output=True,
            text=True,
            cwd=vault,
            env=env,
            timeout=90,
        )
        if result.returncode != expected:
            raise RuntimeError(f"{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
        if "Traceback" in result.stderr or "socksio" in result.stderr:
            raise RuntimeError(f"{args}: unexpected error output\n{result.stderr}")
        checks += 1
        print(f"PASS {checks:2}: {' '.join(args)}", flush=True)
        return result.stdout

    commands = (
        "setup",
        "init-vault-index",
        "read",
        "write",
        "reindex",
        "search",
        "remember",
        "papercut",
        "doctor",
        "_hook",
    )
    help_text = run("--help")
    for command in commands:
        assert command in help_text
        run(command, "--help")

    run("init-vault-index", "--vault", str(vault))
    config = vault / ".claude" / "obsidian-knowledge.yaml"
    before = config.read_bytes()
    run("init-vault-index", "--vault", str(vault))
    assert config.read_bytes() == before

    note = "# Orchid smoke verification\n\nPurple orchids grow in the greenhouse.\n"
    run("write", "wiki/orchid.md", "--vault", str(vault), content=note)
    assert run("read", "wiki/orchid.md", "--vault", str(vault)) == note
    run("write", "wiki/orchid.md", "--vault", str(vault), content="replacement", expected=2)
    assert (vault / "wiki/orchid.md").read_text() == note
    note += "Verified replacement.\n"
    run("write", "wiki/orchid.md", "--vault", str(vault), "--replace", content=note)
    run("write", "wiki/blank.md", "--vault", str(vault), content=" \n", expected=2)
    run("read", "../outside.md", "--vault", str(vault), expected=2)
    assert "Setup complete." in run("setup", "--vault", str(vault), "--skip-claude-plugin")
    assert not (root / "home" / ".i-insist" / "obsidian-knowledge.toml").exists()
    assert "already registered" in run(
        "setup", "--vault", str(vault), "--skip-claude-plugin", "--install-guards"
    )
    exercise_guards(vault, env)
    assert run("read", "wiki/orchid.md") == note

    run("reindex", "--force", "--timeout-seconds", "60")
    assert "Skipped:" in run("reindex", "--timeout-seconds", "60")
    assert "wiki/orchid.md" in run("search", "orchid greenhouse", "--top-k", "1")
    assert "wiki/orchid.md" in run("search", "orchid", "--all")
    assert "wiki/orchid.md" in run("remember", "orchid greenhouse", "--all", "--top-k", "1")
    doctor = run("doctor", "--query", "orchid", "--top-k", "1", "--digest-only")
    assert "status: PASS" in doctor
    print(doctor, end="")
    run("papercut", "Disposable CLI smoke test")
    log = vault / "wiki/systems/knowledge-base/PAPERCUTS.md"
    assert "Disposable CLI smoke test" in log.read_text()

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "true"}})
    for agent in ("claude", "codex"):
        for event in ("post-tool-use", "session-start"):
            output = run("_hook", event, "--agent", agent, content=payload)
            if event == "session-start":
                assert (
                    "obsidian-knowledge harness"
                    in json.loads(output)["hookSpecificOutput"]["additionalContext"]
                )
        for kind in ("capture-session", "update-changelog", "remind-convos", "nudge-index-sync"):
            stop_payload = json.dumps({"session_id": f"{root.name}-{agent}-{kind}"})
            output = run("_hook", "stop", "--kind", kind, "--agent", agent, content=stop_payload)
            if kind != "nudge-index-sync":
                assert json.loads(output)["decision"] == "block"
    run("_hook", "stop", "--kind", "invalid", content="{}", expected=2)
    print(f"All {checks} installed CLI checks passed.")


def exercise_guards(vault: Path, env: dict[str, str]) -> None:
    """Exercise the installed runner and provider together without executing edits."""
    for harness in ("codex", "claude"):

        def hook(event: str, harness: str = harness, **fields: object) -> dict:
            result = subprocess.run(
                ["i-insist", "hook", "--harness", harness, event],
                input=json.dumps({"session_id": "smoke", "turn_id": "1", "cwd": str(vault), **fields}),
                env=env,
                cwd=vault,
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
            return json.loads(result.stdout) if result.stdout.strip() else {}

        hook("user-prompt-submit", prompt="Check vault protection")
        edits = [
            {"tool_name": "Write", "tool_input": {"file_path": "_sources/original.md", "content": "x"}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Delete File: _sources/original.md\n*** End Patch"
                },
            },
        ]
        for edit in edits:
            result = hook("pre-tool-use", **edit)["hookSpecificOutput"]
            assert result["permissionDecision"] == "deny"
            assert "irreplaceable originals" in result["permissionDecisionReason"]
        hook("user-prompt-submit", prompt="I insist")
        assert hook("pre-tool-use", **edits[0]) == {}
        result = hook(
            "pre-tool-use",
            tool_name="MultiEdit",
            tool_input={
                "file_path": "wiki/note.md",
                "edits": [{"new_string": "[[bad.md]]"}],
            },
        )["hookSpecificOutput"]
        assert result["permissionDecision"] == "deny"
        assert "wikilinks" in result["permissionDecisionReason"]
        hook("user-prompt-submit", prompt="Next task")
        assert hook("pre-tool-use", **edits[0])["hookSpecificOutput"]["permissionDecision"] == "deny"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", default="obsidian-knowledge")
    args = parser.parse_args()
    executable = shutil.which(args.executable)
    if executable is None:
        parser.error(f"executable not found: {args.executable}")  # allow: unstructured-logging (argparse)
    with tempfile.TemporaryDirectory(prefix="obsidian-cli-smoke-") as directory:
        exercise(str(Path(executable).absolute()), Path(directory))


if __name__ == "__main__":
    main()
