"""memweave/cli.py — Shell-first CLI for the memweave memory library."""

from __future__ import annotations

import asyncio
import dataclasses
import json as _json
import sys
from pathlib import Path
from typing import Any

import click

from obsidian_knowledge_vendor.memweave import __version__
from obsidian_knowledge_vendor.memweave.config import EmbeddingConfig, MemoryConfig
from obsidian_knowledge_vendor.memweave.exceptions import MemWeaveError
from obsidian_knowledge_vendor.memweave.store import MemWeave
from obsidian_knowledge_vendor.memweave.types import FileInfo, IndexResult, SearchResult


def _make_config(
    workspace: str,
    embedding_model: str | None = None,
    quiet: bool = False,
    snippet_chars: int | None = None,
) -> MemoryConfig:
    """Construct a MemoryConfig for CLI use.

    Workspace is resolved to absolute so that relative_path() works correctly
    when add() and index() both compute workspace-relative DB keys.
    Progress output is shown by default; pass quiet=True to suppress it.
    """
    cfg = MemoryConfig(workspace_dir=str(Path(workspace).resolve()), progress=not quiet)
    if embedding_model:
        cfg = dataclasses.replace(cfg, embedding=EmbeddingConfig(model=embedding_model))
    if snippet_chars is not None:
        cfg = dataclasses.replace(
            cfg, query=dataclasses.replace(cfg.query, snippet_max_chars=snippet_chars)
        )
    return cfg


def _handle_error(exc: Exception) -> None:
    click.echo(f"Error: {exc}", err=True)
    sys.exit(1)


@click.group()
@click.version_option(version=__version__, prog_name="memweave")
def cli() -> None:
    """memweave — agent memory you can read, search, and git diff."""


# ── shared output ──────────────────────────────────────────────────────────────


def _print_index_result(result: IndexResult) -> None:
    click.echo(f"Files scanned:        {result.files_scanned}")
    click.echo(f"Files indexed:        {result.files_indexed}")
    click.echo(f"Files skipped:        {result.files_skipped}")
    click.echo(f"Files deleted:        {result.files_deleted}")
    click.echo(f"Chunks created:       {result.chunks_created}")
    click.echo(f"Embeddings cached:    {result.embeddings_cached}")
    click.echo(f"Embeddings computed:  {result.embeddings_computed}")
    click.echo(f"Duration:             {result.duration_ms:.0f}ms")


# ── index ──────────────────────────────────────────────────────────────────────


async def _index_async(
    workspace: str, force: bool, embedding_model: str | None, quiet: bool
) -> None:
    async with MemWeave(_make_config(workspace, embedding_model, quiet)) as mem:
        result = await mem.index(force=force)
    _print_index_result(result)


@cli.command()
@click.option("--workspace", "-w", default=".", show_default=True, help="Root workspace directory.")
@click.option("--force", is_flag=True, default=False, help="Re-index all files regardless of hash.")
@click.option(
    "--embedding-model", default=None, help="Embedding model (e.g. text-embedding-3-small)."
)
@click.option("--quiet", "-q", is_flag=True, default=False, help="Suppress progress output.")
def index(workspace: str, force: bool, embedding_model: str | None, quiet: bool) -> None:
    """Index all markdown files in the workspace."""
    try:
        asyncio.run(_index_async(workspace, force, embedding_model, quiet))
    except MemWeaveError as exc:
        _handle_error(exc)


# ── add ────────────────────────────────────────────────────────────────────────


async def _add_async(
    file: str, workspace: str, force: bool, embedding_model: str | None, quiet: bool
) -> None:
    # Resolve to absolute so store.py doesn't re-join it with workspace_dir.
    # Paths typed in the shell are relative to CWD, not to --workspace.
    abs_file = str(Path(file).resolve())
    async with MemWeave(_make_config(workspace, embedding_model, quiet)) as mem:
        result = await mem.add(abs_file, force=force)
    _print_index_result(result)


