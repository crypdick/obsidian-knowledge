"""Public CLI commands and discovered MCP tools must stay in sync."""

import asyncio
import hashlib
import json
import subprocess
import sys
import time

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from gardener.cli import build_parser as build_garden_parser
from lib.vault_index.cli import build_parser
from lib.vault_index.mcp_server import create_server

# Binary download is read with transport metadata. Reindex's synchronous
# foreground mode is host-only; both adapters support all queue selections.
CLI_TO_MCP = {
    "read": {"vault_read", "download_file"},
    "write": {"vault_write"},
    "patch": {"vault_patch"},
    "append": {"vault_append"},
    "list": {"vault_list"},
    "search": {"vault_search"},
    "remember": {"vault_remember"},
    "doctor": {"vault_search_doctor"},
    "search-status": {"vault_search_status"},
    "search-update": {"vault_search_update"},
    "reindex": {"vault_search_update"},
    "papercut": {"vault_papercut"},
    "frontmatter": {"vault_frontmatter"},
    "recent": {"vault_recent"},
    "grep": {"vault_grep"},
    "info": {"vault_info"},
    "delete": {"vault_delete"},
    "move": {"vault_move"},
    "garden audit": {"vault_garden_audit"},
    "garden links": {"vault_garden_links"},
    "garden index": {"vault_garden_index"},
    "garden questions": {"vault_garden_questions"},
    "garden frontmatter": {"vault_garden_frontmatter"},
}
HOST_ONLY = {
    "setup",  # Register vault and install host software.
    "init-vault-index",  # Change deployment preferences.
    "install-rules",  # Install host guard configuration.
    "index-worker",  # Run a supervised process.
    "_hook",  # Private harness lifecycle protocol.
}


def test_cli_and_mcp_discovery_have_parity(tmp_path):
    cli_choices = next(action.choices for action in build_parser()._actions if action.dest == "cmd")
    garden_choices = next(
        action.choices for action in build_garden_parser()._actions if action.dest == "operation"
    )
    command_names = (set(cli_choices) - {"garden"}) | {f"garden {name}" for name in garden_choices}
    expected_commands = CLI_TO_MCP.keys() | HOST_ONLY
    assert command_names == expected_commands, (
        f"unmapped CLI commands: {command_names - expected_commands}; "
        f"stale mappings: {expected_commands - command_names}"
    )
    assert "garden" in cli_choices
    assert not CLI_TO_MCP.keys() & HOST_ONLY

    tool_names = {tool.name for tool in asyncio.run(create_server(tmp_path).list_tools())}
    expected_tools = set().union(*CLI_TO_MCP.values())
    assert tool_names == expected_tools, (
        f"unmapped MCP tools: {tool_names - expected_tools}; stale mappings: {expected_tools - tool_names}"
    )


def cli(vault, *args, data=None, check=True):
    return subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", args[0], "--vault", str(vault), *args[1:]],
        input=data,
        capture_output=True,
        check=check,
        timeout=20,
    )


def tool(vault, name, **arguments):
    return asyncio.run(create_server(vault).call_tool(name, arguments))[1]


