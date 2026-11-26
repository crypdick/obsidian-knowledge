"""Bounded vault operations backed by the official Obsidian CLI and app APIs."""

from __future__ import annotations

import asyncio
import json
import re
from _thread import LockType
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, TypeAdapter

from lib.vault_index.obsidian_cli import NativeObsidian
from lib.vault_index.vault_files import resolve_vault_file
from lib.vault_index.vault_listing import VISIBLE_EXCLUDED_NAMES, visible_name


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


ResultLimit = Annotated[int, Field(ge=1, le=500)]
NonemptyText = Annotated[str, Field(min_length=1)]

_GREP = TypeAdapter(list[_NativeFileMatches])
_VISIBLE_JS = (
    "const visible=p=>p.split('/').every(s=>!s.startsWith('.')"
    f"&&!{json.dumps(sorted(VISIBLE_EXCLUDED_NAMES))}.includes(s))"
    "&&!p.includes('.sync-conflict-');"
)


def run_vault_mutation[T](lock: LockType, operation: Callable[[], T]) -> T:
    """Keep the shared lock until worker completion, including request cancellation."""
    with lock:
        return operation()


def _check_destination(vault: Path, destination: str) -> None:
    if resolve_vault_file(vault, Path(destination)).exists():
        raise FileExistsError(f"destination already exists: {destination}")


def visible_vault_path(vault: Path, value: str, *, allow_root: bool = False) -> str:
    if allow_root and value in {"", "."}:
        return ""
    relative = Path(value)
    if any(not visible_name(part) for part in relative.parts):
        raise ValueError("path must name a visible vault entry")
    target = resolve_vault_file(vault, relative)
    current = vault
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symlink paths are not supported")
    return target.relative_to(vault).as_posix()


def restricted_vault_path(vault: Path, value: str) -> str:
    """Keep agent-managed file operations outside generated and protected areas."""
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise ValueError("invalid vault path")
    relative = visible_vault_path(vault, value)
    parents = Path(relative).parents
    protected = {
        Path("wiki/wiki"),
        Path("wiki/Utility"),
        Path("Utility/obsidian-knowledge/reports/archive"),
    }
    if "automation-memory" in Path(relative).parts or any(
        path == Path(relative) or path in parents for path in protected
    ):
        raise ValueError("path must name an unprotected vault entry")
    return relative


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
            path = visible_vault_path(vault, result.file)
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
            path = visible_vault_path(vault, note.path)
        except ValueError:
            has_more = True
            continue
        notes.append({**note.model_dump(), "path": path})
    return {"notes": notes, "has_more": has_more}


class NativeVault:
    """Run fixed app operations with the caller's mutation lock and index notifier."""

    def __init__(self, vault: Path, file_lock: LockType, refresh: Callable[[list[str]], Awaitable[str]]):
        self.vault = vault
        self.native = NativeObsidian(vault)
        self.file_lock = file_lock
        self.refresh = refresh

    async def _mutate(self, command: str, *arguments: str) -> str:
        return await asyncio.to_thread(
            run_vault_mutation, self.file_lock, lambda: asyncio.run(self.native.run(command, *arguments))
        )

    async def _mutate_json(self, command: str, *arguments: str) -> object:
        return await asyncio.to_thread(
            run_vault_mutation, self.file_lock, lambda: asyncio.run(self.native.run_json(command, *arguments))
        )

    async def frontmatter(self, path: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read native properties or merge fields through processFrontMatter; native YAML formatting applies."""
        path = visible_vault_path(self.vault, path)
        if not updates:
            return _mapping(await self.native.run_json("properties", f"path={path}", "format=json"))
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
        return _mapping(await self._mutate_json("eval", f"code={code}"))

    async def recent(self, n: ResultLimit = 10, path_filter: str = "") -> dict[str, Any]:
        """List visible Markdown files by native modified time; paths break ties."""
        path_filter = visible_vault_path(self.vault, path_filter, allow_root=True)
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
        return _recent_report(self.vault, await self.native.run_json("eval", f"code={code}"), n)

    async def grep(
        self,
        query: NonemptyText,
        path_filter: str = "",
        max_results: ResultLimit = 20,
    ) -> dict[str, Any]:
        """Search live content for literal text using native search; return bounded matching lines."""
        path_filter = visible_vault_path(self.vault, path_filter, allow_root=True)
        arguments = [f"query={json.dumps(query)}", "format=json", f"limit={max_results}"]
        if path_filter:
            arguments.append(f"path={path_filter}")
        results = _GREP.validate_python(await self.native.run_json("search:context", *arguments), strict=True)
        return _grep_report(self.vault, results, max_results, query)

    async def info(self) -> dict[str, str]:
        """Return native vault information for the server's fixed vault."""
        return {"info": await self.native.run("vault")}

    async def delete(self, path: str) -> dict[str, str]:
        """Use Obsidian's default trash behavior; permanent deletion is unavailable."""
        path = visible_vault_path(self.vault, path)
        await self._mutate("delete", f"path={path}")
        return {"path": path, "status": "trashed", "index": await self.refresh([path])}

    async def move(self, from_path: str, to_path: str, dry_run: bool = False) -> dict[str, Any]:
        """Delegate moves and link updates to Obsidian's settings; dry_run checks native file info only."""
        source = visible_vault_path(self.vault, from_path)
        destination = visible_vault_path(self.vault, to_path)

        if dry_run:
            _check_destination(self.vault, destination)
            return {
                "from_path": source,
                "to_path": destination,
                "dry_run": True,
                "source_info": await self.native.run("file", f"path={source}"),
            }

        def move() -> str:
            _check_destination(self.vault, destination)
            return asyncio.run(self.native.run("move", f"path={source}", f"to={destination}"))

        await asyncio.to_thread(run_vault_mutation, self.file_lock, move)
        return {
            "from_path": source,
            "to_path": destination,
            "dry_run": False,
            "status": "moved",
            "index": await self.refresh([source, destination]),
        }
