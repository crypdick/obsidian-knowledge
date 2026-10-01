"""Streamable HTTP adapter for existing vault operations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Annotated

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lib.vault_index.cli import positive_int, resolve_vault, search_ttl_seconds
from lib.vault_index.models import SearchReport
from lib.vault_index.vault_files import read_vault_file, write_vault_file


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
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=search_ttl_seconds() + 10
                )
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        if process.returncode:
            raise ValueError(stderr.decode(errors="replace").strip() or "vault search failed")
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
            write_vault_file, vault, Path(path), content.encode("utf-8"), replace=replace
        )
        return {"path": target.relative_to(vault).as_posix(), "status": "wrote and verified"}

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