@cli.command()
@click.argument("file")
@click.option("--workspace", "-w", default=".", show_default=True, help="Root workspace directory.")
@click.option("--force", is_flag=True, default=False, help="Re-index even if hash unchanged.")
@click.option(
    "--embedding-model", default=None, help="Embedding model (e.g. text-embedding-3-small)."
)
@click.option("--quiet", "-q", is_flag=True, default=False, help="Suppress progress output.")
def add(file: str, workspace: str, force: bool, embedding_model: str | None, quiet: bool) -> None:
    """Index a single markdown file."""
    try:
        asyncio.run(_add_async(file, workspace, force, embedding_model, quiet))
    except FileNotFoundError:
        click.echo(f"Error: file not found: {file}", err=True)
        sys.exit(1)
    except MemWeaveError as exc:
        _handle_error(exc)


# ── files ──────────────────────────────────────────────────────────────────────


def _print_files(files: list[FileInfo]) -> None:
    if not files:
        click.echo("No files indexed.")
        return

    path_w = max(len("Path"), max(len(f.path) for f in files))
    source_w = max(len("Source"), max(len(f.source) for f in files))

    header = f"{'Path':<{path_w}}  {'Source':<{source_w}}  {'Chunks':>6}  Evergreen"
    click.echo(header)
    click.echo("─" * len(header))
    for f in files:
        click.echo(
            f"{f.path:<{path_w}}  {f.source:<{source_w}}  {f.chunks:>6}  {'yes' if f.is_evergreen else 'no'}"
        )


async def _files_async(workspace: str, source: str | None, json_output: bool) -> None:
    async with MemWeave(_make_config(workspace, quiet=json_output)) as mem:
        all_files = await mem.files()

    filtered = [f for f in all_files if source is None or f.source == source]

    if json_output:
        click.echo(_json.dumps([dataclasses.asdict(f) for f in filtered], indent=2))
        return

    _print_files(filtered)


@cli.command()
@click.option("--workspace", "-w", default=".", show_default=True, help="Root workspace directory.")
@click.option("--source", default=None, help="Filter by source label (e.g. memory, sessions).")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output as JSON.")
def files(workspace: str, source: str | None, json_output: bool) -> None:
    """List all indexed files with metadata."""
    try:
        asyncio.run(_files_async(workspace, source, json_output))
    except MemWeaveError as exc:
        _handle_error(exc)


# ── search ─────────────────────────────────────────────────────────────────────


def _print_search_results(results: list[SearchResult]) -> None:
    if not results:
        click.echo("No results found.")
        return

    path_w = max(len("Path"), max(len(r.path) for r in results))
    source_w = max(len("Source"), max(len(r.source) for r in results))
    lines_strs = [f"{r.start_line}–{r.end_line}" for r in results]
    lines_w = max(len("Lines"), max(len(s) for s in lines_strs))

    header = (
        f"{'Score':>5}  {'Path':<{path_w}}  {'Lines':<{lines_w}}  {'Source':<{source_w}}  Preview"
    )
    click.echo(header)
    click.echo("─" * len(header))
    for r, lines_str in zip(results, lines_strs):
        snippet = r.snippet.replace("\n", " ")
        if len(snippet) > 60:
            snippet = snippet[:60] + "…"
        click.echo(
            f"{r.score:>5.2f}  {r.path:<{path_w}}  {lines_str:<{lines_w}}  {r.source:<{source_w}}  {snippet}"
        )


async def _search_async(
    query: str,
    workspace: str,
    max_results: int | None,
    min_score: float | None,
    strategy: str | None,
    source_filter: str | None,
    mmr_lambda: float | None,
    decay_half_life_days: float | None,
    snippet_chars: int | None,
    embedding_model: str | None,
    json_output: bool,
) -> None:
    cfg = _make_config(workspace, embedding_model, quiet=json_output, snippet_chars=snippet_chars)
    async with MemWeave(cfg) as mem:
        kwargs: dict[str, Any] = {}
        if mmr_lambda is not None:
            kwargs["mmr_lambda"] = mmr_lambda
        if decay_half_life_days is not None:
            kwargs["decay_half_life_days"] = decay_half_life_days
        results = await mem.search(
            query,
            max_results=max_results,
            min_score=min_score,
            strategy=strategy,
            source_filter=source_filter,
            **kwargs,
        )

    if json_output:
        click.echo(_json.dumps([dataclasses.asdict(r) for r in results], indent=2))
        return

    _print_search_results(results)


