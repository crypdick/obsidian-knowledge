"""Recognized shell operations that can modify vault paths.

Shell command bodies remain opaque; this is the existing conservative command
checker, not a shell interpreter.
"""

import os
import re
import shlex
from collections.abc import Callable
from pathlib import Path

from .vault_config import is_in_vault, load_vault_roots
from .vault_policy import find_containing_vault

VAULT_ROOTS = load_vault_roots()

_HEREDOC_RE = re.compile(r"<<(?P<tabs>-)?\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)")
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_COMMAND_WRAPPERS = {"command", "exec", "nohup"}
_PRIVILEGE_WRAPPERS = {"doas", "sudo"}
_WRAPPER_VALUE_FLAGS = {"-g", "--group", "-h", "--host", "-u", "--user"}
_REDIRECTIONS = {"<", "<<", "<<<", ">", ">>", "<>", "<&", ">&"}


def _without_heredoc_bodies(command: str) -> str:
    """Remove heredoc payloads, which are data or input to another process."""
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.splitlines():
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(
            (match.group("delimiter"), match.group("tabs") == "-") for match in _HEREDOC_RE.finditer(line)
        )
    # NOTE: heredoc payloads are opaque input; use a shell AST if local
    # shell-heredoc enforcement becomes necessary.
    return "\n".join(kept)


def _shell_pipelines(command: str) -> list[list[list[str]]]:
    """Tokenize local shell commands while preserving quoted argument text."""
    lexer = shlex.shlex(
        _without_heredoc_bodies(command),
        posix=True,
        punctuation_chars="|&;<>\n",
    )
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []

    pipelines: list[list[list[str]]] = []
    pipeline: list[list[str]] = []
    simple_command: list[str] = []

    def finish_command() -> None:
        if simple_command:
            pipeline.append(simple_command.copy())
            simple_command.clear()

    def finish_pipeline() -> None:
        finish_command()
        if pipeline:
            pipelines.append(pipeline.copy())
            pipeline.clear()

    for token in tokens:
        if token == "|":
            finish_command()
        elif token in {"&", "&&", "||", ";", "\n"}:
            finish_pipeline()
        else:
            simple_command.append(token)
    finish_pipeline()
    return pipelines


def _command_parts(tokens: list[str]) -> tuple[str, list[str]]:
    """Return the executable basename and args for one simple command."""
    index = 0
    while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
        index += 1

    while index < len(tokens):
        executable = os.path.basename(tokens[index])
        if executable == "env":
            index += 1
            while index < len(tokens) and (
                tokens[index].startswith("-") or _ASSIGNMENT_RE.match(tokens[index])
            ):
                index += 1
            continue
        if executable in _COMMAND_WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        if executable in _PRIVILEGE_WRAPPERS:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                flag = tokens[index]
                index += 1
                if flag in _WRAPPER_VALUE_FLAGS and index < len(tokens):
                    index += 1
            continue
        return executable, tokens[index + 1 :]
    return "", []


def _flags_and_paths(args: list[str]) -> tuple[list[str], list[str]]:
    """Separate flags from positional paths, excluding redirection targets."""
    flags: list[str] = []
    paths: list[str] = []
    end_options = False
    index = 0
    while index < len(args):
        token = args[index]
        if token in _REDIRECTIONS:
            index += 2
            continue
        if token == "--":
            end_options = True
        elif not end_options and token.startswith("-"):
            flags.append(token)
        else:
            paths.append(token)
        index += 1
    return flags, paths


def _obsidian_knowledge_write_target(executable: str, args: list[str], cwd: str) -> str | None:
    """Resolve an `obsidian-knowledge write` path for vault shell checks."""
    if executable != "obsidian-knowledge" or not args or args[0] != "write":
        return None

    relative_path: str | None = None
    explicit_vault: str | None = None
    index = 1
    while index < len(args):
        token = args[index]
        if token == "--vault" and index + 1 < len(args):
            explicit_vault = args[index + 1]
            index += 2
            continue
        if token.startswith("--vault="):
            explicit_vault = token.split("=", 1)[1]
        elif not token.startswith("-") and relative_path is None:
            relative_path = token
        index += 1
    if relative_path is None:
        return None

    vault = (
        str((Path(cwd) / Path(explicit_vault).expanduser()).resolve())
        if explicit_vault
        else find_containing_vault(cwd, VAULT_ROOTS)
    )
    if vault is None and VAULT_ROOTS:
        vault = VAULT_ROOTS[0]
    return os.path.join(vault, relative_path) if vault else None


