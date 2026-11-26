"""Expose fixed, vault-bound gardener workflows without accepting CLI arguments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import tempfile
from _thread import LockType
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from lib.vault_index.bounded_process import collect_bounded_output
from lib.vault_index.native_vault import restricted_vault_path, run_vault_mutation
from lib.vault_index.obsidian_cli import NativeObsidian
from lib.vault_index.search_budget import search_ttl_seconds

# A full-vault audit walks files; its deadline is independent of search.
AUDIT_DEADLINE_SECONDS = 120


class GardenReport(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


def _page[T](items: list[T], offset: int, limit: int, snapshot: str) -> dict[str, Any]:
    identity = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    if (offset and not snapshot) or (snapshot and identity != snapshot):
        raise ValueError("missing or changed snapshot; restart at offset 0")
    if offset > len(items):
        raise ValueError("offset exceeds report size")
    end = offset + limit
    return {
        "snapshot": identity,
        "offset": offset,
        "total": len(items),
        "next_offset": end if end < len(items) else None,
        "items": items[offset:end],
    }


class UnresolvedTarget(BaseModel):
    link: str
    count: int
    sources: str


def register_garden_tools(server: FastMCP, vault: Path, file_lock: LockType) -> None:
    """Reuse the installed gardener's validation, policy, and output."""
    readonly = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    repair = ToolAnnotations(destructiveHint=True, openWorldHint=False)

    async def run(operation: str, *arguments: str, data: object = None, apply: bool = False) -> GardenReport:
        async def command() -> GardenReport:
            flags = ["--apply"] if apply else []
            # A file avoids a blocked stdin pipe when output is oversized or the child exits early.
            with tempfile.TemporaryFile() as payload:
                if data is not None:
                    payload.write(json.dumps(data, allow_nan=False).encode())
                    payload.seek(0)
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "gardener.cli",
                    operation,
                    "--vault",
                    str(vault),
                    *flags,
                    *arguments,
                    stdin=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                stdout, stderr, code = await collect_bounded_output(
                    process,
                    label=f"garden {operation}",
                    max_bytes=6 * 1024 * 1024,
                    deadline_seconds=AUDIT_DEADLINE_SECONDS
                    if operation == "audit"
                    else max(1, search_ttl_seconds()) + 10,
                )
            return GardenReport(exit_code=code, stdout=stdout.decode(), stderr=stderr.decode())

        if apply:
            return await asyncio.to_thread(run_vault_mutation, file_lock, lambda: asyncio.run(command()))
        return await command()

    @server.tool(annotations=readonly)
    async def vault_garden_audit() -> GardenReport:
        """Audit vault structure and conventions without writing files."""
        return await run("audit")

    @server.tool(annotations=readonly)
    async def vault_garden_audit_page(
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
        snapshot: str = "",
    ) -> dict[str, Any]:
        """Page the combined structural and convention audit using a snapshot ID."""
        report = await vault_garden_audit()
        if report.exit_code:
            raise ValueError(report.stderr or "gardener audit failed")
        return _page(report.stdout.splitlines(), offset, limit, snapshot)

    @server.tool(annotations=repair)
    async def vault_garden_links(
        unresolved: list[dict[str, Any]],
        include_stubs: bool = False,
        output_format: Literal["tsv", "json"] = "tsv",
        apply: bool = False,
    ) -> GardenReport:
        """Classify unresolved links; apply only unique recoveries when requested."""
        arguments = [f"--format={output_format}"]
        if include_stubs:
            arguments.append("--include-stubs")
        return await run("links", *arguments, data=unresolved, apply=apply)

    @server.tool(annotations=repair)
    async def vault_garden_index(path: str, review: dict[str, Any], apply: bool = False) -> GardenReport:
        """Preview or apply reviewed entries to one managed index.md."""
        return await run("index", "--", path, data=review, apply=apply)

    @server.tool(annotations=repair)
    async def vault_garden_questions(
        report: bool = False, timestamp: str | None = None, apply: bool = False
    ) -> GardenReport:
        """List question callouts or preview/regenerate the standard report."""
        arguments = ["--report"] if report else []
        if timestamp is not None:
            arguments.append(f"--timestamp={timestamp}")
        return await run("questions", *arguments, apply=apply)

    @server.tool(annotations=readonly)
    async def vault_garden_frontmatter(paths: Annotated[list[str], Field(min_length=1)]) -> GardenReport:
        """Report ambiguous stacked frontmatter; never remove markers."""
        return await run("frontmatter", "--", *paths)


def register_garden_native_tools(server: FastMCP, vault: Path, file_lock: LockType) -> None:
    """Expose bounded link diagnostics and native organizer actions."""
    readonly = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    repair = ToolAnnotations(destructiveHint=True, openWorldHint=False)
    native = NativeObsidian(vault)

    @server.tool(annotations=readonly)
    async def vault_garden_unresolved(
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=20)] = 20,
        link_contains: str = "",
        snapshot: str = "",
    ) -> dict[str, Any]:
        """Page native unresolved link targets. Restart if the snapshot changes."""
        raw = await native.run_json("unresolved", "verbose", "format=json")
        if not isinstance(raw, list):
            raise ValueError("unexpected native unresolved link report")
        all_items = sorted(
            (UnresolvedTarget.model_validate(item) for item in raw), key=lambda item: item.link
        )
        matching = [item.model_dump() for item in all_items if link_contains in item.link]
        page = _page(matching, offset, limit, snapshot)
        return {
            **page,
            "total_targets": len(all_items),
            "total_references": sum(item.count for item in all_items),
            "matching_targets": len(matching),
        }

    @server.tool(annotations=readonly)
    async def vault_garden_orphans() -> dict[str, str]:
        """Return native orphan evidence; filter excluded paths before maintenance."""
        return {"orphans": await native.run("orphans", "format=json")}

    @server.tool(annotations=readonly)
    async def vault_garden_backlinks(path: str) -> dict[str, str]:
        """Return native backlinks for one unprotected exact vault-relative path."""
        relative = restricted_vault_path(vault, path)
        return {"backlinks": await native.run("backlinks", f"path={relative}", "format=json")}

    @server.tool(annotations=repair)
    async def vault_garden_rename(path: str, new_name: str) -> dict[str, str]:
        """Rename a visible file through Obsidian's native link updating."""
        relative = restricted_vault_path(vault, path)
        name = restricted_vault_path(vault, new_name)
        if "/" in name:
            raise ValueError("new_name must be a filename")
        result = await asyncio.to_thread(
            run_vault_mutation,
            file_lock,
            lambda: asyncio.run(native.run("rename", f"path={relative}", f"name={name}")),
        )
        return {"result": result}

    @server.tool(annotations=repair)
    async def vault_garden_move(path: str, destination: str) -> dict[str, str]:
        """Move a visible file through Obsidian's native link updating."""
        relative = restricted_vault_path(vault, path)
        target = restricted_vault_path(vault, destination)
        result = await asyncio.to_thread(
            run_vault_mutation,
            file_lock,
            lambda: asyncio.run(native.run("move", f"path={relative}", f"to={target}")),
        )
        return {"result": result}
