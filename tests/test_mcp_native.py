"""MCP contracts against a fake official CLI, with no GUI dependency."""

import asyncio
import json
import sys
import threading

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from lib.vault_index.mcp_native import register_native_tools


@pytest.fixture
def native_server(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "folder").mkdir()
    (vault / "folder" / "note.md").write_text("Original")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"metadata": {"created": "2026-10-15"}, "grep": []}))
    binary = tmp_path / "official-cli"
    binary.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, pathlib, sys
root = pathlib.Path(os.environ["FAKE_ROOT"])
statepath = pathlib.Path(os.environ["FAKE_STATE"])
state = json.loads(statepath.read_text())
command = sys.argv[2]
args = dict(argument.split("=",1) for argument in sys.argv[3:] if "=" in argument)
if command == "vault":
    print(root if args.get("info") == "path" else "name\\tFixed Vault\\nfiles\\t1")
elif command == "append":
    path = root / args["path"]
    path.write_text(path.read_text() + ("" if "inline" in sys.argv else "\\n") + args["content"])
    print("Appended")
elif command == "properties":
    print(json.dumps(state["metadata"]))
elif command == "eval":
    code = args["code"]
    encoded, _ = json.JSONDecoder().raw_decode(code.split("const args=JSON.parse(",1)[1])
    payload = json.loads(encoded)
    if "updates" in payload:
        state["metadata"].update(payload["updates"])
        result = state["metadata"]
        statepath.write_text(json.dumps(state))
    else:
        result = state.get("recent", {"notes": [{"path": "folder/note.md", "mtime_ms": 1234, "size_bytes": 8}], "has_more": False})
    print("=> " + json.dumps(result))
elif command == "search:context":
    needle = json.loads(args["query"]).casefold()
    records = []
    for record in state["grep"]:
        matches = [match for match in record["matches"] if state.get("include_context") or needle in match["text"].casefold()]
        if matches:
            records.append({"file": record["file"], "matches": matches})
    print(json.dumps(records))
elif command == "file":
    if not (root / args["path"]).is_file():
        print("Error: File not found.")
    else:
        print("path\\t" + args["path"])
elif command == "move":
    target = root / args["to"]
    target.parent.mkdir(parents=True, exist_ok=True)
    (root / args["path"]).rename(target)
    print("Moved")
elif command == "delete":
    assert "permanent" not in sys.argv
    trash = root / ".trash"
    trash.mkdir(exist_ok=True)
    (root / args["path"]).rename(trash / pathlib.Path(args["path"]).name)
    print("Trashed")
else:
    raise AssertionError(command)