def write_targets(command: str, cwd: str) -> list[str]:
    """Return paths targeted by actual local write commands."""
    targets: list[str] = []
    destructive = {"chmod", "chown", "mv", "rm", "rmdir", "shred", "truncate", "unlink"}
    for pipeline in _shell_pipelines(command):
        for tokens in pipeline:
            for index, token in enumerate(tokens[:-1]):
                if token in {">", ">>"} and tokens[index + 1] != "/dev/null":
                    targets.append(tokens[index + 1])

            executable, args = _command_parts(tokens)
            flags, paths = _flags_and_paths(args)
            cli_target = _obsidian_knowledge_write_target(executable, args, cwd)
            if cli_target is not None:
                targets.append(cli_target)
            elif executable in destructive:
                targets.extend(paths)
            elif executable == "sed" and any("i" in flag.lstrip("-") for flag in flags):
                targets.extend(paths[1:])
    return [str((Path(cwd) / Path(target).expanduser()).resolve()) for target in targets]


def _check_rm_mv(executable: str, args: list[str], target_in_vault: Callable[[str], bool]) -> bool:
    """Block recursive `rm` or any `mv` whose target is a vault path."""
    if executable not in {"rm", "mv"}:
        return False
    flags, paths = _flags_and_paths(args)
    if executable == "rm":
        if not any(flag == "--recursive" or re.search("[rR]", flag.lstrip("-")) for flag in flags):
            return False
        if any(target_in_vault(path) for path in paths):
            return True
    elif any(target_in_vault(path) for path in paths):
        return True
    return False


def _check_find_delete(executable: str, args: list[str], target_in_vault: Callable[[str], bool]) -> bool:
    """Block `find -delete` / `find -exec rm` whose path arg is a vault path."""
    if executable != "find":
        return False
    has_delete = "-delete" in args
    has_exec_rm = any(
        (
            token == "-exec" and index + 1 < len(args) and (os.path.basename(args[index + 1]) == "rm")
            for index, token in enumerate(args)
        )
    )
    if not (has_delete or has_exec_rm):
        return False
    paths: list[str] = []
    for token in args:
        if token.startswith(("-", "(", ")", "!")):
            break
        paths.append(token)
    return any(target_in_vault(path) for path in paths or ["."])


def _check_rsync_delete(executable: str, args: list[str], target_in_vault: Callable[[str], bool]) -> bool:
    """Block `rsync --delete` whose destination is a vault path."""
    if executable != "rsync" or not any(flag.startswith("--delete") for flag in args):
        return False
    _flags, paths = _flags_and_paths(args)
    return bool(paths and target_in_vault(paths[-1]))


def _check_shred(executable: str, args: list[str], target_in_vault: Callable[[str], bool]) -> bool:
    """Block `shred` whose path arg is a vault path."""
    if executable != "shred":
        return False
    _flags, paths = _flags_and_paths(args)
    return any(target_in_vault(path) for path in paths)


def _xargs_executable(args: list[str]) -> str:
    """Return the executable selected by xargs, excluding its own options."""
    options_with_values = {"-E", "-I", "-L", "-P", "-S", "-a", "-d", "-n", "-s"}
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            break
        index += 2 if token in options_with_values else 1
    return os.path.basename(args[index]) if index < len(args) else ""


def _check_xargs_rm(pipeline: list[list[str]], cwd_in_vault: bool) -> bool:
    """Block `xargs rm` fed by a pipeline rooted in / referencing a vault.

    rm gets its targets from stdin, so check upstream pipe segments
    (and cwd) for vault-path references.
    """
    for index, tokens in enumerate(pipeline):
        executable, args = _command_parts(tokens)
        if executable != "xargs" or _xargs_executable(args) != "rm":
            continue
        if cwd_in_vault:
            return True
        for upstream in pipeline[:index]:
            for token in upstream:
                if token.startswith(("/", "~")) and is_in_vault(token, VAULT_ROOTS):
                    return True
    return False


def destructive_vault_ops(command: str, cwd: str) -> bool:
    """Block recognized destructive commands whose targets are in a vault."""
    cwd_in_vault = is_in_vault(cwd, VAULT_ROOTS)

    def target_in_vault(token: str) -> bool:
        if not token or token[0] in ('"', "'", "\\", "|", "&", ";", "<", ">"):
            return False
        return is_in_vault(str((Path(cwd) / Path(token).expanduser()).resolve()), VAULT_ROOTS)

    for pipeline in _shell_pipelines(command):
        for tokens in pipeline:
            executable, args = _command_parts(tokens)
            if any(
                check(executable, args, target_in_vault)
                for check in (_check_rm_mv, _check_find_delete, _check_rsync_delete, _check_shred)
            ):
                return True
        if _check_xargs_rm(pipeline, cwd_in_vault):
            return True
    return False


def enters_protected_directory(command: str) -> bool:
    """Catch destructive relative operations after cd into _sources."""
    commands = [_command_parts(tokens) for pipeline in _shell_pipelines(command) for tokens in pipeline]
    destructive = {"chmod", "chown", "mv", "rm", "rmdir", "shred", "truncate", "unlink"}
    return any(exe == "cd" and args and "_sources" in Path(args[0]).parts for exe, args in commands) and any(
        exe in destructive
        or (exe == "sed" and any("i" in arg.lstrip("-") for arg in args if arg.startswith("-")))
        for exe, args in commands
    )
