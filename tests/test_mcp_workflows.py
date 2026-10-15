"""MCP editing, discovery, and index maintenance contracts."""

import asyncio
import hashlib

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from lib.vault_index.mcp_server import create_server


def test_patch_and_listing_tools(tmp_path):
    original = b"---\r\ncreated: 2026-01-01\r\n---\r\n# Orchid\r\nOld paragraph\r\n"
    (tmp_path / "note.md").write_bytes(original)

    async def exercise():
        server = create_server(tmp_path)
        patched = await server.call_tool(
            "vault_patch",
            {
                "path": "note.md",
                "old_str": "Old paragraph",
                "new_str": "New paragraph",
                "expected_sha256": hashlib.sha256(original).hexdigest(),
            },
        )
        assert patched[1] == {"path": "note.md", "status": "patched and verified"}
        assert (tmp_path / "note.md").read_bytes() == original.replace(b"Old paragraph", b"New paragraph")
        listed = await server.call_tool("vault_list", {})
        assert listed[1]["entries"][0]["path"] == "note.md"
        assert listed[1]["next_offset"] is None
        with pytest.raises(ToolError, match=r"not found|exactly once"):
            await server.call_tool("vault_patch", {"path": "note.md", "old_str": "Missing", "new_str": "New"})
        for arguments in [{"limit": 501}, {"offset": -1}, {"depth": 11}]:
            with pytest.raises(ToolError):
                await server.call_tool("vault_list", arguments)
        with pytest.raises(ToolError):
            await server.call_tool("vault_patch", {"path": "note.md", "old_str": "", "new_str": "New"})

    asyncio.run(exercise())


def test_index_update_makes_new_note_searchable(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "offline")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))

    async def exercise():
        server = create_server(tmp_path)
        before = await server.call_tool("vault_search_status", {})
        assert before[1]["index_exists"] is False
        await server.call_tool(
            "vault_write", {"path": "wiki/orchid.md", "content": "# Orchid\nPurple greenhouse orchids"}
        )
        updated = await server.call_tool("vault_search_update", {})
        assert updated[1]["status"] == "updated"
        assert updated[1]["indexed"] == 1
        after = await server.call_tool("vault_search_status", {})
        assert after[1]["index_exists"] is True
        assert after[1]["indexed_files"] == 1
        assert after[1]["vector_index_ready"] is False
        hits = await server.call_tool("vault_search", {"query": "greenhouse", "all_paths": True})
        assert hits[1]["hits"][0]["path"] == "wiki/orchid.md"
        await server.call_tool(
            "vault_patch", {"path": "wiki/orchid.md", "old_str": "greenhouse", "new_str": "conservatory"}
        )
        await server.call_tool("vault_search_update", {})
        hits = await server.call_tool("vault_search", {"query": "conservatory", "all_paths": True})
        assert hits[1]["hits"][0]["path"] == "wiki/orchid.md"

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "operation,arguments", [("vault_search", {"query": "orchid"}), ("vault_search_update", {})]
)
def test_empty_subprocess_error(tmp_path, monkeypatch, operation, arguments):
    from lib.vault_index import mcp_server

    class Process:
        returncode = 1

        async def communicate(self):
            return b"", b""

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr(mcp_server.asyncio, "create_subprocess_exec", spawn)

    async def exercise():
        with pytest.raises(ToolError, match="failed"):
            await create_server(tmp_path).call_tool(operation, arguments)

    asyncio.run(exercise())