@cli.command()
@click.argument("query")
@click.option("--workspace", "-w", default=".", show_default=True, help="Root workspace directory.")
@click.option(
    "--max-results", default=None, type=int, help="Maximum results to return (default: 6)."
)
@click.option(
    "--min-score", default=None, type=float, help="Minimum relevance score 0–1 (default: 0.35)."
)
@click.option(
    "--strategy",
    default=None,
    type=click.Choice(["hybrid", "vector", "keyword"]),
    help="Search strategy (default: hybrid).",
)
@click.option(
    "--source-filter", default=None, help="Restrict to one source label (e.g. memory, sessions)."
)
@click.option(
    "--mmr-lambda",
    default=None,
    type=float,
    help="MMR diversity weight 0–1 (0=diverse, 1=relevant).",
)
@click.option(
    "--decay-half-life-days", default=None, type=float, help="Temporal decay half-life in days."
)
@click.option(
    "--snippet-chars",
    default=None,
    type=int,
    help="Max characters in result snippet (default: 700).",
)
@click.option(
    "--embedding-model", default=None, help="Embedding model (e.g. text-embedding-3-small)."
)
@click.option("--json", "json_output", is_flag=True, default=False, help="Output as JSON.")
def search(
    query: str,
    workspace: str,
    max_results: int | None,
    min_score: float | None,
    strategy: str | None,
    source_filter: str | None,
    mmr_lambda: float | None,
    decay_half_life_days: float | None,
    snippet_chars: int | None,
    embedding_model: str | None,
    json_output: bool,
) -> None:
    """Search the memory index."""
    try:
        asyncio.run(
            _search_async(
                query,
                workspace,
                max_results,
                min_score,
                strategy,
                source_filter,
                mmr_lambda,
                decay_half_life_days,
                snippet_chars,
                embedding_model,
                json_output,
            )
        )
    except MemWeaveError as exc:
        _handle_error(exc)


# ── stats ──────────────────────────────────────────────────────────────────────


async def _stats_async(workspace: str, json_output: bool) -> None:
    async with MemWeave(_make_config(workspace, quiet=json_output)) as mem:
        status = await mem.status()

    if json_output:
        click.echo(_json.dumps(dataclasses.asdict(status), indent=2))
        return

    cache_max = (
        str(status.cache_max_entries) if status.cache_max_entries is not None else "unlimited"
    )

    click.echo("──────────────────────────────────────")
    click.echo(f"  Workspace:        {status.workspace_dir}")
    click.echo(f"  DB path:          {status.db_path}")
    click.echo(f"  Search mode:      {status.search_mode}")
    click.echo(f"  Provider:         {status.provider}")
    click.echo(f"  Model:            {status.model or '(none)'}")
    click.echo("")
    click.echo(f"  Files:            {status.files}")
    click.echo(f"  Chunks:           {status.chunks}")
    click.echo(f"  Cache entries:    {status.cache_entries}")
    click.echo(f"  Cache max:        {cache_max}")
    click.echo(f"  Dirty:            {'yes' if status.dirty else 'no'}")
    click.echo(f"  Watcher active:   {'yes' if status.watcher_active else 'no'}")
    click.echo(f"  FTS available:    {'yes' if status.fts_available else 'no'}")
    click.echo(f"  Vector available: {'yes' if status.vector_available else 'no'}")

    if status.dirty:
        click.echo("\n⚠ Index is stale — run: memweave index")


@cli.command()
@click.option("--workspace", "-w", default=".", show_default=True, help="Root workspace directory.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output as JSON.")
def stats(workspace: str, json_output: bool) -> None:
    """Show memory index statistics."""
    try:
        asyncio.run(_stats_async(workspace, json_output))
    except MemWeaveError as exc:
        _handle_error(exc)
