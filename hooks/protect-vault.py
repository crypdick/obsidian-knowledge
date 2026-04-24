#!/usr/bin/env python3
"""
PreToolUse hook: protect Obsidian vault integrity.

Ships with the obsidian-knowledge plugin. Requires vault roots configured in
~/.config/obsidian-knowledge/vaults.yaml:

    vaults:
      - /path/to/your/vault

Provides:
- Read-only _sources/ directories (irreplaceable originals like tax records,
  legal filings, vital docs). Agents can read but not write.
- Guards against recursive rm/mv on vault paths, including relative paths
  when the working directory is inside a vault.
- Blocks edits to published files (dg-publish: true) without user confirmation.
- Redirects operational knowledge from agent auto-memory to the vault wiki.

Escape hatch: prefix Bash commands with I_AM_BEING_CAREFUL=1 to bypass.
Write/Edit to _sources/ has no inline bypass — use Bash with the escape hatch.
The wiki-policy rule has no escape hatch — write to the wiki instead.
"""

import json
import os
import re
import sys
from pathlib import Path

ESCAPE_HATCH = "I_AM_BEING_CAREFUL=1"
PROTECTED_DIRS = ["_sources"]
CONFIG_PATH = Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"


# ── Config ───────────────────────────────────────────────────────


def load_vault_roots() -> list[str]:
    """Load vault root paths from ~/.config/obsidian-knowledge/vaults.yaml."""
    if not CONFIG_PATH.exists():
        return []
    try:
        text = CONFIG_PATH.read_text()
    except OSError:
        return []
    roots = []
    for line in text.splitlines():
        m = re.match(r"^\s*-\s+(.+)$", line)
        if m:
            p = m.group(1).strip().strip("'\"")
            if p and not p.startswith("#"):
                roots.append(os.path.abspath(os.path.expanduser(p)))
    return roots


VAULT_ROOTS = load_vault_roots()


def is_in_vault(path: str) -> bool:
    """Return True if path is inside any configured vault root."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    return any(
        abs_path == root or abs_path.startswith(root + os.sep)
        for root in VAULT_ROOTS
    )


def command_touches_vault(command: str) -> bool:
    """Return True if the command operates on or from within a vault."""
    if is_in_vault(os.getcwd()):
        return True
    return any(
        is_in_vault(token)
        for token in command.split()
        if token.startswith(("/", "~"))
    )


# ── Helpers ──────────────────────────────────────────────────────


def deny(rule: str, message: str, hint: str = "", show_escape_hint: bool = True) -> str:
    # NOTE TO AI AGENT: You MUST NOT prepend I_AM_BEING_CAREFUL=1 yourself.
    # Show this deny message to the user and wait for them to explicitly say
    # "use the escape hatch" or "I confirm". Self-authorizing the escape hatch
    # defeats the entire purpose of this safety system.
    escape_warning = (
        f"\n\n>>> AGENT: DO NOT bypass this by prepending {ESCAPE_HATCH} yourself. <<<"
        "\n>>> Show this BLOCKED message to the user verbatim and ask them to confirm. <<<"
        "\n>>> The escape hatch exists for the HUMAN to authorize, not for you to self-authorize. <<<"
        f"\n>>> If the user confirms, re-run with {ESCAPE_HATCH} prepended. <<<"
    ) if show_escape_hint else ""
    if not hint:
        hint = ""
    return f"BLOCKED [{rule}]: {message} {hint}{escape_warning}"


def path_hits_protected_dir(path: str) -> bool:
    return any(
        f"/{d}/" in path or path.rstrip("/").endswith(f"/{d}")
        for d in PROTECTED_DIRS
    )


# ── Rules ────────────────────────────────────────────────────────


def protected_dirs_file(tool_name: str, tool_input: dict) -> str | None:
    """Block Write/Edit to _sources/ directories inside any configured vault."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not path_hits_protected_dir(file_path):
        return None
    if is_in_vault(file_path):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir",
            f"Cannot modify files in protected directories ({dirs}). These contain irreplaceable originals.",
            f"To modify, use Bash with {ESCAPE_HATCH} after user confirms.",
        )
    return None