def test_file_edit_and_listing_parity(tmp_path):
    note = tmp_path / "note.md"
    original = b"Before\r\n"
    note.write_bytes(original)
    sha = hashlib.sha256(original).hexdigest()
    patched = cli(tmp_path, "patch", "note.md", "Before", "After", "--expected-sha256", sha)
    assert note.read_bytes() == b"After\r\n"
    note.write_bytes(original)
    assert json.loads(patched.stdout) == tool(
        tmp_path,
        "vault_patch",
        path="note.md",
        old_str="Before",
        new_str="After",
        expected_sha256=sha,
    )
    assert (
        cli(tmp_path, "patch", "note.md", "After", "Before", "--expected-sha256", sha, check=False).returncode
        == 2
    )
    assert (
        cli(
            tmp_path, "patch", "note.md", "After", "Before", "--expected-sha256", "bad", check=False
        ).returncode
        == 2
    )

    content = "literal \\\\n and café\r\n"
    appended = cli(tmp_path, "append", "note.md", "--inline", data=content.encode())
    assert note.read_bytes() == b"After\r\n" + content.encode()
    note.write_bytes(b"After\r\n")
    assert json.loads(appended.stdout) == tool(
        tmp_path, "vault_append", path="note.md", content=content, inline=True
    )

    (tmp_path / "other.md").touch()
    (tmp_path / ".hidden.md").touch()
    page = cli(
        tmp_path, "list", "--recursive", "--depth", "2", "--limit", "1", "--offset", "1", "--pattern", "*.md"
    )
    assert json.loads(page.stdout) == tool(
        tmp_path, "vault_list", recursive=True, depth=2, limit=1, offset=1, pattern="*.md"
    )
    assert json.loads(cli(tmp_path, "list").stdout) == tool(tmp_path, "vault_list")
    assert cli(tmp_path, "list", "--limit", "501", check=False).returncode == 2


@pytest.mark.parametrize(
    ("flags", "arguments", "pending"),
    [
        ([], {}, "@scan"),
        (["--force"], {"force": True}, "@rebuild"),
        (["--path", "./note.md"], {"paths": ["./note.md"]}, "note.md"),
    ],
)
def test_status_and_queue_parity(tmp_path, monkeypatch, flags, arguments, pending):
    from lib.vault_index.cache_paths import default_cache_dir
    from lib.vault_index.dirty_paths import DirtyPaths

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    assert json.loads(cli(tmp_path, "search-status").stdout) == tool(tmp_path, "vault_search_status")
    (tmp_path / "note.md").touch()
    assert json.loads(cli(tmp_path, "search-update", *flags).stdout) == {"status": "queued"}
    queue = DirtyPaths(default_cache_dir(tmp_path) / "pending.sqlite")
    path, revision = queue.ready(now=time.time() + 60)
    assert path == pending
    queue.complete(path, revision)
    (tmp_path / "note.md").write_text("changed")
    assert tool(tmp_path, "vault_search_update", **arguments) == {"status": "queued"}
    assert queue.ready(now=time.time() + 60)[0] == pending


def test_remote_queue_rejects_conflicting_or_escaping_selections(tmp_path, monkeypatch):
    from lib.vault_index.cache_paths import default_cache_dir

    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "outside.md")
    with pytest.raises(ToolError, match="mutually exclusive"):
        tool(tmp_path, "vault_search_update", force=True, paths=["note.md"])
    for path in ["../outside.md", "escape.md"]:
        with pytest.raises(ToolError, match="escapes vault"):
            tool(tmp_path, "vault_search_update", paths=["note.md", path])
    assert not (default_cache_dir(tmp_path) / "pending.sqlite").exists()


def test_remember_and_live_doctor_parity(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", "offline")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CACHE_ROOT", str(tmp_path / "cache"))
    with pytest.raises(ToolError, match="index absent"):
        tool(tmp_path, "vault_search_doctor")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/orchid.md").write_text("Greenhouse orchid")
    cli(tmp_path, "reindex")

    memory = tool(tmp_path, "vault_remember", memory="orchid", top_k=1, all_paths=True)
    assert memory == json.loads(cli(tmp_path, "search", "--top-k", "1", "--all", "--json", "orchid").stdout)
    assert b"wiki/orchid.md" in cli(tmp_path, "remember", "orchid", "--top-k", "1", "--all").stdout
    for query, passed in [("orchid", True), ("--missing", False)]:
        doctor = tool(tmp_path, "vault_search_doctor", queries=[query], top_k=1, digest_only=True)
        local = cli(
            tmp_path,
            "doctor",
            f"--query={query}",
            "--top-k",
            "1",
            "--digest-only",
            "--no-host-paths",
            check=False,
        )
        assert doctor == {"passed": passed, "report": local.stdout.decode().rstrip()}
        assert str(tmp_path) not in doctor["report"]


