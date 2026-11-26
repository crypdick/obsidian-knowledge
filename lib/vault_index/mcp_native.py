"""Register shared vault operations as MCP tools."""

from __future__ import annotations

import asyncio
from _thread import LockType
from collections.abc import Awaitable, Callable
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from lib.vault_index.native_vault import NativeVault, NonemptyText, run_vault_mutation, visible_vault_path
from lib.vault_index.vault_files import append_vault_file


def register_native_tools(
    server: FastMCP, vault: Path, file_lock: LockType, refresh: Callable[[list[str]], Awaitable[str]]
) -> None:
    """Register confined append and six app-backed operations against one vault."""
    native = NativeVault(vault, file_lock, refresh)
    destructive = ToolAnnotations(destructiveHint=True, openWorldHint=False)
    readonly = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    @server.tool(annotations=destructive)
    async def vault_append(path: str, content: NonemptyText, inline: bool = False) -> dict[str, str]:
        """Append literal UTF-8 atomically without the app; inline disables the leading newline."""
        path = visible_vault_path(vault, path)
        await asyncio.to_thread(
            run_vault_mutation,
            file_lock,
            lambda: append_vault_file(vault, Path(path), content, inline=inline),
        )
        return {"path": path, "status": "appended", "index": await refresh([path])}

    server.add_tool(native.frontmatter, name="vault_frontmatter", annotations=destructive)
    server.add_tool(native.recent, name="vault_recent", annotations=readonly)
    server.add_tool(native.grep, name="vault_grep", annotations=readonly)
    server.add_tool(native.info, name="vault_info", annotations=readonly)
    server.add_tool(native.delete, name="vault_delete", annotations=destructive)
    server.add_tool(native.move, name="vault_move", annotations=destructive)
