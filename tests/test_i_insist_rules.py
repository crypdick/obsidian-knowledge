"""Vault policy exercised through the executable neutral checker."""

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


def file_event(directory, path, content="", operation="write"):
    absolute = str(directory / path)
    return {
        "kind": "file_write" if operation == "write" else "file_edit",
        "cwd": str(directory),
        "paths": [absolute],
        "changes": [{"path": absolute, "operation": operation, "content": content}],
    }


@pytest.mark.parametrize("operation", ["write", "edit", "delete"])
def test_checker_protects_every_file_target(tmp_path, operation):
    event = file_event(tmp_path, "safe.md")
    target = str(tmp_path / "_sources/original.pdf")
    event["paths"].append(target)
    event["changes"].append({"path": target, "operation": operation, "content": ""})
    result = run_check(tmp_path, "protected-dirs", event)
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)
        == "Cannot modify _sources directories in configured vaults; these contain irreplaceable originals. Ask the human for consent."
    )
    assert json.loads(run_check(tmp_path, "protected-dirs", file_event(tmp_path, "safe.md")).stdout) is None


def test_non_overridable_policy_metadata():
    import tomllib

    rules = tomllib.loads((ROOT / "hooks/i-insist.toml").read_text())["rules"]
    assert {r["id"] for r in rules if not r.get("overridable", True)} == {
        "publish-allowlist",
        "generic-filenames",
        "illegal-filenames",
        "memory-routing",
        "wikilinks",
        "dated-filenames",
        "frontmatter",
    }


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"kind": "other", "cwd": "relative", "changes": []},
        {"kind": "shell", "cwd": "/", "changes": []},
        {"kind": "file_write", "cwd": "/", "paths": ["/note.md"], "changes": []},
        {
            "kind": "file_write",
            "cwd": "/",
            "paths": ["/note.md"],
            "changes": [{"path": "/note.md", "operation": "write", "content": 42}],
        },
    ],
)
def test_checker_rejects_invalid_events(tmp_path, event):
    result = run_check(tmp_path, "protected-dirs", event)
    assert result.returncode == 2
    assert not result.stdout


def test_checker_ignores_other_events_and_rejects_unknown_rule(tmp_path):
    event = {"kind": "other", "cwd": str(tmp_path), "changes": []}
    assert json.loads(run_check(tmp_path, "protected-dirs", event).stdout) is None
    assert run_check(tmp_path, "unknown", event).returncode == 2


@pytest.mark.parametrize(
    "rule,path,content,blocked",
    [
        ("wikilinks", "note.md", "See [[target.md]]", True),
        ("wikilinks", "note.md", "See [[target]] and [[photo.jpg]]", False),
        ("frontmatter", "note.md", "---\ntitle: [broken\n---", True),
        ("frontmatter", "note.md", "---\ntitle: valid\n---", False),
        ("frontmatter", "note.md", "---\n---\nbody", False),
        ("dated-filenames", "Journal/note.md", "text", True),
        ("dated-filenames", "Journal/2026-09-17 note.md", "text", False),
        ("dated-filenames", "Journal/index.md", "text", False),
        ("publish-allowlist", "private.md", "dg-publish: true", True),
        ("publish-allowlist", "Public/note.md", "dg-publish: true", False),
        ("publish-allowlist", "Publicity/note.md", "dg-publish: true", True),
        ("publish-allowlist", "private.md", "dg-publish: false", False),
        ("generic-filenames", "plan.md", "", True),
        ("generic-filenames", "project-plan.md", "", False),
        ("generic-filenames", "index.md", "", False),
        ("illegal-filenames", "bad:name.md", "", True),
        ("illegal-filenames", "good-name.md", "", False),
        ("ai-readonly", "Public/note.md", "", True),
        ("ai-readonly", "private.md", "", False),
    ],
)
def test_file_policy_decisions(tmp_path, rule, path, content, blocked):
    policy = tmp_path / ".claude/obsidian-knowledge.yaml"
    policy.parent.mkdir()
    policy.write_text(
        'publish_allowlist: ["Public/"]\nai_readonly_folders: [Public]\ngeneric_filenames: [plan.md, index.md]\nillegal_filename_chars: [":"]\n'
    )
    result = run_check(tmp_path, rule, file_event(tmp_path, path, content))
    assert result.returncode == 0, result.stderr
    assert (json.loads(result.stdout) is not None) is blocked