def test_papercut_parity(tmp_path):
    local = cli(tmp_path, "papercut", "Local friction", "--repository", "alice/repo")
    relative = "wiki/repos/alice/repo/PAPERCUTS.md"
    assert relative.encode() in local.stdout
    assert tool(tmp_path, "vault_papercut", description="Remote friction", repository="alice/repo") == {
        "path": relative,
        "status": "logged",
    }
    assert "Remote friction" in (tmp_path / relative).read_text()
    assert tool(tmp_path, "vault_papercut", description="Global friction")["path"].startswith("wiki/systems/")
    with pytest.raises(ToolError, match="owner/repo"):
        tool(tmp_path, "vault_papercut", description="bad repository", repository="../x")


@pytest.mark.parametrize("filename", ["PAPERCUTS.md", ".PAPERCUTS.md.lock"])
def test_papercut_rejects_links_outside_fixed_vault(tmp_path, filename):
    vault = tmp_path / "vault"
    log_dir = vault / "wiki/repos/alice/repo"
    log_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (log_dir / filename).symlink_to(outside)
    with pytest.raises(ToolError, match="outside the vault"):
        tool(vault, "vault_papercut", description="Blocked", repository="alice/repo")
    assert outside.read_text() == "outside"


@pytest.mark.parametrize(
    ("operation", "flags", "arguments", "data"),
    [
        ("audit", [], {}, None),
        ("links", [], {"unresolved": []}, []),
        (
            "links",
            ["--include-stubs", "--format", "json", "--apply"],
            {"unresolved": [], "include_stubs": True, "output_format": "json", "apply": True},
            [],
        ),
        (
            "index",
            ["wiki/index.md"],
            {"path": "wiki/index.md", "review": {"title": "Wiki", "entries": []}},
            {"title": "Wiki", "entries": []},
        ),
        ("frontmatter", ["wiki/note.md"], {"paths": ["wiki/note.md"]}, None),
        ("frontmatter", ["--", "--vault"], {"paths": ["--vault"]}, None),
        ("questions", [], {}, None),
        (
            "questions",
            ["--report", "--timestamp=2026-01-01T00:00:00Z"],
            {"report": True, "timestamp": "2026-01-01T00:00:00Z"},
            None,
        ),
    ],
)
def test_gardener_parity(tmp_path, operation, flags, arguments, data):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/note.md").write_text("# Note\n")
    local = subprocess.run(
        [sys.executable, "-m", "lib.vault_index.cli", "garden", operation, "--vault", str(tmp_path), *flags],
        input=json.dumps(data).encode() if data is not None else None,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert tool(tmp_path, f"vault_garden_{operation}", **arguments) == {
        "exit_code": local.returncode,
        "stdout": local.stdout.decode(),
        "stderr": local.stderr.decode(),
    }


def test_doctor_reports_empty_failed_subprocess(tmp_path, monkeypatch):
    async def run(*args, **options):
        return b"", b""

    monkeypatch.setattr("lib.vault_index.mcp_server.run_index_command", run)
    with pytest.raises(ToolError, match="vault search doctor failed"):
        tool(tmp_path, "vault_search_doctor")


def test_remote_garden_index_only_writes_on_apply(tmp_path):
    (tmp_path / "wiki").mkdir()
    note = tmp_path / "wiki/index.md"
    request = {"path": "wiki/index.md", "review": {"title": "Wiki", "entries": []}}
    preview = tool(tmp_path, "vault_garden_index", **request)
    assert preview == {"exit_code": 0, "stdout": "# Wiki\n\n", "stderr": ""}
    assert not note.exists()
    assert tool(tmp_path, "vault_garden_index", **request, apply=True)["exit_code"] == 0
    assert note.read_text() == preview["stdout"]
