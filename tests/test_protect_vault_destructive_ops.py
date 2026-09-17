"""Regression tests for destructive-command detection at shell command boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _run_hook(
    command: str,
    vault: Path,
    env: dict[str, str],
    rule: str = "destructive-ops",
    *,
    cwd: Path | None = None,
) -> bool:
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks/i_insist.py"), rule],
        input=json.dumps({"kind": "shell", "cwd": str(cwd or vault), "command": command, "changes": []}),
        capture_output=True,
        text=True,
        cwd=vault,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "command",
    [
        "nl -ba wiki/read-only-rm-rf-audit.md wiki/other.md | wc -l",
        (
            "ssh build-host docker build -f - . <<'DOCKERFILE'\n"
            "FROM debian\n"
            "RUN rm -rf /var/lib/apt/lists/*\n"
            "DOCKERFILE"
        ),
        "trap 'rm -f \"$cookie_file\"' EXIT\ncurl --retry 2 https://example.test",
        (
            "obsidian-knowledge papercut "
            "'remote Dockerfile used rm -rf cleanup; the local vault was not a target'"
        ),
        (
            "obsidian-knowledge write wiki/note.md <<'ENDNOTE'\n"
            "The report mentions `rm -rf`, but it is literal Markdown.\n"
            "ENDNOTE"
        ),
        "mv /tmp/source.md /tmp/destination.md",
    ],
)
def test_non_destructive_command_text_is_not_blocked(
    command: str,
    subprocess_vault: tuple[Path, dict[str, str]],
) -> None:
    vault, env = subprocess_vault

    assert _run_hook(command, vault, env) is False


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf wiki",
        "mv wiki/old.md wiki/new.md",
        "find wiki -delete",
        "rsync --delete /tmp/source/ wiki/",
        "shred wiki/note.md",
        "find wiki -type f | xargs rm",
    ],
)
def test_actual_destructive_vault_commands_remain_blocked(
    command: str,
    subprocess_vault: tuple[Path, dict[str, str]],
) -> None:
    vault, env = subprocess_vault

    assert _run_hook(command, vault, env) is True


def test_verified_cli_write_still_honors_protected_directories(
    subprocess_vault: tuple[Path, dict[str, str]],
) -> None:
    vault, env = subprocess_vault

    assert (
        _run_hook(
            "obsidian-knowledge write _sources/original.md <<'ENDNOTE'\nblocked\nENDNOTE",
            vault,
            env,
            "protected-dirs",
        )
        is True
    )


@pytest.mark.parametrize(
    ("command", "blocked"),
    [
        ("'unterminated", False),
        ("; ;", False),
        ("rm wiki", False),
        ("rm -r /tmp/outside", False),
        ("find wiki -name '*.md'", False),
        ("rsync /tmp/source/ wiki/", False),
        ("shred /tmp/outside", False),
        ("env -i FOO=x command --", False),
        ("sudo -u", False),
        ("obsidian-knowledge write --replace", False),
        ("mv '\"ignored' /tmp/outside", False),
        ("FOO=x env -i BAR=y command -- nohup sudo -u root rm -r wiki", True),
        ("find wiki -delete", True),
        ("find wiki -exec /bin/rm {} ';'", True),
        ("find -delete", True),
        ("mv -- wiki/old wiki/new", True),
        ("rsync --delete-excluded /tmp/source/ wiki/", True),
    ],
)
def test_shell_guard_wrapper_flag_and_command_variants(subprocess_vault, command, blocked):
    vault, env = subprocess_vault
    assert _run_hook(command, vault, env) is blocked


@pytest.mark.parametrize(
    "command",
    [
        "printf data > _sources/note.md",
        "chmod 600 _sources/note.md",
        "sed -i s/a/b/ _sources/note.md",
        "cd _sources; truncate -s 0 note.md",
        "obsidian-knowledge write --vault . _sources/note.md",
        "obsidian-knowledge write _sources/note.md --vault=.",
    ],
)
def test_shell_write_variants_protect_sources(subprocess_vault, command):
    vault, env = subprocess_vault
    assert _run_hook(command, vault, env, "protected-dirs") is True


def test_xargs_upstream_absolute_vault_path_is_blocked_outside_vault(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    command = f"find {vault / 'wiki'} -type f | xargs -n 1 rm"
    assert _run_hook(command, vault, env, cwd=tmp_path) is True


def test_xargs_rm_without_upstream_is_allowed_outside_vault(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    assert _run_hook("xargs rm", vault, env, cwd=tmp_path) is False


def test_cli_write_outside_vault_defaults_to_registered_vault(subprocess_vault, tmp_path):
    vault, env = subprocess_vault
    assert (
        _run_hook(
            "obsidian-knowledge write _sources/note.md",
            vault,
            env,
            "protected-dirs",
            cwd=tmp_path,
        )
        is True
    )


def test_cli_write_without_target_is_allowed(subprocess_vault):
    vault, env = subprocess_vault
    assert _run_hook("obsidian-knowledge write --replace", vault, env, "protected-dirs") is False


def test_readonly_shell_target_outside_vault_is_allowed(subprocess_vault):
    vault, env = subprocess_vault
    assert _run_hook("chmod 600 /tmp/outside", vault, env, "ai-readonly") is False


@pytest.mark.parametrize("command", ["printf x | xargs -- echo", "printf x | xargs -n 1"])
def test_xargs_without_rm_is_allowed(subprocess_vault, command):
    vault, env = subprocess_vault
    assert _run_hook(command, vault, env) is False
