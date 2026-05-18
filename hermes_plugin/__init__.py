"""Obsidian vault memory provider for Hermes Agent CLI.

Wraps the shared lib/vault_index/ retrieval into a MemoryProvider implementation.
Activated via ``memory.provider: obsidian-vault`` in ~/.hermes/config.yaml.

Required env: OBSIDIAN_VAULT_ROOT — absolute path to the vault.

Architecture note: lib/vault_index requires memweave which requires Python 3.12+.
Hermes runs Python 3.11. This provider bridges to the uv venv via subprocess
to avoid the version mismatch.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


_VAULT_SEARCH_TIMEOUT_SECONDS = 60.0

from agent.memory_provider import MemoryProvider  # type: ignore


# Path to the uv venv Python that has memweave + lib/vault_index installed
_PLUGIN_REPO = Path(os.environ.get(
    "OBSIDIAN_KNOWLEDGE_ROOT",
    str(Path.home() / "src" / "PERSONAL" / "obsidian-knowledge"),
))
_UV_PYTHON = _PLUGIN_REPO / ".venv" / "bin" / "python"


def _run_vault_search(query: str, top_k: int | None = None,
                      min_score: float | None = None,
                      override_digest_filter: bool = False) -> list[dict[str, Any]]:
    """Run vault_search via uv venv subprocess, return list of {score, path}."""
    script = (
        "import asyncio, json, sys, os\n"
        f"sys.path.insert(0, {str(_PLUGIN_REPO)!r})\n"
        "from pathlib import Path\n"
        "from lib.vault_index.config import load_config\n"
        "from lib.vault_index.indexer import Indexer, default_cache_dir\n"
        "vault = Path(os.environ['OBSIDIAN_VAULT_ROOT'])\n"
        "cfg_path = vault / '.claude' / 'obsidian-knowledge.yaml'\n"
        "cfg = load_config(cfg_path)\n"
        "cache = default_cache_dir(vault)\n"
        "idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)\n"
        f"hits = idx.search({query!r}, top_k={top_k!r}, min_score={min_score!r}, override_digest_filter={override_digest_filter!r})\n"
        "print(json.dumps([{'score': h.score, 'path': h.path} for h in hits]))\n"
        "sys.stdout.flush()\n"
        "os._exit(0)\n"  # bypass daemon thread cleanup hang (asyncio threads don't exit cleanly)
    )
    result = subprocess.run(
        [str(_UV_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        cwd=str(_PLUGIN_REPO),
        stdin=subprocess.DEVNULL,  # prevent watchfiles from blocking on stdin
        timeout=_VAULT_SEARCH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"vault_search failed: {result.stderr}")
    return json.loads(result.stdout.strip())


def _run_build_primer(vault_root: str, plugin_root: str) -> str:
    """Get primer text via uv venv subprocess."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, {plugin_root!r})\n"
        "from pathlib import Path\n"
        "from lib.vault_index.primer import build_primer\n"
        f"print(build_primer(Path({vault_root!r}), Path({plugin_root!r})))\n"
    )
    result = subprocess.run(
        [str(_UV_PYTHON), "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_PLUGIN_REPO),
        stdin=subprocess.DEVNULL,  # prevent watchfiles from blocking on stdin
    )
    if result.returncode != 0:
        return "You are operating under the obsidian-knowledge harness."
    return result.stdout.strip()


# Module-level ref so atexit handler can call shutdown() even on crash.
_last_active_provider: "ObsidianVaultProvider | None" = None


def _atexit_shutdown() -> None:
    if _last_active_provider is not None:
        try:
            _last_active_provider.shutdown()
        except Exception:
            pass


atexit.register(_atexit_shutdown)


class ObsidianVaultProvider(MemoryProvider):
    """Hermes MemoryProvider backed by an Obsidian vault via memweave retrieval."""

    NUDGE = (
        "\n\nThis is your long-term memory. Write learnings to the wiki as you go. "
        "See the obsidian-knowledge skill for entry conventions. "
        "Use vault_search for more results."
    )

    VAULT_SEARCH_SCHEMA: dict[str, Any] = {
        "name": "vault_search",
        "description": (
            "Hybrid BM25 + dense semantic search over the Obsidian vault. "
            "Returns a ranked list of {score, path} hits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language or keyword query."},
                "top_k": {"type": "integer", "description": "Max results. Defaults to config value."},
                "min_score": {"type": "number", "description": "Drop hits below this score (post-rescale)."},
                "override_digest_filter": {
                    "type": "boolean",
                    "description": (
                        "If true, bypass the digest allow/deny lists and search the full "
                        "indexed corpus. Use for power-search into Journal, Inbox, etc."
                    ),
                },
            },
            "required": ["query"],
        },
    }

    @property
    def name(self) -> str:
        return "obsidian-vault"

    def is_available(self) -> bool:
        root = os.environ.get("OBSIDIAN_VAULT_ROOT")
        if not root:
            return False
        vault = Path(root)
        if not vault.is_dir():
            return False
        if not (vault / ".claude" / "obsidian-knowledge.yaml").exists():
            return False
        if not _UV_PYTHON.exists():
            return False
        # Verify uv venv has memweave
        result = subprocess.run(
            [str(_UV_PYTHON), "-c", "import memweave"],
            capture_output=True,
        )
        return result.returncode == 0

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        global _last_active_provider

        self.session_id = session_id
        self.vault_root = str(os.environ["OBSIDIAN_VAULT_ROOT"])
        self.plugin_root = str(_PLUGIN_REPO)

        self.injected_paths_this_session: set[str] = set()

        # Threading state for queue_prefetch
        import threading
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Any = None
        self._prefetch_cache: list[Any] = []

        # Threading state for sync_turn
        self._sync_thread: Any = None
        self._sync_pending: bool = False

        _last_active_provider = self

    def shutdown(self) -> None:
        pass

    def system_prompt_block(self) -> str:
        primer = _run_build_primer(self.vault_root, self.plugin_root)
        directive = (
            "\n\n"
            "On your first turn, call the `skill_view` tool with "
            "`name=\"obsidian-knowledge\"` to load the skill instructions. "
            "Re-load it after a context compaction if you find yourself "
            "uncertain about vault conventions."
        )
        return primer + directive

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Consume a ready queued result without blocking agent startup."""
        if not query:
            return ""

        hits: list[Any] = []
        if self._prefetch_thread is not None:
            self._prefetch_thread.join(timeout=0.0)
            if not self._prefetch_thread.is_alive():
                with self._prefetch_lock:
                    hits = self._prefetch_cache
                    self._prefetch_cache = []
                self._prefetch_thread = None

        fresh = [h for h in hits if h["path"] not in self.injected_paths_this_session]
        for h in fresh:
            self.injected_paths_this_session.add(h["path"])

        lines = ["Top semantic vault hits:"]
        for h in fresh:
            lines.append(f"  {h['score']:.1f}  {h['path']}")
        if len(lines) == 1:
            return self.NUDGE.lstrip()
        return "\n".join(lines) + self.NUDGE

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Compression is about to drop earlier turns; allow paths to be re-injected."""
        self.injected_paths_this_session.clear()
        return ""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [self.VAULT_SEARCH_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if tool_name != "vault_search":
            raise NotImplementedError(f"Unknown tool: {tool_name}")
        try:
            hits = _run_vault_search(
                query=args["query"],
                top_k=args.get("top_k"),
                min_score=args.get("min_score"),
                override_digest_filter=bool(args.get("override_digest_filter", False)),
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(hits)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Run search in background; result cached for next prefetch() call."""
        import threading
        if self._prefetch_thread is not None and self._prefetch_thread.is_alive():
            return

        def _run() -> None:
            try:
                hits = _run_vault_search(query)
            except Exception:
                hits = []
            with self._prefetch_lock:
                self._prefetch_cache = hits

        self._prefetch_thread = threading.Thread(target=_run, daemon=False)
        self._prefetch_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Re-index after each turn. Background thread; debounced."""
        import threading
        if self._sync_thread is not None and self._sync_thread.is_alive():
            self._sync_pending = True
            return

        plugin_root = self.plugin_root
        vault_root = self.vault_root
        uv_python = str(_UV_PYTHON)

        def _run() -> None:
            try:
                script = (
                    "import sys, os\n"
                    f"sys.path.insert(0, {plugin_root!r})\n"
                    "from pathlib import Path\n"
                    "from lib.vault_index.config import load_config\n"
                    "from lib.vault_index.indexer import Indexer, default_cache_dir\n"
                    f"vault = Path({vault_root!r})\n"
                    "cfg = load_config(vault / '.claude' / 'obsidian-knowledge.yaml')\n"
                    "cache = default_cache_dir(vault)\n"
                    "idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)\n"
                    "idx.sync()\n"
                    "idx.row_count()\n"
                    "os._exit(0)\n"  # bypass asyncio daemon thread cleanup hang
                )
                subprocess.run(
                    [uv_python, "-c", script],
                    capture_output=True,
                    env=os.environ.copy(),
                    cwd=plugin_root,
                    stdin=subprocess.DEVNULL,  # prevent watchfiles blocking on stdin
                    timeout=_VAULT_SEARCH_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("sync_turn failed: %s", exc)
            finally:
                if self._sync_pending:
                    self._sync_pending = False

        self._sync_thread = threading.Thread(target=_run, daemon=False)
        self._sync_thread.start()
