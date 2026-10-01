"""MCP public tool and HTTP contracts."""

import asyncio
import subprocess
import sys

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from lib.vault_index import mcp_server
from lib.vault_index.mcp_server import BearerAuth, create_server, main


def test_tools_and_verified_write(tmp_path):
    async def exercise():
        server = create_server(tmp_path)
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {"vault_search", "vault_read", "vault_write"}
        result = await server.call_tool("vault_write", {"path": "wiki/note.md", "content": "# Orchid\n"})
        assert (tmp_path / "wiki/note.md").read_text() == "# Orchid\n"
        result = await server.call_tool("vault_read", {"path": "wiki/note.md"})
        assert result[0][0].text == "# Orchid\n"

    asyncio.run(exercise())


@pytest.mark.parametrize("path", ["../outside.md", "/tmp/outside.md"])
def test_path_escape_rejected(tmp_path, path):
    async def exercise():
        server = create_server(tmp_path)
        for name, arguments in [
            ("vault_read", {"path": path}),
            ("vault_write", {"path": path, "content": "Forbidden"}),
        ]:
            with pytest.raises(ToolError, match="vault"):
                await server.call_tool(name, arguments)

    asyncio.run(exercise())


def test_overwrite_and_blank_content(tmp_path):
    async def exercise():
        server = create_server(tmp_path)
        await server.call_tool("vault_write", {"path": "note.md", "content": "Original"})
        with pytest.raises(ToolError, match="already exists"):
            await server.call_tool("vault_write", {"path": "note.md", "content": "Replacement"})
        with pytest.raises(ToolError, match="empty"):
            await server.call_tool("vault_write", {"path": "note.md", "content": " "})
        assert (tmp_path / "note.md").read_text() == "Original"
        await server.call_tool("vault_write", {"path": "note.md", "content": "Replacement", "replace": True})
        assert (tmp_path / "note.md").read_text() == "Replacement"

    asyncio.run(exercise())


def test_search_real_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "offline")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("# Orchid\nPurple orchids in greenhouse")

    subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "reindex", "--vault", str(tmp_path)],
        check=True,
        capture_output=True,
        timeout=20,
    )

    async def exercise():
        server = create_server(tmp_path)
        for arguments in [{"query": "greenhouse"}, {"query": "greenhouse", "top_k": 1, "all_paths": True}]:
            result = await server.call_tool("vault_search", arguments)
            assert result[1]["mode"] == "keyword"
            assert result[1]["hits"][0]["path"] == "wiki/orchid.md"
        literal = await server.call_tool("vault_search", {"query": "--help"})
        assert literal[1]["hits"] == []
        for arguments in [{"query": ""}, {"query": "orchid", "top_k": 0}]:
            with pytest.raises(ToolError):
                await server.call_tool("vault_search", arguments)

    asyncio.run(exercise())


def test_http_protocol_and_auth(tmp_path):
    app = create_server(tmp_path).streamable_http_app()
    access = "test-access"
    app.add_middleware(BearerAuth, token=access)
    with TestClient(app, base_url="http://localhost:8000") as client:
        headers = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer test-access"}
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        assert client.post("/mcp", json=message).status_code == 401
        assert (
            client.post(
                "/mcp", json=message, headers={**headers, "Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        response = client.post("/mcp", json=message, headers=headers)
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "obsidian-knowledge"
        response = client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers
        )
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
            "vault_read",
            "vault_write",
            "vault_search",
        }
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "vault_write", "arguments": {"path": "note.md", "content": "From HTTP"}},
            },
            headers=headers,
        )
        assert response.json()["result"]["structuredContent"]["status"] == "wrote and verified"
        assert (tmp_path / "note.md").read_text() == "From HTTP"
        assert (
            client.post("/mcp", json=message, headers={**headers, "Host": "evil.example"}).status_code == 421
        )
        assert (
            client.post(
                "/mcp", json=message, headers={**headers, "Origin": "http://evil.example"}
            ).status_code
            == 403
        )


def test_vault_must_be_directory(tmp_path):
    file = tmp_path / "file"
    file.touch()
    with pytest.raises(ValueError, match="directory"):
        create_server(file)


@pytest.mark.parametrize("token", ["", "test-access"])
def test_command_startup(tmp_path, monkeypatch, token):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_MCP_TOKEN", token)
    monkeypatch.setattr(
        "sys.argv",
        [
            "obsidian-knowledge-mcp",
            "--vault",
            str(tmp_path),
            "--port",
            "8100",
            "--allowed-host",
            "vault-server:*",
        ],
    )
    calls = []
    monkeypatch.setattr(mcp_server.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    main()
    assert calls[0][1] == {"host": "127.0.0.1", "port": 8100}
    assert bool(calls[0][0].user_middleware) is bool(token)


def test_invalid_port(monkeypatch):
    monkeypatch.setattr("sys.argv", ["obsidian-knowledge-mcp", "--port", "65536"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


@pytest.mark.parametrize("outcome", ["timeout", "cancel", "failure"])
def test_search_failure_and_process_cleanup(tmp_path, monkeypatch, outcome):
    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            if outcome == "timeout":
                raise TimeoutError
            if outcome == "cancel":
                raise asyncio.CancelledError
            self.returncode = 2
            return b"", b"index unavailable"

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True
            self.returncode = -9

    process = Process()

    async def spawn(*args, **kwargs):
        return process

    monkeypatch.setattr(mcp_server.asyncio, "create_subprocess_exec", spawn)

    async def exercise():
        server = create_server(tmp_path)
        if outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await server.call_tool("vault_search", {"query": "orchid"})
        else:
            with pytest.raises(ToolError):
                await server.call_tool("vault_search", {"query": "orchid"})
        assert process.killed == (outcome != "failure")
        assert process.waited == (outcome != "failure")

    asyncio.run(exercise())


def test_sdk_streamable_http_client(tmp_path):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def exercise():
        app = create_server(tmp_path).streamable_http_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                async with streamable_http_client("http://localhost:8000/mcp", http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as client:
                        initialized = await client.initialize()
                        assert initialized.serverInfo.name == "obsidian-knowledge"
                        tools = await client.list_tools()
                        assert len(tools.tools) == 3
                        written = await client.call_tool(
                            "vault_write", {"path": "sdk.md", "content": "SDK text"}
                        )
                        assert written.isError is False
                        read_result = await client.call_tool("vault_read", {"path": "sdk.md"})
                        assert read_result.content[0].text == "SDK text"
                        rejected = await client.call_tool(
                            "vault_write", {"path": "sdk.md", "content": "Overwrite"}
                        )
                        assert rejected.isError is True

    asyncio.run(exercise())
