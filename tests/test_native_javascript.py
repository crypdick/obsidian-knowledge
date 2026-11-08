"""Execute native eval programs, rather than simulating their intended behavior."""

import asyncio
import json
import shutil
import subprocess
import threading

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from lib.vault_index.mcp_native import register_native_tools
from lib.vault_index.obsidian_cli import NativeObsidian


@pytest.fixture
def javascript_server(tmp_path, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.fail("native JavaScript contract tests require Node.js")
    state = {"metadata": {"created": "2026-10-15"}, "files": []}
    stub = """
const fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const state=input.state;
const app={vault:{getFileByPath:path=>state.files.find(f=>f.path===path),
                 getMarkdownFiles:()=>state.files},
           fileManager:{processFrontMatter:async(file,edit)=>edit(state.metadata)}};
Promise.resolve(eval(input.code)).then(result=>console.log(result));
"""

    async def run_json(self, command, *arguments):
        assert command == "eval"
        code = next(value.removeprefix("code=") for value in arguments if value.startswith("code="))
        result = await asyncio.to_thread(
            subprocess.run,
            [node, "-e", stub],
            input=json.dumps({"code": code, "state": state}),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(result.stderr)
        return json.loads(result.stdout)

    async def refresh(paths):
        return "queued"

    monkeypatch.setattr(NativeObsidian, "run_json", run_json)
    server = FastMCP("javascript-test")
    register_native_tools(server, tmp_path, threading.Lock(), refresh)
    return server, state


def call(server, tool, arguments):
    return asyncio.run(server.call_tool(tool, arguments))[1]


def test_frontmatter_program_preserves_properties_and_treats_updates_as_data(javascript_server):
    server, state = javascript_server
    state["files"] = [{"path": "note.md"}]
    updates = {"nested": {"enabled": True}, "__proto__": {"polluted": True}, "text": "');throw Error('x');//"}
    assert call(server, "vault_frontmatter", {"path": "note.md", "updates": updates}) == {
        "created": "2026-10-15",
        **updates,
    }
    with pytest.raises(ToolError, match="File not found"):
        call(server, "vault_frontmatter", {"path": "missing.md", "updates": {"title": "Missing"}})


def test_recent_program_filters_sorts_and_limits_real_records(javascript_server):
    server, state = javascript_server
    state["files"] = [
        {"path": path, "stat": {"mtime": mtime, "size": 8}}
        for path, mtime in [
            ("folder/b.md", 20),
            ("folder/a.md", 20),
            ("folder/old.md", 10),
            ("elsewhere/new.md", 100),
            ("folderish/new.md", 100),
            ("folder/.hidden/new.md", 100),
            ("folder/_sources/new.md", 100),
            ("folder/node_modules/new.md", 100),
            ("folder/venv/new.md", 100),
            ("folder/__pycache__/new.md", 100),
            ("folder/a.sync-conflict-copy.md", 100),
        ]
    ]
    assert call(server, "vault_recent", {"n": 2, "path_filter": "folder"}) == {
        "notes": [
            {"path": "folder/a.md", "mtime_ms": 20, "size_bytes": 8},
            {"path": "folder/b.md", "mtime_ms": 20, "size_bytes": 8},
        ],
        "has_more": True,
    }
    assert len(call(server, "vault_recent", {"n": 20})["notes"]) == 5
