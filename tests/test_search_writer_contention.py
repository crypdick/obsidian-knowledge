"""Public CLI/MCP searches preserve vector consistency during indexing."""

from __future__ import annotations

import asyncio
import fcntl
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel

from lib.vault_index.config import VaultIndexConfig
from lib.vault_index.indexer import Indexer, default_cache_dir
from lib.vault_index.mcp_server import create_server


@dataclass
class Endpoint:
    requests: int = 0
    delay: float = 0


class EmbedRequest(BaseModel):
    input: list[str]


@pytest.fixture
def vector_vault(tmp_path, monkeypatch):
    endpoint = Endpoint()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(b'{"models": [{"name": "bge-m3:latest"}]}')

        def do_POST(self):
            payload = EmbedRequest.model_validate_json(self.rfile.read(int(self.headers["Content-Length"])))
            endpoint.requests += 1
            time.sleep(endpoint.delay)
            self.respond(json.dumps({"embeddings": [[1.0, 0.0] for _ in payload.input]}).encode())

        def respond(self, payload: bytes):
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when the bounded CLI terminates a slow request.

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("# Orchid\nPurple greenhouse orchids\n")
    instance = Indexer(tmp_path, default_cache_dir(tmp_path), VaultIndexConfig(), skip_probe=True)
    instance.full_reindex()
    asyncio.run(instance._store.close())
    endpoint.requests = 0
    try:
        yield tmp_path, default_cache_dir(tmp_path), endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cli_no_wait_reports_held_writer_without_empty_results(vector_vault):
    vault, cache, endpoint = vector_vault
    with (cache / ".index.sqlite.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lib.vault_index.cli",
                "search",
                "greenhouse",
                "--vault",
                str(vault),
                "--no-rebuild",
                "--no-wait",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    assert result.returncode == 2
    assert "another operation holds the index lock; retry after it completes" in result.stderr
    assert "timed out" not in result.stderr
    assert result.stdout == ""
    assert endpoint.requests == 0


def test_mcp_held_writer_reports_busy_then_hybrid_after_release(vector_vault):
    vault, cache, endpoint = vector_vault

    async def exercise():
        server = create_server(vault)
        with (cache / ".index.sqlite.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(
                ToolError, match="another operation holds the index lock; retry after it completes"
            ):
                await asyncio.wait_for(server.call_tool("vault_search", {"query": "greenhouse"}), timeout=15)
            assert endpoint.requests == 0
        result = await server.call_tool("vault_search", {"query": "greenhouse", "top_k": 1})
        assert result[1]["mode"] == "hybrid"
        assert result[1]["degraded_reason"] is None
        assert [hit["path"] for hit in result[1]["hits"]] == ["wiki/orchid.md"]
        assert endpoint.requests == 1

    asyncio.run(exercise())


def test_no_wait_still_bounds_slow_query_embedding(vector_vault, monkeypatch):
    vault, _cache, endpoint = vector_vault
    endpoint.delay = 10
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS", "4")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "search",
            "greenhouse",
            "--vault",
            str(vault),
            "--no-rebuild",
            "--no-wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert endpoint.requests == 1
    assert result.returncode == 124
    assert "search exceeded 4s TTL" in result.stderr
    assert result.stdout == ""


def test_no_wait_requires_no_rebuild(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lib.vault_index.cli",
            "search",
            "query",
            "--vault",
            str(tmp_path),
            "--no-wait",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "--no-wait requires --no-rebuild" in result.stderr
    assert result.stdout == ""
