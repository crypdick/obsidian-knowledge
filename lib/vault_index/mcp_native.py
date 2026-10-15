"""Bounded MCP adapters for the official Obsidian CLI and app APIs."""

from __future__ import annotations

import asyncio
import json
import re
from _thread import LockType
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, TypeAdapter

from lib.vault_index.obsidian_cli import NativeObsidian
from lib.vault_index.vault_files import resolve_vault_file


class _NativeMatch(BaseModel):
    line: int = Field(ge=1)
    text: str


class _NativeFileMatches(BaseModel):
    file: str
    matches: list[_NativeMatch]


class _NativeRecentNote(BaseModel):
    path: str
    mtime_ms: int | float = Field(ge=0)
    size_bytes: int = Field(ge=0)


class _NativeRecentReport(BaseModel):
    notes: list[_NativeRecentNote] = Field(max_length=500)
    has_more: bool


_GREP = TypeAdapter(list[_NativeFileMatches])
_VISIBLE_JS = (
    "const visible=p=>p.split('/').every(s=>!s.startsWith('.')"
    "&&!['_sources','node_modules','__pycache__','venv'].includes(s))"
    "&&!p.includes('.sync-conflict-');"
)


def run_vault_mutation[T](lock: LockType, operation: Callable[[], T]) -> T:
    """Keep the shared lock until worker completion, including request cancellation."""
    with lock:
        return operation()


def _path(vault: Path, value: str, *, allow_root: bool = False) -> str:
    if allow_root and value in {"", "."}:
        return ""
    relative = Path(value)
    if (
        any(
            part.startswith(".") or part in {"_sources", "node_modules", "__pycache__", "venv"}
            for part in relative.parts
        )
        or ".sync-conflict-" in value
    ):
        raise ValueError("path must name a visible vault entry")
    target = resolve_vault_file(vault, relative)
    current = vault
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symlink paths are not supported")
    return target.relative_to(vault).as_posix()


def _arguments(payload: dict[str, Any]) -> str:
    """Embed JSON as data, including object keys, rather than executable JavaScript."""
    return "const args=JSON.parse(" + json.dumps(json.dumps(payload, allow_nan=False)) + ");"


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected an Obsidian JSON object")
    return value


