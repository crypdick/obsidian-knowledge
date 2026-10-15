"""Mutation serialization survives cancellation of an MCP request."""

import asyncio
import threading

import pytest

from lib.vault_index import mcp_server


def test_cancelled_write_finishes_before_next_patch(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    real_write = mcp_server.write_vault_file

    def blocked_write(*args, **kwargs):
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release write")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(mcp_server, "write_vault_file", blocked_write)
    target = tmp_path / "note.md"
    target.write_bytes(b"initial")

    async def exercise():
        server = mcp_server.create_server(tmp_path)
        first = asyncio.create_task(
            server.call_tool("vault_write", {"path": "note.md", "content": "first", "replace": True})
        )
        second = None
        try:
            assert await asyncio.to_thread(started.wait, 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(
                server.call_tool("vault_patch", {"path": "note.md", "old_str": "first", "new_str": "second"})
            )
            # The worker from the cancelled request remains blocked. A later
            # mutation must wait for that worker, rather than observe old bytes.
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(second), timeout=0.1)
            release.set()
            result = await asyncio.wait_for(second, timeout=2)
            assert result[1]["status"] == "patched and verified"
            assert target.read_bytes() == b"second"
        finally:
            release.set()
            await asyncio.gather(first, *([second] if second is not None else []), return_exceptions=True)

    asyncio.run(exercise())