@pytest.mark.parametrize("rule", ["wikilinks", "frontmatter", "dated-filenames", "publish-allowlist"])
def test_content_rules_ignore_deletions(tmp_path, rule):
    event = file_event(tmp_path, "Journal/undated.md", "[[bad.md]]", "delete")
    assert json.loads(run_check(tmp_path, rule, event).stdout) is None


def test_existing_undated_file_can_be_edited(tmp_path):
    (tmp_path / "Journal").mkdir()
    (tmp_path / "Journal/old.md").write_text("old")
    event = file_event(tmp_path, "Journal/old.md", "updated", "edit")
    assert json.loads(run_check(tmp_path, "dated-filenames", event).stdout) is None


def test_readonly_outside_vault_is_allowed(tmp_path):
    event = file_event(tmp_path.parent, "outside.md")
    assert json.loads(run_check(tmp_path, "ai-readonly", event).stdout) is None


@pytest.mark.parametrize(
    "content",
    ["ordinary text", "---\ndg-publish: true"],
)
@pytest.mark.parametrize("operation", ["write", "edit"])
def test_unpublished_files_can_be_edited(tmp_path, content, operation):
    note = tmp_path / "note.md"
    note.write_text(content)
    event = file_event(tmp_path, "note.md", "replacement", operation)
    assert json.loads(run_check(tmp_path, "published-files", event).stdout) is None


@pytest.mark.parametrize("operation", ["write", "edit"])
def test_missing_published_file_is_allowed(tmp_path, operation):
    event = file_event(tmp_path, "missing.md", "replacement", operation)
    assert json.loads(run_check(tmp_path, "published-files", event).stdout) is None


def test_non_file_rule_allows_file_event(tmp_path):
    assert json.loads(run_check(tmp_path, "destructive-ops", file_event(tmp_path, "note.md")).stdout) is None


def test_shell_content_rule_is_not_applied(tmp_path):
    event = {"kind": "shell", "cwd": str(tmp_path), "command": "true", "changes": []}
    assert json.loads(run_check(tmp_path, "wikilinks", event).stdout) is None


def test_file_event_requires_matching_nonempty_changes(tmp_path):
    event = file_event(tmp_path, "note.md")
    event["changes"] = []
    result = run_check(tmp_path, "protected-dirs", event)
    assert result.returncode == 2
    assert "needs a change for every path" in result.stderr


def test_checker_requires_one_rule_argument():
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks/i_insist.py")],
        input="{}",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "expected one rule id" in result.stderr


@pytest.mark.parametrize("operation", ["write", "edit", "delete"])
def test_published_file_needs_consent(tmp_path, operation):
    (tmp_path / "live.md").write_text("---\ndg-publish: true\n---\nbody")
    event = file_event(tmp_path, "live.md", "replacement", operation)
    assert json.loads(run_check(tmp_path, "published-files", event).stdout) is not None


def test_conventions_do_not_apply_outside_vault(tmp_path):
    event = file_event(tmp_path.parent, "outside.md", "[[bad.md]]")
    assert json.loads(run_check(tmp_path, "wikilinks", event).stdout) is None


@pytest.mark.parametrize(
    "basename,blocked",
    [
        ("feedback_x.md", True),
        ("project_x.md", True),
        ("reference_x.md", True),
        ("user_profile.md", False),
        ("MEMORY.md", False),
    ],
)
def test_memory_routing(tmp_path, basename, blocked):
    event = file_event(tmp_path, f".claude/projects/slug/memory/{basename}")
    assert (json.loads(run_check(tmp_path, "memory-routing", event).stdout) is not None) is blocked


