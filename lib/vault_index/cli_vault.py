"""Local CLI adapters for shared vault operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from lib.vault_index.native_vault import NativeVault, NonemptyText, ResultLimit, visible_vault_path
from lib.vault_index.vault_files import ExpectedDigest, append_vault_file, patch_vault_file
from lib.vault_index.vault_listing import list_vault_files


def add_vault_commands(add_parser: Callable[..., argparse.ArgumentParser]) -> None:
    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        parser = add_parser(name, help=help_text)
        parser.add_argument("--vault", type=Path, help="Vault root")
        parser.set_defaults(vault_operation=True)
        return parser

    patch = command("patch", "Replace exactly one literal text match in a vault file")
    patch.add_argument("path", type=Path)
    patch.add_argument("old_str", type=TypeAdapter(NonemptyText).validate_python)
    patch.add_argument("new_str")
    patch.add_argument("--expected-sha256", type=TypeAdapter(ExpectedDigest).validate_python)

    append = command("append", "Append literal UTF-8 from stdin to an existing vault file")
    append.add_argument("path")
    append.add_argument("--inline", action="store_true", help="Do not prepend a newline")

    listing = command("list", "List visible vault files and folders as a JSON page")
    listing.add_argument("path", type=Path, nargs="?", default=Path("."))
    listing.add_argument("--recursive", action="store_true")
    listing.add_argument("--depth", type=int, default=3)
    listing.add_argument("--pattern")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)

    command("search-status", "Report persisted index readiness without probing or rebuilding")
    update = command("search-update", "Queue index maintenance without waiting for the worker")
    selection = update.add_mutually_exclusive_group()
    selection.add_argument("--force", action="store_true", help="Queue a new index generation")
    selection.add_argument("--path", action="append", dest="paths", help="Queue this path; repeatable")

    frontmatter = command("frontmatter", "Read or merge note properties through Obsidian")
    frontmatter.add_argument("path")
    frontmatter.add_argument("--updates", type=TypeAdapter(dict[str, Any]).validate_json, metavar="JSON")

    result_limit = TypeAdapter(ResultLimit).validate_python
    recent = command("recent", "List recently modified notes through Obsidian")
    recent.add_argument("--n", type=result_limit, default=10)
    recent.add_argument("--path-filter", default="")

    grep = command("grep", "Search live note content for literal text through Obsidian")
    grep.add_argument("query", type=TypeAdapter(NonemptyText).validate_python)
    grep.add_argument("--path-filter", default="")
    grep.add_argument("--max-results", type=result_limit, default=20)

    command("info", "Report vault information through Obsidian")

    delete = command("delete", "Trash a vault file through Obsidian")
    delete.add_argument("path")

    move = command("move", "Move a vault file through Obsidian, respecting its link update settings")
    move.add_argument("from_path")
    move.add_argument("to_path")
    move.add_argument("--dry-run", action="store_true")


async def _native_command(args: argparse.Namespace, vault: Path) -> dict[str, Any]:
    from lib.vault_index.mcp_index import refresh_index

    native = NativeVault(vault, threading.Lock(), partial(refresh_index, vault))
    match args.cmd:
        case "frontmatter":
            return await native.frontmatter(args.path, args.updates)
        case "recent":
            return await native.recent(args.n, args.path_filter)
        case "grep":
            return await native.grep(args.query, args.path_filter, args.max_results)
        case "info":
            return await native.info()
        case "delete":
            return await native.delete(args.path)
        case "move":
            return await native.move(args.from_path, args.to_path, args.dry_run)
    raise AssertionError(f"unexpected native command: {args.cmd}")


def _file_edit(args: argparse.Namespace, vault: Path) -> dict[str, str]:
    from lib.vault_index.mcp_index import refresh_index

    if args.cmd == "patch":
        target = patch_vault_file(
            vault, args.path, args.old_str, args.new_str, expected_sha256=args.expected_sha256
        )
        status = "patched and verified"
    else:
        path = visible_vault_path(vault, args.path)
        target = append_vault_file(
            vault, Path(path), sys.stdin.buffer.read().decode("utf-8"), inline=args.inline
        )
        status = "appended"
    path = target.relative_to(vault).as_posix()
    return {"path": path, "status": status, "index": asyncio.run(refresh_index(vault, [path]))}


def run_vault_command(args: argparse.Namespace, vault: Path) -> int:
    match args.cmd:
        case "patch" | "append":
            report = json.dumps(_file_edit(args, vault))
        case "list":
            report = list_vault_files(
                vault,
                args.path,
                recursive=args.recursive,
                depth=args.depth,
                pattern=args.pattern,
                limit=args.limit,
                offset=args.offset,
            ).model_dump_json()
        case "search-status":
            from lib.vault_index.mcp_index import read_index_status

            report = read_index_status(vault).model_dump_json()
        case "search-update":
            from lib.vault_index.index_worker import queue_index_update

            queue_index_update(vault, force=args.force, paths=args.paths)
            report = '{"status":"queued"}'
        case _:
            report = json.dumps(asyncio.run(_native_command(args, vault)))
    sys.stdout.write(report + "\n")
    return 0