"""
    )
    binary.chmod(0o755)
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(binary))
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_VAULT", "Fixed Vault")
    monkeypatch.setenv("FAKE_ROOT", str(vault))
    monkeypatch.setenv("FAKE_STATE", str(state))
    server = FastMCP("native-test")
    register_native_tools(server, vault, threading.Lock())
    return server, vault, state


def call(server, name, arguments=None):
    return asyncio.run(server.call_tool(name, arguments or {}))[1]


def test_append_and_native_properties(native_server):
    server, vault, _ = native_server
    assert call(server, "vault_append", {"path": "folder/note.md", "content": "Next"})["status"] == "appended"
    call(server, "vault_append", {"path": "folder/note.md", "content": " inline", "inline": True})
    assert (vault / "folder/note.md").read_text() == "Original\nNext inline"
    assert call(server, "vault_frontmatter", {"path": "folder/note.md"}) == {"created": "2026-10-15"}
    updates = {"nested": {"value": [True, None, 3]}, "text": "'); throw new Error('injected');//"}
    result = call(server, "vault_frontmatter", {"path": "folder/note.md", "updates": updates})
    assert result == {"created": "2026-10-15", **updates}
    assert call(server, "vault_frontmatter", {"path": "folder/note.md", "updates": {}}) == result


def test_recent_info_and_folder_filter(native_server):
    server, _, _ = native_server
    expected = {"notes": [{"path": "folder/note.md", "mtime_ms": 1234, "size_bytes": 8}], "has_more": False}
    assert call(server, "vault_recent") == expected
    assert call(server, "vault_recent", {"path_filter": ".", "n": 1}) == expected
    assert call(server, "vault_recent", {"path_filter": "folder"}) == expected
    assert "Fixed Vault" in call(server, "vault_info")["info"]


def test_move_dry_run_and_trash(native_server):
    server, vault, _ = native_server
    arguments = {"from_path": "folder/note.md", "to_path": "new/moved.md"}
    preview = call(server, "vault_move", {**arguments, "dry_run": True})
    assert preview["dry_run"] is True
    assert (vault / "folder/note.md").exists()
    assert call(server, "vault_move", arguments)["status"] == "moved"
    assert (vault / "new/moved.md").read_text() == "Original"
    assert call(server, "vault_delete", {"path": "new/moved.md"})["status"] == "trashed"
    assert (vault / ".trash/moved.md").read_text() == "Original"


def test_move_refuses_collision_and_missing_source(native_server):
    server, _, _ = native_server
    with pytest.raises(ToolError, match="already exists"):
        call(server, "vault_move", {"from_path": "folder/note.md", "to_path": "folder/note.md"})
    with pytest.raises(ToolError, match="File not found"):
        call(server, "vault_move", {"from_path": "missing.md", "to_path": "new.md", "dry_run": True})


def test_grep_is_bounded_and_filters_hidden_paths(native_server):
    server, _, state = native_server
    assert call(server, "vault_grep", {"query": "missing"}) == {"matches": [], "truncated": False}
    state.write_text(
        json.dumps(
            {
                "grep": [
                    {"file": "_sources/secret.md", "matches": [{"line": 1, "text": "hidden x"}]},
                    {
                        "file": "folder/note.md",
                        "matches": [{"line": 2, "text": "x" * 3000}, {"line": 3, "text": "Next"}],
                    },
                ]
            }
        )
    )
    result = call(server, "vault_grep", {"query": "X", "path_filter": "folder", "max_results": 1})
    assert result == {
        "matches": [{"path": "folder/note.md", "line": 2, "text": "x" * 2000}],
        "truncated": True,
    }
    result = call(server, "vault_grep", {"query": "x", "max_results": 20})
    assert len(result["matches"]) == 2
    assert result["truncated"] is False


def test_grep_long_line_keeps_match_near_end(native_server):
    server, _, state = native_server
    state.write_text(
        json.dumps(
            {
                "grep": [
                    {
                        "file": "folder/note.md",
                        "matches": [
                            {"line": 1, "text": "x" * 5000 + "NeedleEND"},
                        ],
                    }
                ]
            }
        )
    )
    result = call(server, "vault_grep", {"query": "needleend"})
    assert result["matches"] == [{"path": "folder/note.md", "line": 1, "text": "x" * 1991 + "NeedleEND"}]


def test_recent_excludes_physical_symlinks_and_hidden_entries(native_server):
    server, vault, state = native_server
    (vault / "alias").symlink_to(vault / "folder", target_is_directory=True)
    state.write_text(
        json.dumps(
            {
                "recent": {
                    "notes": [
                        {"path": "alias/note.md", "mtime_ms": 3000, "size_bytes": 8},
                        {"path": "_sources/secret.md", "mtime_ms": 2000, "size_bytes": 8},
                        {"path": "folder/note.md", "mtime_ms": 1234, "size_bytes": 8},
                    ],
                    "has_more": False,
                }
            }
        )
    )
    assert call(server, "vault_recent") == {
        "notes": [{"path": "folder/note.md", "mtime_ms": 1234, "size_bytes": 8}],
        "has_more": True,
    }


def test_grep_context_without_literal_match_stays_bounded(native_server):
    server, _, state = native_server
    state.write_text(
        json.dumps(
            {
                "include_context": True,
                "grep": [
                    {
                        "file": "folder/note.md",
                        "matches": [{"line": 1, "text": "Context " + "x" * 3000}],
                    }
                ],
            }
        )
    )
    result = call(server, "vault_grep", {"query": "needle"})
    assert result["matches"] == [{"path": "folder/note.md", "line": 1, "text": "Context " + "x" * 1992}]


def test_recent_bounds_and_validates_native_response(native_server):
    server, _, state = native_server
    note = {"path": "folder/note.md", "mtime_ms": 1234, "size_bytes": 8}
    state.write_text(json.dumps({"recent": {"notes": [note, note], "has_more": False}}))
    assert call(server, "vault_recent", {"n": 1}) == {"notes": [note], "has_more": True}
    for invalid in [
        {"notes": [note], "has_more": "false"},
        {"notes": [note] * 501, "has_more": False},
        {"notes": [{**note, "size_bytes": -1}], "has_more": False},
    ]:
        state.write_text(json.dumps({"recent": invalid}))
        with pytest.raises(ToolError):
            call(server, "vault_recent")


@pytest.mark.parametrize(
    "path",
    ["../outside.md", ".hidden.md", "_sources/note.md", "/tmp/note.md", "wiki/sync.sync-conflict-1.md", "."],
)
def test_native_tools_reject_unsafe_paths(native_server, path):
    server, _, _ = native_server
    with pytest.raises(ToolError):
        call(server, "vault_delete", {"path": path})


def test_symlink_path_rejected(native_server):
    server, vault, _ = native_server
    (vault / "alias").symlink_to(vault / "folder", target_is_directory=True)
    with pytest.raises(ToolError, match="symlink"):
        call(server, "vault_delete", {"path": "alias/note.md"})


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("vault_recent", {"n": 0}),
        ("vault_recent", {"n": 501}),
        ("vault_grep", {"query": "", "max_results": 1}),
        ("vault_grep", {"query": "text", "max_results": 501}),
        ("vault_append", {"path": "folder/note.md", "content": ""}),
    ],
)
def test_native_tool_bounds(native_server, tool, arguments):
    server, _, _ = native_server
    with pytest.raises(ToolError):
        call(server, tool, arguments)


def test_invalid_native_properties_rejected(native_server):
    server, _, state = native_server
    state.write_text(json.dumps({"metadata": []}))
    with pytest.raises(ToolError, match="JSON object"):
        call(server, "vault_frontmatter", {"path": "folder/note.md"})
