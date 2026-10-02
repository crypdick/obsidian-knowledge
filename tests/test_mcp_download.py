"""Binary file delivery through the MCP public contract."""

import asyncio
import base64
import hashlib

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import BlobResourceContents, EmbeddedResource

from lib.vault_index.mcp_server import create_server


@pytest.mark.parametrize(
    ("name", "mime_type", "content"),
    [
        (
            "budget.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"PK\x03\x04\x00\xff",
        ),
        ("report.pdf", "application/pdf", b"%PDF-1.7\n\xff"),
        ("unknown.binary", "application/octet-stream", bytes(range(256))),
        ("empty.bin", "application/octet-stream", b""),
        ("notes with # and café.txt", "text/plain", b"Literal text"),
    ],
)
def test_binary_download_over_http(tmp_path, name, mime_type, content):
    (tmp_path / name).write_bytes(content)

    async def exercise():
        server = create_server(tmp_path)
        app = server.streamable_http_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
                async with streamable_http_client("http://localhost:8000/mcp", http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        result = await client.call_tool("download_file", {"path": name})
                        assert result.isError is False
                        assert len(result.content) == 1
                        resource = result.content[0]
                        assert isinstance(resource, EmbeddedResource)
                        assert isinstance(resource.resource, BlobResourceContents)
                        assert resource.resource.mimeType == mime_type
                        assert base64.b64decode(resource.resource.blob, validate=True) == content
                        assert result.structuredContent == {
                            "filename": name,
                            "mime_type": mime_type,
                            "size_bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                        assert str(resource.resource.uri).startswith("obsidian-vault:///")
                        assert "#" not in str(resource.resource.uri)
                        assert str(tmp_path) not in str(resource.resource.uri)

    asyncio.run(exercise())


@pytest.mark.parametrize("path", ["../escape.bin", "/tmp/escape.bin", "missing.bin", "."])
def test_download_rejects_invalid_paths(tmp_path, path):
    async def exercise():
        with pytest.raises(ToolError):
            await create_server(tmp_path).call_tool("download_file", {"path": path})

    asyncio.run(exercise())


def test_download_rejects_symlink_escape(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"private")
    (vault / "escape.bin").symlink_to(outside)

    async def exercise():
        with pytest.raises(ToolError, match="outside the vault"):
            await create_server(vault).call_tool("download_file", {"path": "escape.bin"})

    asyncio.run(exercise())


def test_download_size_boundary(tmp_path):
    limit = 6 * 1024 * 1024
    path = tmp_path / "large.bin"
    path.write_bytes(b"\xff" * limit)

    async def exercise():
        server = create_server(tmp_path)
        result = await server.call_tool("download_file", {"path": "large.bin"})
        assert len(base64.b64decode(result.content[0].resource.blob)) == limit
        with path.open("ab") as stream:
            stream.write(b"\x00")
        with pytest.raises(ToolError, match="exceeds"):
            await server.call_tool("download_file", {"path": "large.bin"})

    asyncio.run(exercise())
