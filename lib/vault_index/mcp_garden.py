"""Expose fixed, vault-bound gardener workflows without accepting CLI arguments."""

from __future__ import annotations

import asyncio
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
from lib.vault_index.native_vault import run_vault_mutation
from lib.vault_index.search_budget import search_ttl_seconds


class GardenReport(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


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
                    deadline_seconds=max(1, search_ttl_seconds()) + 10,
                )
            return GardenReport(exit_code=code, stdout=stdout.decode(), stderr=stderr.decode())

        if apply:
            return await asyncio.to_thread(run_vault_mutation, file_lock, lambda: asyncio.run(command()))
        return await command()

    @server.tool(annotations=readonly)
    async def vault_garden_audit() -> GardenReport:
        """Audit vault structure and conventions without writing files."""
        return await run("audit")

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
