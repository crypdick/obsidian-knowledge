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
from collections.abc import Callable
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
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
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
        "garden",
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
    search_report = json.loads(run("search", "orchid greenhouse", "--json", "--all", "--top-k", "1"))
    assert search_report["mode"] in {"keyword", "hybrid"}
    assert "degraded_reason" in search_report
    assert search_report["hits"][0]["path"] == "wiki/orchid.md"
    assert "greenhouse" in search_report["hits"][0]["snippet"]
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
    exercise_garden(vault, run)
    print(f"All {checks} installed CLI checks passed.")


def exercise_garden(vault: Path, run: Callable[..., str]) -> None:
    """Exercise bundled gardener modules through the installed executable."""
    for operation in ("audit", "links", "index", "questions", "frontmatter"):
        run("garden", operation, "--help")

    folder = vault / "wiki/garden-smoke"
    folder.mkdir()
    config = vault / ".claude/obsidian-knowledge.yaml"
    with config.open("a") as handle:
        handle.write("\nai_managed: [wiki]\nai_readonly_folders: [wiki/garden-smoke/readonly]\n")
    source = folder / "source.md"
    original = "# Source\n\nSee [[renamed_file#Heading|display]].\n\n> [!question]\n> Which flower?\n"
    source.write_text(original)
    (folder / "Renamed File.md").write_text("# Renamed flower\n")
    index = folder / "index.md"
    index_before = "# Garden smoke\n\nContext stays.\n\n"
    index.write_text(index_before)
    stacked = folder / "stacked.md"
    stacked_before = "---\r\ntitle: Flower\r\n---\r\n---\r\n# Flower\r\n"
    stacked.write_bytes(stacked_before.encode())
    protected = {}
    for relative in (
        "_sources/protected.md",
        "wiki/garden-smoke/readonly/readonly.md",
        "wiki/garden-smoke/.hidden/ignored.md",
        "wiki/garden-smoke/ignored.sync-conflict-20261003-120000-device.md",
    ):
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        question = "Readonly question" if "/readonly/" in relative else "Protected question"
        body = stacked_before + f"> [!question]\r\n> {question}\r\n"
        path.write_bytes(body.encode())
        protected[relative] = path.read_bytes()
    outside = vault.parent / "outside-garden.md"
    outside.write_bytes(stacked_before.encode())
    (folder / "symlink.md").symlink_to(outside)

    def garden(operation: str, *args: str, **kwargs: object) -> str:
        return run("garden", operation, "--vault", str(vault), *args, **kwargs)

    audit = garden("audit")
    assert f"STACKED_FRONTMATTER\t{stacked}" in audit
    assert "protected.md" not in audit and "ignored" not in audit and "symlink.md" not in audit
    assert stacked.read_bytes() == stacked_before.encode()

    review = json.dumps(
        {"entries": [{"target": "wiki/garden-smoke/source", "description": "flower question"}]}
    )
    rendered_index = garden("index", "wiki/garden-smoke/index.md", content=review)
    assert "Context stays." in rendered_index
    assert "- [[wiki/garden-smoke/source]] — flower question" in rendered_index
    assert index.read_text() == index_before
    garden("index", "wiki/garden-smoke/index.md", "--apply", content=review)
    assert index.read_text() == rendered_index

    links = json.dumps([{"link": "renamed_file", "sources": "wiki/garden-smoke/source.md"}])
    decisions = json.loads(garden("links", "--format", "json", content=links))
    assert len(decisions) == 1 and decisions[0]["auto_fixable"]
    assert decisions[0]["candidates"] == ["wiki/garden-smoke/Renamed File.md"]
    assert source.read_text() == original
    assert "# applied_rewrites\t1" in garden("links", "--apply", content=links)
    assert source.read_text() == original.replace("renamed_file", "wiki/garden-smoke/Renamed File")

    report = vault / "Utility/obsidian-knowledge/reports/open-questions.md"
    report_args = ("--report", "--timestamp", "2026-10-03T12:00:00+00:00")
    report_text = garden("questions", *report_args)
    assert "Which flower?" in report_text and "Readonly question" in report_text
    assert "Protected question" not in report_text
    assert not report.exists()
    garden("questions", *report_args, "--apply")
    assert report.read_text() == report_text

    assert "WOULD_FIX" in garden("frontmatter", "wiki/garden-smoke/stacked.md")
    assert stacked.read_bytes() == stacked_before.encode()
    assert "FIXED" in garden("frontmatter", "wiki/garden-smoke/stacked.md", "--apply")
    assert stacked.read_bytes() == b"---\r\ntitle: Flower\r\n---\r\n# Flower\r\n"
    for relative in (*protected, "wiki/garden-smoke/symlink.md", "../outside-garden.md"):
        garden("frontmatter", relative, "--apply", expected=1)
    assert outside.read_bytes() == stacked_before.encode()
    assert all((vault / relative).read_bytes() == body for relative, body in protected.items())


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
