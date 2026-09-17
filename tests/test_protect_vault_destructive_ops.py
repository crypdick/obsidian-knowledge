"""Regression tests for destructive-command detection at shell command boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _run_hook(command: str, vault: Path, env: dict[str, str], rule: str = "destructive-ops") -> bool:
    result = subprocess.run(
        [sys.executable, str(ROOT / "hooks/i_insist.py"), rule],
        input=json.dumps({"kind": "shell", "cwd": str(vault), "command": command, "changes": []}),
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
