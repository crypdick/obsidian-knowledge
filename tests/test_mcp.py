"""MCP public tool and HTTP contracts."""

import asyncio
import json
import subprocess
import sys

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from lib.vault_index import mcp_garden, mcp_server
from lib.vault_index.mcp_server import BearerAuth, create_server, main
from lib.vault_index.obsidian_cli import NativeObsidian


def test_tools_and_verified_write(tmp_path):
    async def exercise():
        server = create_server(tmp_path)
        result = await server.call_tool("vault_write", {"path": "wiki/note.md", "content": "# Orchid\n"})
        assert (tmp_path / "wiki/note.md").read_text() == "# Orchid\n"
        result = await server.call_tool("vault_read", {"path": "wiki/note.md"})
        assert result[0][0].text == "# Orchid\n"

    asyncio.run(exercise())


def test_managed_tools_preserve_path_boundaries(tmp_path):
    policy = tmp_path / ".claude"
    policy.mkdir()
    (policy / "obsidian-knowledge.yaml").write_text(
        "ai_managed: [wiki]\nai_readonly_folders: [wiki/locked]\nai_readonly_root_files: [wiki/protected.md]\n"
    )
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "link.md").symlink_to(wiki / "managed.md")

    async def exercise():
        server = create_server(tmp_path)
        await server.call_tool("vault_managed_write", {"path": "wiki/managed.md", "content": "# Note"})
        result = await server.call_tool("vault_managed_read", {"path": "wiki/managed.md"})
        assert result[0][0].text == "# Note"
        for path in (
            "outside.md",
            "wiki/locked/nested/file.md",
            "wiki/AGENTS.md",
            "wiki/link.md",
            "wiki/note.txt",
            "wiki/protected.md",
        ):
            with pytest.raises(ToolError):
                await server.call_tool(
                    "vault_managed_write", {"path": path, "content": "blocked", "replace": True}
                )
        for path in (
            "wiki/link.md",
            "wiki/_sources/hidden.md",
            "wiki/back\\slash.md",
            "Utility/obsidian-knowledge/reports/archive/old.md",
        ):
            with pytest.raises(ToolError):
                await server.call_tool("vault_managed_read", {"path": path})
        assert (wiki / "managed.md").read_text() == "# Note"
        (policy / "obsidian-knowledge.yaml").unlink()
        with pytest.raises(ToolError, match="ai_managed"):
            await server.call_tool("vault_managed_write", {"path": "wiki/managed.md", "content": "blocked"})

    asyncio.run(exercise())


