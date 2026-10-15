"""Streamable HTTP adapter for existing vault operations."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import secrets
import sys
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ToolAnnotations
from pydantic import AnyUrl, BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lib.vault_index.cli import positive_int, resolve_vault, search_ttl_seconds
from lib.vault_index.mcp_index import IndexStatus, IndexUpdate, parse_index_update, read_index_status
from lib.vault_index.models import SearchReport
from lib.vault_index.vault_files import patch_vault_file, read_vault_file, write_vault_file
from lib.vault_index.vault_listing import ListingReport, list_vault_files

# NOTE: docs/MCP.md documents this raw-byte ceiling and client handoff limits.
MAX_DOWNLOAD_BYTES = 6 * 1024 * 1024


class DownloadMetadata(BaseModel):
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str


class BearerAuth(BaseHTTPMiddleware):
    """Optional private-server bearer authentication, independent of tunnel auth."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self.authorization = f"Bearer {token}".encode()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("authorization", "").encode()
        if not secrets.compare_digest(supplied, self.authorization):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


async def run_index_command(command: list[str], operation: str) -> tuple[bytes, bytes]:
    """Run one CLI operation with a deadline and reap its process on cancellation."""
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=search_ttl_seconds() + 10)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise ValueError(stderr.decode(errors="replace").strip() or f"vault {operation} failed")
    return stdout, stderr


def create_server(
    vault: Path, *, host: str = "127.0.0.1", port: int = 8000, allowed_hosts: list[str] | None = None
) -> FastMCP:
    """Create a server bound to one existing vault; clients cannot select roots."""
    vault = vault.expanduser().resolve(strict=True)
    if not vault.is_dir():
        raise ValueError("vault must be a directory")
    # NOTE: docs/MCP.md documents transport defaults and tool contracts.
    server = FastMCP(
        "obsidian-knowledge",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", f"{host}:*", *(allowed_hosts or [])],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", f"http://{host}:*"],
        ),
    )
    # Serialize index access to avoid competing rebuilds from concurrent requests.
    search_lock = asyncio.Lock()

    file_lock = threading.Lock()

    def mutate(operation: Callable[[], Path]) -> Path:
        # Keep the lock in the worker: cancellation does not stop a to_thread write.
        with file_lock:
            return operation()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_search(
        query: Annotated[str, Field(min_length=1)],
        top_k: Annotated[int | None, Field(gt=0)] = None,
        all_paths: bool = False,
    ) -> SearchReport:
        """Search indexed notes; all_paths bypasses the configured digest filter."""
        command = [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "search",
            "--vault",
            str(vault),
            "--json",
        ]
        if top_k is not None:
            command.extend(["--top-k", str(top_k)])
        if all_paths:
            command.append("--all")
        command.extend(["--", query])
        async with search_lock:
            stdout, _ = await run_index_command(command, "search")
        return SearchReport.model_validate(json.loads(stdout))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_read(path: str) -> str:
        """Read UTF-8 text from a vault-relative file. Paths cannot escape the vault."""
        content = await asyncio.to_thread(read_vault_file, vault, Path(path))
        return content.decode("utf-8")

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_write(path: str, content: str, replace: bool = False) -> dict[str, str]:
        """Write UTF-8 text atomically and verify bytes. Existing files require replace=true."""
        target = await asyncio.to_thread(
            mutate, partial(write_vault_file, vault, Path(path), content.encode("utf-8"), replace=replace)
        )
        return {"path": target.relative_to(vault).as_posix(), "status": "wrote and verified"}

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_patch(
        path: str,
        old_str: Annotated[str, Field(min_length=1)],
        new_str: str,
        expected_sha256: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None,
    ) -> dict[str, str]:
        """Replace exactly one text match, preserving other bytes; optionally require the original SHA-256."""
        target = await asyncio.to_thread(
            mutate,
            partial(patch_vault_file, vault, Path(path), old_str, new_str, expected_sha256=expected_sha256),
        )
        return {"path": target.relative_to(vault).as_posix(), "status": "patched and verified"}

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_list(
        path: str = "",
        recursive: bool = False,
        depth: Annotated[int, Field(ge=1, le=10)] = 3,
        pattern: str | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> ListingReport:
        """List visible vault entries in sorted depth-first order; offset pages through matching entries."""
        return await asyncio.to_thread(
            list_vault_files,
            vault,
            Path(path),
            recursive=recursive,
            depth=depth,
            pattern=pattern,
            limit=limit,
            offset=offset,
        )

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_search_status() -> IndexStatus:
        """Inspect persisted index readiness without rebuilding or probing the embedding service."""
        async with search_lock:
            return await asyncio.to_thread(read_index_status, vault)

    @server.tool(annotations=ToolAnnotations(destructiveHint=False, openWorldHint=False))
    async def vault_search_update() -> IndexUpdate:
        """Incrementally refresh the search index; report busy when another process holds the index lock."""
        command = [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "reindex",
            "--vault",
            str(vault),
            "--timeout-seconds",
            str(search_ttl_seconds()),
        ]
        async with search_lock:
            stdout, stderr = await run_index_command(command, "index update")
        return parse_index_update(stdout, stderr)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    async def download_file(path: str) -> Annotated[CallToolResult, DownloadMetadata]:
        """Deliver original file bytes as an embedded MCP resource, up to 6 MiB. Client handles saving."""
        relative_path = Path(path)
        content = await asyncio.to_thread(read_vault_file, vault, relative_path, max_bytes=MAX_DOWNLOAD_BYTES)
        mime_type = mimetypes.guess_type(relative_path.name)[0] or "application/octet-stream"
        metadata = DownloadMetadata(
            filename=relative_path.name,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        return CallToolResult(
            structuredContent=metadata.model_dump(),
            content=[
                EmbeddedResource(
                    type="resource",
                    resource=BlobResourceContents(
                        uri=AnyUrl(f"obsidian-vault:///{quote(relative_path.as_posix(), safe='/')}"),
                        mimeType=mime_type,
                        blob=base64.b64encode(content).decode("ascii"),
                    ),
                )
            ],
        )

    return server


def main() -> None:
    """Run the private HTTP listener."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=positive_int, default=8000)
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Additional trusted Host header, e.g. vault-server:*",
    )
    args = parser.parse_args()
    if args.port > 65535:
        parser.error("port must be between 1 and 65535")
    server = create_server(
        resolve_vault(args.vault), host=args.host, port=args.port, allowed_hosts=args.allowed_host
    )
    app = server.streamable_http_app()
    token = os.environ.get("OBSIDIAN_KNOWLEDGE_MCP_TOKEN")
    if token:
        app.add_middleware(BearerAuth, token=token)
    uvicorn.run(app, host=args.host, port=args.port)
