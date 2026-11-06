"""Search requests never launch or own indexing jobs."""

import asyncio
import json

import httpx
import pytest

from lib.vault_index.mcp_server import create_http_app, create_server


@pytest.mark.parametrize("reason", ["vector index requires reindex", "vector index unavailable", "offline"])
def test_mcp_search_starts_independent_background_repair(tmp_path, monkeypatch, reason):
    calls = []

    async def run(command, operation, **kwargs):
        calls.append((command, operation, kwargs))
        if operation == "search":
            return json.dumps({"mode": "keyword", "degraded_reason": reason, "hits": []}).encode(), b""
        return b"Indexed: 1, Skipped: 0, Deleted: 0\n", b""

    monkeypatch.setattr("lib.vault_index.mcp_server.run_index_command", run)

    async def exercise():
        server = create_server(tmp_path)
        result = await server.call_tool("vault_search", {"query": "orchid"})
        assert result[1]["mode"] == "keyword"
        expected = reason
        assert result[1]["degraded_reason"] == expected
        await asyncio.sleep(0)
        assert len(calls) == 1

    asyncio.run(exercise())


def test_stateless_http_requests_do_not_cancel_or_duplicate_repair(tmp_path, monkeypatch):
    async def exercise():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        jobs = []

        async def run(command, operation, **kwargs):
            if operation == "search":
                return b'{"mode":"keyword","degraded_reason":"vector index requires reindex","hits":[]}', b""
            jobs.append(command)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr("lib.vault_index.mcp_server.run_index_command", run)
        app = create_http_app(tmp_path)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                for message_id in (1, 2):
                    response = await http.post(
                        "http://localhost:8000/mcp",
                        headers={"Accept": "application/json, text/event-stream"},
                        json={
                            "jsonrpc": "2.0",
                            "id": message_id,
                            "method": "tools/call",
                            "params": {"name": "vault_search", "arguments": {"query": "orchid"}},
                        },
                    )
                    assert (
                        response.json()["result"]["structuredContent"]["degraded_reason"]
                        == "vector index requires reindex"
                    )
                    assert not cancelled.is_set()
        assert jobs == []
        assert not cancelled.is_set()

    asyncio.run(exercise())