def test_shared_gardener_diagnostics_and_native_actions(tmp_path, monkeypatch):
    native_calls = []
    targets = [
        {"link": "B", "count": "2", "sources": "wiki/b.md"},
        {"link": "A", "count": "1", "sources": "wiki/a.md"},
    ]

    async def run_json(self, command, *arguments):
        assert command == "unresolved"
        assert arguments == ("verbose", "format=json")
        return targets or {}

    async def run(self, command, *arguments):
        native_calls.append((command, arguments))
        return "fixture"

    monkeypatch.setattr(NativeObsidian, "run", run)
    monkeypatch.setattr(NativeObsidian, "run_json", run_json)
    config = tmp_path / "preferences.yaml"
    config.write_text("ai_managed: []\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CONFIG", str(config))

    async def exercise():
        server = create_server(tmp_path)

        async def call(name, **arguments):
            _, output = await server.call_tool(name, arguments)
            return output

        first = await call("vault_garden_unresolved", limit=1)
        assert first["items"] == [{"link": "A", "count": 1, "sources": "wiki/a.md"}]
        assert first["total_references"] == 3
        second = await call(
            "vault_garden_unresolved", offset=first["next_offset"], snapshot=first["snapshot"]
        )
        assert second["items"] == [{"link": "B", "count": 2, "sources": "wiki/b.md"}]
        assert second["next_offset"] is None
        assert (await call("vault_garden_unresolved", link_contains="B"))["matching_targets"] == 1
        for arguments, message in [
            ({"offset": 1}, "snapshot"),
            ({"offset": 1, "snapshot": "stale"}, "snapshot"),
            ({"offset": 3, "snapshot": first["snapshot"]}, "offset"),
        ]:
            with pytest.raises(ToolError, match=message):
                await call("vault_garden_unresolved", **arguments)
        targets.clear()
        with pytest.raises(ToolError, match="unexpected native"):
            await call("vault_garden_unresolved")
        assert (await call("vault_garden_orphans"))["orphans"] == "fixture"
        await call("vault_garden_backlinks", path="wiki/note.md")
        await call("vault_garden_rename", path="wiki/note.md", new_name="renamed.md")
        await call("vault_garden_move", path="wiki/renamed.md", destination="root.md")
        with pytest.raises(ToolError, match="must be a filename"):
            await call("vault_garden_rename", path="wiki/note.md", new_name="other/not-a-name.md")
        assert native_calls == [
            ("orphans", ("format=json",)),
            ("backlinks", ("path=wiki/note.md", "format=json")),
            ("rename", ("path=wiki/note.md", "name=renamed.md")),
            ("move", ("path=wiki/renamed.md", "to=root.md")),
        ]
        with pytest.raises(ToolError, match="audit snapshot"):
            await call("vault_garden_audit_page", snapshot="unknown")
        monkeypatch.setattr(mcp_garden, "AUDIT_POLL_SECONDS", 0)
        started = await call("vault_garden_audit_page")
        assert started["status"] == "running"
        assert (await call("vault_garden_audit_page"))["snapshot"] == started["snapshot"]
        monkeypatch.setattr(mcp_garden, "AUDIT_POLL_SECONDS", 5)
        with pytest.raises(ToolError, match="audit snapshot"):
            await call("vault_garden_audit_page", snapshot="stale")
        audit = await call(
            "vault_garden_audit_page", snapshot=started["snapshot"], offset=started["next_offset"]
        )
        assert audit["status"] == "ready"
        assert audit["items"] == ["OK: no structural or convention issues found"]
        config.write_text("ai_managed: malformed\n")
        with pytest.raises(ToolError, match="ai_managed"):
            await call("vault_garden_audit_page")

        async def failed_audit(process, **bounds):
            await process.communicate()
            assert bounds["deadline_seconds"] == 240
            raise ValueError("fixture audit deadline")

        monkeypatch.setattr(mcp_garden, "collect_bounded_output", failed_audit)
        with pytest.raises(ToolError, match="fixture audit deadline"):
            await call("vault_garden_audit_page")

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

    spawn = asyncio.create_subprocess_exec

    async def bounded_search(*command, **kwargs):
        assert "--no-rebuild" not in command
        assert "--no-wait" not in command
        return await spawn(*command, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", bounded_search)

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


def test_managed_search_does_not_return_protected_hits(tmp_path, monkeypatch):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/link.md").symlink_to(tmp_path / "wiki/readable.md")
    paths = [
        "wiki/readable.md",
        "wiki/_sources/note.md",
        "wiki/link.md",
        "Utility/obsidian-knowledge/reports/archive/note.md",
    ]

    async def search(command, operation):
        assert operation == "search"
        assert "--all" in command
        return json.dumps(
            {
                "mode": "keyword",
                "degraded_reason": "private diagnostic",
                "outside_digest_matches": 4,
                "hits": [{"path": path, "score": 1, "snippet": path} for path in paths],
            }
        ).encode(), b""

    monkeypatch.setattr(mcp_server, "run_index_command", search)
    _, result = asyncio.run(
        create_server(tmp_path).call_tool("vault_managed_search", {"query": "note", "all_paths": True})
    )
    assert result == {
        "mode": "keyword",
        "hits": [{"path": "wiki/readable.md", "score": 1.0, "snippet": "wiki/readable.md"}],
    }


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
        assert {"vault_read", "vault_write"} <= {tool["name"] for tool in response.json()["result"]["tools"]}
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


@pytest.mark.parametrize("operation,arguments", [("vault_search", {"query": "orchid"})])
@pytest.mark.parametrize("outcome", ["timeout", "cancel", "failure"])
def test_search_failure_and_process_cleanup(tmp_path, monkeypatch, outcome, operation, arguments):
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
                await server.call_tool(operation, arguments)
        else:
            with pytest.raises(ToolError):
                await server.call_tool(operation, arguments)
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
                        assert "vault_write" in {tool.name for tool in tools.tools}
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
