"""Append works without a desktop app and preserves existing bytes."""

import asyncio
import stat

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from lib.vault_index.mcp_server import create_server


@pytest.mark.parametrize("inline,separator", [(False, b"\n"), (True, b"")])
def test_append_without_obsidian(tmp_path, monkeypatch, inline, separator):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(tmp_path / "missing-cli"))
    note = tmp_path / "note.md"
    original = b"---\r\ncreated: unchanged\r\n---\r\nDiary\r\n"
    note.write_bytes(original)
    note.chmod(0o640)
    content = r"Literal \n and \t; café" + "\nNext line"

    async def exercise():
        result = await create_server(tmp_path).call_tool(
            "vault_append", {"path": "note.md", "content": content, "inline": inline}
        )
        assert result[1] == {"path": "note.md", "status": "appended"}

    asyncio.run(exercise())
    assert note.read_bytes() == original + separator + content.encode()
    assert stat.S_IMODE(note.stat().st_mode) == 0o640


def test_append_empty_file_and_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(tmp_path / "missing-cli"))
    (tmp_path / "empty.md").touch()

    async def exercise():
        server = create_server(tmp_path)
        await server.call_tool("vault_append", {"path": "empty.md", "content": "First"})
        with pytest.raises(ToolError, match="does not exist"):
            await server.call_tool("vault_append", {"path": "missing.md", "content": "First"})

    asyncio.run(exercise())
    assert (tmp_path / "empty.md").read_bytes() == b"\nFirst"
    assert not (tmp_path / "missing.md").exists()


@pytest.mark.parametrize("path", ["../outside.md", ".hidden.md", "_sources/note.md", "alias/note.md"])
def test_append_rejects_unsafe_paths(tmp_path, path):
    (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)

    async def exercise():
        with pytest.raises(ToolError):
            await create_server(tmp_path).call_tool("vault_append", {"path": path, "content": "No"})

    asyncio.run(exercise())


def test_concurrent_appends_keep_every_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_OBSIDIAN_CLI", str(tmp_path / "missing-cli"))
    (tmp_path / "note.md").write_text("Original")

    async def exercise():
        server = create_server(tmp_path)
        await asyncio.gather(
            *(
                server.call_tool("vault_append", {"path": "note.md", "content": f"Entry {n}"})
                for n in range(20)
            )
        )

    asyncio.run(exercise())
    lines = (tmp_path / "note.md").read_text().splitlines()
    assert lines[0] == "Original"
    assert sorted(lines[1:]) == sorted(f"Entry {n}" for n in range(20))


def test_append_helper_rejects_empty_content(tmp_path):
    from pathlib import Path

    from lib.vault_index.vault_files import append_vault_file

    (tmp_path / "note.md").write_bytes(b"Original")
    with pytest.raises(ValueError, match="must not be empty"):
        append_vault_file(tmp_path, Path("note.md"), "")
    assert (tmp_path / "note.md").read_bytes() == b"Original"