def _snippet(text: str, query: str) -> str:
    match = re.search(re.escape(query), text, re.IGNORECASE)
    if match is None:
        return text[:2000]
    start = max(0, min(len(text) - 2000, (match.start() + match.end() - 2000) // 2))
    return text[start : start + 2000]


def _grep_report(vault: Path, results: list[_NativeFileMatches], limit: int, query: str) -> dict[str, Any]:
    matches: list[dict[str, str | int]] = []
    for result in results:
        try:
            path = _path(vault, result.file)
        except ValueError:
            continue
        for match in result.matches:
            if len(matches) == limit:
                return {"matches": matches, "truncated": True}
            matches.append({"path": path, "line": match.line, "text": _snippet(match.text, query)})
    return {"matches": matches, "truncated": len(results) >= limit}


def _recent_report(vault: Path, value: object, limit: int) -> dict[str, Any]:
    report = _NativeRecentReport.model_validate(value, strict=True)
    notes = []
    has_more = report.has_more or len(report.notes) > limit
    for note in report.notes[:limit]:
        try:
            path = _path(vault, note.path)
        except ValueError:
            has_more = True
            continue
        notes.append({**note.model_dump(), "path": path})
    return {"notes": notes, "has_more": has_more}


def register_native_tools(server: FastMCP, vault: Path, file_lock: LockType) -> None:
    """Register seven app-backed operations against one configured vault."""
    # NOTE: docs/MCP.md, App-backed tools, documents native contracts and discovery bounds.
    native = NativeObsidian(vault)

    async def run(command: str, *arguments: str) -> str:
        return await asyncio.to_thread(
            run_vault_mutation, file_lock, lambda: asyncio.run(native.run(command, *arguments))
        )

    async def run_json(command: str, *arguments: str) -> object:
        return await asyncio.to_thread(
            run_vault_mutation, file_lock, lambda: asyncio.run(native.run_json(command, *arguments))
        )

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_append(
        path: str, content: Annotated[str, Field(min_length=1)], inline: bool = False
    ) -> dict[str, str]:
        """Append through Obsidian; inline disables its automatic leading newline."""
        path = _path(vault, path)
        arguments = [f"path={path}", f"content={content}"]
        if inline:
            arguments.append("inline")
        await run("append", *arguments)
        return {"path": path, "status": "appended"}

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_frontmatter(path: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read native properties or merge fields through processFrontMatter; native YAML formatting applies."""
        path = _path(vault, path)
        if not updates:
            return _mapping(await run_json("properties", f"path={path}", "format=json"))
        code = (
            "(async()=>{"
            + _arguments({"path": path, "updates": updates})
            + "const file=app.vault.getFileByPath(args.path);"
            "if(!file)throw new Error('File not found');let result;"
            "await app.fileManager.processFrontMatter(file,fm=>{"
            "for(const [key,value] of Object.entries(args.updates))"
            "Object.defineProperty(fm,key,{value,enumerable:true,writable:true,configurable:true});"
            "result=fm;});return JSON.stringify(result);})()"
        )
        return _mapping(await run_json("eval", f"code={code}"))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_recent(
        n: Annotated[int, Field(ge=1, le=500)] = 10, path_filter: str = ""
    ) -> dict[str, Any]:
        """List visible Markdown files by native modified time; paths break ties."""
        path_filter = _path(vault, path_filter, allow_root=True)
        code = (
            "(()=>{"
            + _arguments({"n": n, "folder": path_filter})
            + _VISIBLE_JS
            + "const files=app.vault.getMarkdownFiles().filter(f=>visible(f.path)"
            "&&(!args.folder||f.path.startsWith(args.folder+'/')))"
            ".sort((a,b)=>b.stat.mtime-a.stat.mtime||(a.path<b.path?-1:a.path>b.path?1:0));"
            "return JSON.stringify({notes:files.slice(0,args.n).map(f=>"
            "({path:f.path,mtime_ms:f.stat.mtime,size_bytes:f.stat.size})),has_more:files.length>args.n});})()"
        )
        return _recent_report(vault, await run_json("eval", f"code={code}"), n)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_grep(
        query: Annotated[str, Field(min_length=1)],
        path_filter: str = "",
        max_results: Annotated[int, Field(ge=1, le=500)] = 20,
    ) -> dict[str, Any]:
        """Search live content for literal text using native search; return bounded matching lines."""
        path_filter = _path(vault, path_filter, allow_root=True)
        arguments = [f"query={json.dumps(query)}", "format=json", f"limit={max_results}"]
        if path_filter:
            arguments.append(f"path={path_filter}")
        results = _GREP.validate_python(await run_json("search:context", *arguments), strict=True)
        return _grep_report(vault, results, max_results, query)

    @server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    async def vault_info() -> dict[str, str]:
        """Return native vault information for the server's fixed vault."""
        return {"info": await run("vault")}

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_delete(path: str) -> dict[str, str]:
        """Use Obsidian's default trash behavior; permanent deletion is unavailable."""
        path = _path(vault, path)
        await run("delete", f"path={path}")
        return {"path": path, "status": "trashed"}

    @server.tool(annotations=ToolAnnotations(destructiveHint=True, openWorldHint=False))
    async def vault_move(from_path: str, to_path: str, dry_run: bool = False) -> dict[str, Any]:
        """Delegate moves and link updates to Obsidian's settings; dry_run checks native file info only."""
        source = _path(vault, from_path)
        destination = _path(vault, to_path)
        if resolve_vault_file(vault, Path(destination)).exists():
            raise FileExistsError(f"destination already exists: {destination}")
        if dry_run:
            return {
                "from_path": source,
                "to_path": destination,
                "dry_run": True,
                "source_info": await run("file", f"path={source}"),
            }
        await run("move", f"path={source}", f"to={destination}")
        return {"from_path": source, "to_path": destination, "dry_run": False, "status": "moved"}
