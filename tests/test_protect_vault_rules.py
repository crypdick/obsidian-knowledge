"""Behavior matrix for vault write-protection rules."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def guard_module():
    spec = importlib.util.spec_from_file_location("protect_vault_rules", ROOT / "hooks/protect-vault.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard(tmp_path, monkeypatch, guard_module):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(guard_module, "VAULT_ROOTS", [str(vault)])
    monkeypatch.setattr(guard_module, "load_vault_policy", lambda root: {})
    return guard_module, vault


def check(guard, tool: str, tool_input: dict, *, cwd: Path | None = None):
    module, vault = guard
    return module.check_tool_call(tool, tool_input, workdir=str(cwd or vault))


def test_file_guard_blocks_protected_child_but_not_similar_outside_path(guard, tmp_path):
    module, vault = guard
    assert "BLOCKED [protected-dir]" in check(guard, "Write", {"file_path": "_sources/original.md"})
    outside = tmp_path / "outside" / "_sources" / "note.md"
    assert module.protected_dirs_file("Write", {"file_path": str(outside)}) is None


def test_malformed_shell_is_ignored_instead_of_crashing(guard):
    assert check(guard, "Bash", {"command": "rm -rf 'unterminated"}) is None
    assert check(guard, "Bash", {"command": "env -i NAME=value"}) is None


@pytest.mark.parametrize(
    "command",
    [
        "NAME=value rm -rf wiki",
        "env -i NAME=value rm -rf wiki",
        "command -- rm -rf wiki",
        "exec -- rm -rf wiki",
        "nohup rm -rf wiki",
        "sudo -u root rm -rf wiki",
        "sudo -u root -g wheel rm -rf wiki",
        "sudo -n -u root rm -rf wiki",
        "doas --user root rm -rf wiki",
    ],
)
def test_destructive_wrappers_do_not_hide_recursive_remove(guard, command):
    assert "BLOCKED [destructive-rm]" in check(guard, "Bash", {"command": command})


@pytest.mark.parametrize("command", ["rm wiki", "rm -f wiki", "printf rm", "echo rm -rf wiki"])
def test_non_recursive_or_non_command_remove_is_allowed(guard, command):
    assert check(guard, "Bash", {"command": command}) is None


def test_empty_destructive_target_is_ignored(guard):
    assert check(guard, "Bash", {"command": "rm -rf ''"}) is None


def test_redirection_and_sed_in_place_target_protected_paths(guard):
    assert "protected-dir-bash" in check(guard, "Bash", {"command": "printf data > _sources/file.md"})
    assert check(guard, "Bash", {"command": "printf data > /dev/null"}) is None
    assert "protected-dir-bash" in check(guard, "Bash", {"command": "sed -i s/a/b/ _sources/file.md"})


def test_cd_then_destructive_command_protects_relative_source_path(guard):
    reason = check(guard, "Bash", {"command": "cd _sources && rm file.md"})
    assert "appears to cd into a protected directory" in reason


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("find wiki -exec /bin/rm {} ;", "destructive-find"),
        ("find -delete", "destructive-find"),
        ("rsync --delete-excluded /tmp/source/ wiki/", "destructive-rsync-delete"),
        ("shred --zero wiki/note.md", "destructive-shred"),
        ("find /tmp -type f | xargs -n 2 rm", "destructive-xargs-rm"),
        ("find /tmp -type f | xargs -- rm", "destructive-xargs-rm"),
    ],
)
def test_destructive_command_variants_are_detected(guard, command, rule):
    assert f"BLOCKED [{rule}]" in check(guard, "Bash", {"command": command})


def test_xargs_rm_blocks_upstream_absolute_vault_reference(guard, tmp_path):
    module, vault = guard
    outside = tmp_path / "outside"
    outside.mkdir()
    command = f"find {vault} -type f | xargs rm"
    assert "pipeline that references" in check(guard, "Bash", {"command": command}, cwd=outside)


def test_end_of_options_keeps_dash_prefixed_path_as_target(guard):
    module, vault = guard
    (vault / "-archive").mkdir()
    assert "destructive-rm" in check(guard, "Bash", {"command": "rm -r -- -archive"})


def test_verified_write_cli_resolves_explicit_vault_forms(guard, tmp_path):
    module, vault = guard
    for command in (
        f"obsidian-knowledge write _sources/a.md --vault {vault}",
        f"obsidian-knowledge write --vault={vault} _sources/a.md",
    ):
        assert "protected-dir-bash" in check(guard, "Bash", {"command": command}, cwd=tmp_path)
    assert check(guard, "Bash", {"command": "obsidian-knowledge write --replace"}) is None
    assert "protected-dir-bash" in check(
        guard,
        "Bash",
        {"command": "obsidian-knowledge write _sources/fallback.md"},
        cwd=tmp_path,
    )


def test_published_file_edit_requires_valid_published_frontmatter(guard, monkeypatch):
    module, vault = guard
    note = vault / "note.md"
    for content in ("body", "---\ntitle: open", "---\ndg-publish: false\n---\n"):
        note.write_text(content)
        assert check(guard, "Edit", {"file_path": str(note), "new_string": "change"}) is None
    note.write_text("---\ndg-publish: true\n---\nbody")
    assert "BLOCKED [published-file]" in check(
        guard, "Edit", {"file_path": str(note), "new_string": "change"}
    )

    real_open = open

    def unreadable(path, *args, **kwargs):
        if str(path) == str(note):
            raise OSError("unreadable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setitem(module.block_published_file_edits.__globals__, "open", unreadable)
    assert module.block_published_file_edits("Edit", {"file_path": str(note), "new_string": "change"}) is None


def test_published_file_rule_ignores_missing_outside_and_nonexistent_paths(guard, tmp_path):
    module, vault = guard
    assert module.block_published_file_edits("Edit", {}) is None
    assert module.block_published_file_edits("Edit", {"file_path": str(tmp_path / "outside.md")}) is None
    assert module.block_published_file_edits("Edit", {"file_path": str(vault / "missing.md")}) is None


def test_ai_readonly_policy_covers_folder_root_file_and_bash(guard, monkeypatch):
    module, vault = guard
    policy = {"ai_readonly_folders": ["public"], "ai_readonly_root_files": ["README.md"]}
    monkeypatch.setattr(module, "load_vault_policy", lambda root: policy)
    assert "BLOCKED [ai-readonly]" in check(guard, "Write", {"file_path": "public/note.md"})
    assert "BLOCKED [ai-readonly]" in check(guard, "Edit", {"file_path": "README.md"})
    assert "BLOCKED [ai-readonly-bash]" in check(guard, "Bash", {"command": "rm public/note.md"})
    assert check(guard, "Write", {"file_path": "private/note.md"}) is None


@pytest.mark.parametrize(
    ("allowed", "path"),
    [("public", "public"), ("public/", "public/note.md"), ("public/note.md", "public/note.md")],
)
def test_publish_allowlist_accepts_exact_files_and_folders(guard, monkeypatch, allowed, path):
    module, vault = guard
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {"publish_allowlist": [allowed]})
    assert (
        check(
            guard,
            "Write",
            {"file_path": path, "content": "---\ndg-publish: true\n---\n"},
        )
        is None
    )


def test_publish_guard_blocks_outside_allowlist_without_escape_hint(guard, monkeypatch):
    module, vault = guard
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {"publish_allowlist": ["public/"]})
    reason = check(
        guard,
        "Write",
        {"file_path": "private/note.md", "content": "---\ndg-publish: true\n---\n"},
    )
    assert "BLOCKED [publish-guard]" in reason
    assert "DO NOT bypass" not in reason


def test_publish_guard_ignores_non_enabling_or_unconfigured_updates(guard, monkeypatch, tmp_path):
    module, vault = guard
    assert check(guard, "Write", {"file_path": "note.md", "content": "dg-publish: false"}) is None
    assert module.publish_guard("Write", {"content": "dg-publish: true"}) is None
    assert (
        module.publish_guard(
            "Write",
            {"file_path": str(tmp_path / "outside.md"), "content": "dg-publish: true"},
        )
        is None
    )
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {})
    assert check(guard, "Write", {"file_path": "note.md", "content": "dg-publish: true"}) is None
    monkeypatch.setattr(
        module, "load_vault_policy", lambda root: {"publish_allowlist": ["other.md", "note.md"]}
    )
    assert check(guard, "Write", {"file_path": "note.md", "content": "dg-publish: true"}) is None


def test_generic_filename_policy_blocks_new_case_insensitive_match(guard, monkeypatch):
    module, vault = guard
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {"generic_filenames": ["notes.md"]})
    assert "BLOCKED [generic-filename]" in check(guard, "Write", {"file_path": "wiki/Notes.md"})
    assert check(guard, "Write", {"file_path": "wiki/specific.md"}) is None
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {"generic_filenames": ["index.md"]})
    assert check(guard, "Write", {"file_path": "wiki/index.md"}) is None


def test_creation_policy_rules_ignore_missing_paths(guard):
    module, vault = guard
    assert module.ai_readonly_file("Write", {}) is None
    assert module.generic_filename_guard("Write", {}) is None
    assert module.illegal_filename_guard("Write", {}) is None


def test_filename_character_policy_suggests_sync_safe_name(guard, monkeypatch):
    module, vault = guard
    monkeypatch.setattr(module, "load_vault_policy", lambda root: {"illegal_filename_chars": [":", "?"]})
    reason = check(guard, "Write", {"file_path": "wiki/bad:name?.md"})
    assert "BLOCKED [illegal-filename]" in reason
    assert "bad-name-.md" in reason
    assert check(guard, "Write", {"file_path": "wiki/good-name.md"}) is None


def test_existing_policy_controlled_file_is_not_treated_as_creation(guard, monkeypatch):
    module, vault = guard
    note = vault / "wiki" / "notes.md"
    note.parent.mkdir()
    note.write_text("existing")
    policy = {"generic_filenames": ["notes.md"], "illegal_filename_chars": [":"]}
    monkeypatch.setattr(module, "load_vault_policy", lambda root: policy)
    assert check(guard, "Write", {"file_path": str(note)}) is None


def test_memory_redirect_explains_missing_vault_configuration(guard, monkeypatch, tmp_path):
    module, vault = guard
    monkeypatch.setattr(module, "VAULT_ROOTS", [])
    target = tmp_path / ".claude/projects/repo/memory/reference_fact.md"
    reason = module.check_tool_call("Write", {"file_path": str(target)}, workdir=str(tmp_path))
    assert "no vaults configured" in reason


def test_memory_redirect_lists_each_configured_vault(guard, monkeypatch, tmp_path):
    module, vault = guard
    second = tmp_path / "second-vault"
    monkeypatch.setattr(module, "VAULT_ROOTS", [str(vault), str(second)])
    target = tmp_path / ".claude/projects/repo/memory/project_fact.md"
    reason = module.check_tool_call("Write", {"file_path": str(target)}, workdir=str(tmp_path))
    assert "one of these" in reason
    assert str(vault) in reason
    assert str(second) in reason


def test_escape_hatch_skips_bash_rules_but_plain_command_does_not(guard):
    assert check(guard, "Bash", {"command": "I_AM_BEING_CAREFUL=1 rm -rf wiki"}) is None
    assert "destructive-rm" in check(guard, "Bash", {"command": "rm -rf wiki"})


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /tmp/outside",
        "find /tmp -delete",
        "rsync --delete /tmp/source/ /tmp/destination/",
        "shred /tmp/outside.md",
        "printf data | xargs rm",
        "printf data | xargs -n 2",
    ],
)
def test_destructive_commands_outside_vault_are_not_blocked(guard, tmp_path, command):
    assert check(guard, "Bash", {"command": command}, cwd=tmp_path) is None


def test_invalid_json_hook_payload_fails_open(tmp_path, subprocess_vault):
    vault, env = subprocess_vault
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks/protect-vault.py")],
        input="{",
        capture_output=True,
        text=True,
        cwd=vault,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout == ""