@pytest.mark.parametrize("installed_version", [None, "0.3.3", "0.4.0"])
def test_installer_bootstraps_runner_and_replaces_owned_rules(tmp_path, monkeypatch, installed_version):
    from lib.vault_index.guard_install import install_rules

    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    runner = binary / "i-insist"
    runner_source = tmp_path / "runner"
    runner_source.write_text("""#!/bin/sh
if [ "$1" = "--version" ]; then echo "i-insist 0.4.0"; else echo ensure >> "$CALL_LOG"; fi
""")
    monkeypatch.setenv("PATH", str(binary))
    monkeypatch.setenv("CALL_LOG", str(log))
    monkeypatch.setenv("RUNNER_BIN", str(runner))
    monkeypatch.setenv("RUNNER_SOURCE", str(runner_source))
    if installed_version:
        runner.write_text(runner_source.read_text().replace("0.4.0", installed_version))
        runner.chmod(0o755)
    uv = binary / "uv"
    uv.write_text("""#!/bin/sh
echo "$*" >> "$CALL_LOG"
/bin/cp "$RUNNER_SOURCE" "$RUNNER_BIN"
/bin/chmod +x "$RUNNER_BIN"
""")
    uv.chmod(0o755)
    path = install_rules(tmp_path)
    expected = (
        ["ensure"] if installed_version == "0.4.0" else ["tool install --upgrade i-insist>=0.4.0", "ensure"]
    )
    assert log.read_text().splitlines() == expected
    assert path == tmp_path / ".i-insist/obsidian-knowledge.toml"
    expected_rules = (ROOT / "hooks/i-insist.toml").read_text()
    other = path.with_name("other.toml")
    other.write_text("# other provider")
    path.write_text('[[rules]]\nid="disabled"\nenabled=false\n')
    install_rules(tmp_path)
    assert path.read_text() == expected_rules
    assert other.read_text() == "# other provider"
    assert log.read_text().splitlines() == [*expected, "ensure"]


def test_installer_keeps_rules_unchanged_when_runner_disabled(tmp_path, monkeypatch):
    from lib.vault_index.guard_install import install_rules

    monkeypatch.setenv("PATH", str(tmp_path))
    runner = tmp_path / "i-insist"
    runner.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "i-insist 0.4.0"; else exit 2; fi\n')
    runner.chmod(0o755)
    with pytest.raises(subprocess.CalledProcessError):
        install_rules(tmp_path)
    assert not (tmp_path / ".i-insist").exists()


@pytest.mark.parametrize("content", ["publish_allowlist: [broken", "- Public/", "false"])
def test_malformed_policy_is_checker_failure(tmp_path, content):
    policy = tmp_path / ".claude/obsidian-knowledge.yaml"
    policy.parent.mkdir()
    policy.write_text(content)
    result = run_check(tmp_path, "publish-allowlist", file_event(tmp_path, "private.md", "dg-publish: true"))
    assert result.returncode != 0
    assert not result.stdout
    assert result.stderr


@pytest.mark.parametrize("stage", ["create", "replace"])
def test_registration_write_failure_preserves_previous_file(tmp_path, monkeypatch, stage):
    from types import SimpleNamespace

    from lib.vault_index import guard_install

    monkeypatch.setattr(guard_install.shutil, "which", lambda name: "/bin/i-insist")
    monkeypatch.setattr(
        guard_install.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="i-insist 0.4.0"),
    )
    path = tmp_path / ".i-insist/obsidian-knowledge.toml"
    path.parent.mkdir()
    path.write_text("previous complete registration")

    def unavailable(*args, **kwargs):
        raise OSError("storage unavailable")

    if stage == "create":
        monkeypatch.setattr(guard_install.tempfile, "mkstemp", unavailable)
    else:
        monkeypatch.setattr(Path, "replace", unavailable)
    with pytest.raises(OSError, match="storage unavailable"):
        guard_install.install_rules(tmp_path)
    assert path.read_text() == "previous complete registration"
    assert list(path.parent.iterdir()) == [path]
