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

# Vault discovery is shared with the Stop hooks via lib/vault_config.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.vault_config import is_in_vault, load_vault_roots  # noqa: E402

ESCAPE_HATCH = "I_AM_BEING_CAREFUL=1"
PROTECTED_DIRS = ["_sources"]

VAULT_ROOTS = load_vault_roots()


def command_touches_vault(command: str) -> bool:
    """Return True if the command operates on or from within a vault."""
    if is_in_vault(os.getcwd(), VAULT_ROOTS):
        return True
    return any(
        is_in_vault(token, VAULT_ROOTS)
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
    if is_in_vault(file_path, VAULT_ROOTS):
        dirs = ", ".join(PROTECTED_DIRS)
        return deny(
            "protected-dir",
            f"Cannot modify files in protected directories ({dirs}). These contain irreplaceable originals.",
            f"To modify, use Bash with {ESCAPE_HATCH} after user confirms.",
        )
    return None


def _bash_write_targets(command: str) -> list:
    """Return paths targeted by destructive operations in a bash command.

    Walks each write operation (redirect, rm/mv/etc., sed -i) and collects
    the actual *target* paths. Avoids the old "any write pattern + zone
    name anywhere in command" trap that false-positived on benign cases
    like `ls _sources/ 2>/dev/null && rm /tmp/x` (rm targets /tmp, not
    _sources, but both tokens were present).
    """
    targets: list = []

    # Stdout/stderr redirects: > target, >> target. Skip /dev/null.
    # Lookbehind avoids matching `<<` heredocs and `2>&1`.
    for m in re.finditer(r'(?<![<>&])>>?\s*(\S+)', command):
        target = m.group(1)
        if target != '/dev/null':
            targets.append(target)

    # Destructive commands: collect non-flag args until next |;& or EOL.
    destructive_cmd = r'\b(?:rm|mv|rmdir|unlink|truncate|shred|chmod|chown)\b'
    for m in re.finditer(rf'{destructive_cmd}([^|;&]*)', command):
        for tok in m.group(1).split():
            if not tok.startswith('-'):
                targets.append(tok)

    # sed -i (in-place edit): file args after -i.
    for m in re.finditer(r'\bsed\b[^|;&]*\s-i\b([^|;&]*)', command):
        for tok in m.group(1).split():
            if tok.startswith(('-', "'", '"')):
                continue
            targets.append(tok)

    return targets


def protected_dirs_bash(tool_name: str, tool_input: dict) -> str | None:
    """Block Bash write operations targeting _sources/ paths."""
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")

    for target in _bash_write_targets(command):
        if path_hits_protected_dir(target):
            dirs = ", ".join(PROTECTED_DIRS)
            return deny(
                "protected-dir-bash",
                f"Bash command would modify files in a protected directory ({dirs}). These contain irreplaceable originals.",
            )

    # Safety net: catch `cd /path/_sources && rm foo` — relative-path
    # destructive ops after entering a protected dir. Target-based parsing
    # alone misses this because `foo` doesn't contain `_sources`. Since
    # _sources/ holds irreplaceable originals, defense-in-depth is worth
    # the occasional friction.
    has_destructive = bool(re.search(
        r'\b(?:rm|mv|rmdir|unlink|truncate|shred|chmod|chown|sed\s+-i)\b',
        command,
    ))
    if has_destructive:
        for m in re.finditer(r'\bcd\s+(\S+)', command):
            if path_hits_protected_dir(m.group(1)):
                dirs = ", ".join(PROTECTED_DIRS)
                return deny(
                    "protected-dir-bash",
                    f"Bash command appears to cd into a protected directory ({dirs}) before a destructive op. "
                    "Refusing on the side of caution.",
                )
    return None


def block_published_file_edits(tool_name: str, tool_input: dict) -> str | None:
    """Block edits to vault files marked dg-publish: true without user confirmation."""
    if tool_name not in ("Write", "Edit"):
        return None
    file_path = tool_input.get("file_path", "")
    if not file_path or not is_in_vault(file_path, VAULT_ROOTS):
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
    """Block recursive rm/mv when the *target* is a vault path (absolute,
    or relative when cwd is inside a vault).

    Old implementation fired whenever `mv` or recursive `rm` appeared in
    a command and the command "touched the vault" (cwd in vault, or any
    `/`-prefixed token in vault). That produced false positives like
    `git status && mv /tmp/a /tmp/b` from inside a vault directory: the
    mv has nothing to do with the vault, but the rule blocked because
    cwd was a vault root.
    """
    if tool_name != "Bash":
        return None
    command = tool_input.get("command", "")
    cwd = os.getcwd()
    cwd_in_vault = is_in_vault(cwd, VAULT_ROOTS)

    def target_in_vault(token: str) -> bool:
        if token.startswith(("/", "~")):
            return is_in_vault(token, VAULT_ROOTS)
        # Relative paths are vault paths only if cwd is in a vault.
        return cwd_in_vault

    # Walk each rm and mv invocation in its own segment.
    for m in re.finditer(r'\b(rm|mv)\b([^|;&]*)', command):
        cmd = m.group(1)
        tokens = m.group(2).split()
        flags = [t for t in tokens if t.startswith("-")]
        paths = [t for t in tokens if not t.startswith("-")]

        if cmd == "rm":
            # Only flag recursive removes (the dangerous variant).
            if not any(re.search(r"[rR]", f) for f in flags):
                continue
            for p in paths:
                if target_in_vault(p):
                    return deny(
                        "destructive-rm",
                        "Recursive rm on a path that appears to be in an Obsidian vault.",
                    )

        if cmd == "mv":
            for p in paths:
                if target_in_vault(p):
                    return deny(
                        "destructive-mv",
                        "mv on a path that appears to be in an Obsidian vault. "
                        "Use the Obsidian CLI for moves to preserve internal links.",
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
