"""Automatic repair is independent of searches and reaped during shutdown."""

import asyncio
import json
import sys
from functools import partial
from unittest.mock import AsyncMock

import httpx
import pytest

from lib.vault_index.mcp_recovery import IndexRecovery
from lib.vault_index.mcp_server import create_http_app, create_server, rebuild_index, run_index_command
from lib.vault_index.models import SearchReport


def test_recovery_coalesces_requests_and_cancels_at_shutdown():
    async def exercise():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def rebuild():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        recovery = IndexRecovery(rebuild)
        recovery.request()
        first = recovery.task
        await started.wait()
        recovery.request()
        assert recovery.task is first
        await recovery.close()
        assert cancelled.is_set()
        recovery.request()
        assert recovery.task is first  # shutdown/retry cooldown

    asyncio.run(exercise())


@pytest.mark.parametrize("error", [ValueError("failed"), OSError("unavailable"), TimeoutError()])
def test_recovery_failure_is_reported_and_can_be_retried(error, caplog):
    async def exercise():
        rebuild = AsyncMock(side_effect=error)
        recovery = IndexRecovery(rebuild)
        recovery.request()
        await recovery.task
        recovery.request()
        assert rebuild.await_count == 1
        recovery.retry_at = 0
        rebuild.side_effect = None
        recovery.request()
        await recovery.task
        assert rebuild.await_count == 2
        await recovery.close()

    asyncio.run(exercise())
    assert "Background vector index repair failed" in caplog.text


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
        recovery = IndexRecovery(partial(rebuild_index, tmp_path))
        server = create_server(tmp_path, recovery=recovery)
        try:
            result = await server.call_tool("vault_search", {"query": "orchid"})
            assert result[1]["mode"] == "keyword"
            expected = reason if reason == "offline" else "vector index rebuilding"
            assert result[1]["degraded_reason"] == expected
            await asyncio.sleep(0)
        finally:
            await recovery.close()
        if reason == "offline":
            assert len(calls) == 1
        else:
            assert len(calls) == 2
            assert calls[1][1] == "background index repair"
            assert calls[1][2]["deadline_seconds"] == 1810
            assert "1800" in calls[1][0]

    asyncio.run(exercise())


def test_close_before_any_recovery_is_safe():
    asyncio.run(IndexRecovery(AsyncMock()).close())


def test_background_deadline_accepts_integer_seconds_with_real_subprocess():
    result = asyncio.run(
        run_index_command([sys.executable, "-c", "print('ready')"], "repair", deadline_seconds=5)
    )
    assert result == (b"ready\n", b"")


def test_search_during_retry_cooldown_keeps_original_degraded_reason():
    async def exercise():
        recovery = IndexRecovery(AsyncMock())
        report = SearchReport(mode="keyword", degraded_reason="vector index requires reindex", hits=[])
        assert recovery.repair_if_needed(report).degraded_reason == "vector index rebuilding"
        await recovery.task
        assert recovery.repair_if_needed(report) is report
        await recovery.close()

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
                        == "vector index rebuilding"
                    )
                    await asyncio.wait_for(started.wait(), 1)
                    assert not cancelled.is_set()
        assert len(jobs) == 1
        assert cancelled.is_set()

    asyncio.run(exercise())