def protected_dirs_bash(tool_name: str, tool_input: dict) -> str | None:
    """Block Bash write operations targeting _sources/ paths."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    if not any(d in command for d in PROTECTED_DIRS):
        return None
    write_patterns = [
        r"\brm\b",
        r"\bmv\b",
        r"\brmdir\b",
        r"\bunlink\b",
        r">\s*\S*_sources",
        r">>\s*\S*_sources",
        r"\bsed\b.*-i",
        r"\bchmod\b",
        r"\bchown\b",
        r"\btruncate\b",
        r"\bshred\b",
    ]
    if any(re.search(p, command) for p in write_patterns):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir-bash",
            f"Bash command would modify files in a protected directory ({dirs}). These contain irreplaceable originals.",
        )
    return None


def block_published_file_edits(tool_name: str, tool_input: dict) -> str | None:
    """Block edits to vault files marked dg-publish: true without user confirmation."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path or not is_in_vault(file_path):
        return None
    if tool_name == "Edit":
        if not os.path.isfile(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read(1000)
        except (OSError, UnicodeDecodeError):
            return None
    else:
        content = tool_input.get("content", "")
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    frontmatter = content[3:end]
    if not re.search(r"^dg-publish:\s*true", frontmatter, re.MULTILINE):
        return None
    return deny(
        "published-file",
        f"'{os.path.basename(file_path)}' is published to the website (dg-publish: true). Edits will go live.",
        f"To modify, use Bash with {ESCAPE_HATCH} after the user confirms.",
    )


def destructive_vault_ops(tool_name: str, tool_input: dict) -> str | None:
    """Block recursive rm/mv on vault paths, including via relative paths from within a vault."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    if not command_touches_vault(command):
        return None
    if re.search(r"\brm\s+.*-[a-z]*[rR]", command):
        return deny(
            "destructive-rm",
            "Recursive rm on a path that appears to be in an Obsidian vault.",
        )
    if re.search(r"\bmv\b", command):
        return deny(
            "destructive-mv",
            "mv on a path that appears to be in an Obsidian vault. Use the Obsidian CLI for moves to preserve internal links.",
        )
    return None


def block_memory_file_creation(tool_name: str, tool_input: dict) -> str | None:
    """Redirect operational knowledge from agent auto-memory to the Obsidian wiki.

    Blocks Write/Edit to feedback_*.md, project_*.md, reference_*.md in any
    ~/.claude/projects/*/memory/ directory. MEMORY.md (the pointer index) and
    user_*.md (user-profile facts) are allowed through.
    """
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not re.search(r"/\.claude/projects/[^/]+/memory/", file_path):
        return None
    basename = os.path.basename(file_path)
    blocked_prefixes = ("feedback_", "project_", "reference_")
    if not any(basename.startswith(p) for p in blocked_prefixes):
        return None
    return deny(
        "wiki-policy",
        f"Writing '{basename}' to agent auto-memory is not permitted. "
        "Auto-memory is a per-project silo — invisible to other sessions, other tools, and vault search.",
        hint=(
            "\n\nWhere to write instead:\n"
            "  - Behavioral rules (how the agent should act) → CLAUDE.md in the Obsidian vault\n"
            "  - Facts about the world (tools, gotchas, procedures, system state) → wiki/ in the vault\n"
            "  - MEMORY.md is the only file permitted here — use it only as a pointer to vault locations.\n"
            "\n(The I_AM_BEING_CAREFUL=1 escape hatch does not apply to this rule — there is no bypass.)"
        ),
        show_escape_hint=False,
    )


# ── Registry ─────────────────────────────────────────────────────

RULES = [
    protected_dirs_file,
    protected_dirs_bash,
    block_published_file_edits,
    destructive_vault_ops,
    block_memory_file_creation,
]


# ── Main ─────────────────────────────────────────────────────────


def main():
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)  # malformed input — fail open

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Global escape hatch (Bash only)
    if tool_name == "Bash" and ESCAPE_HATCH in tool_input.get("command", ""):
        sys.exit(0)

    for rule in RULES:
        reason = rule(tool_name, tool_input)
        if reason:
            json.dump(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
                sys.stdout,
            )
            return

    sys.exit(0)


if __name__ == "__main__":
    main()
