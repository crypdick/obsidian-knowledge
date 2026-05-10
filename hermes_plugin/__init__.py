"""Obsidian vault memory provider for Hermes Agent CLI.

Wraps the shared lib/vault_index/ retrieval into a MemoryProvider implementation.
Activated via ``memory.provider: obsidian-vault`` in ~/.hermes/config.yaml.

Required env: OBSIDIAN_VAULT_ROOT — absolute path to the vault.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider  # type: ignore

from lib.vault_index import (
    Indexer,
    VaultIndexConfig,
    build_primer,
    load_config,
)

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
        try:
            import memweave  # noqa: F401
        except ImportError:
            return False
        return True

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        global _last_active_provider

        self.session_id = session_id
        self.vault_root = Path(os.environ["OBSIDIAN_VAULT_ROOT"])
        self.plugin_root = Path(os.environ.get(
            "OBSIDIAN_KNOWLEDGE_ROOT",
            str(Path.home() / "src" / "PERSONAL" / "obsidian-knowledge"),
        ))
        cfg_path = self.vault_root / ".claude" / "obsidian-knowledge.yaml"
        self.config: VaultIndexConfig = load_config(cfg_path)
        cache = self.vault_root / ".config" / "obsidian-knowledge" / "cache"
        self.indexer = Indexer(
            vault_root=self.vault_root, cache_dir=cache, config=self.config,
        )
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
        # memweave write queue flush handled by Store on GC; nothing to do here.
        pass

    def system_prompt_block(self) -> str:
        primer = build_primer(self.vault_root, self.plugin_root)
        directive = (
            "\n\n"
            "On your first turn, call the `skill_view` tool with "
            "`name=\"obsidian-knowledge\"` to load the skill instructions. "
            "Re-load it after a context compaction if you find yourself "
            "uncertain about vault conventions."
        )
        return primer + directive

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Consume queued result if available; else search synchronously."""
        if not query:
            return ""

        hits: list[Any] = []
        if self._prefetch_thread is not None:
            self._prefetch_thread.join(timeout=3.0)
            with self._prefetch_lock:
                hits = self._prefetch_cache
                self._prefetch_cache = []
            self._prefetch_thread = None

        if not hits:
            hits = self.indexer.search(query)

        fresh = [h for h in hits if h.path not in self.injected_paths_this_session]
        for h in fresh:
            self.injected_paths_this_session.add(h.path)

        lines = ["Top semantic vault hits:"]
        for h in fresh:
            lines.append(f"  {h.score:.1f}  {h.path}")
        if len(lines) == 1:
            # No fresh hits — header alone is misleading. Drop it; keep nudge only.
            return self.NUDGE.lstrip()
        return "\n".join(lines) + self.NUDGE

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Compression is about to drop earlier turns; allow paths to be re-injected."""
        self.injected_paths_this_session.clear()
        return ""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [self.VAULT_SEARCH_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        import json
        if tool_name != "vault_search":
            raise NotImplementedError(f"Unknown tool: {tool_name}")
        hits = self.indexer.search(
            query=args["query"],
            top_k=args.get("top_k"),
            min_score=args.get("min_score"),
            override_digest_filter=bool(args.get("override_digest_filter", False)),
        )
        return json.dumps([{"score": h.score, "path": h.path} for h in hits])

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Run search in background; result cached for next prefetch() call."""
        import threading

        def _run() -> None:
            try:
                hits = self.indexer.search(query)
            except Exception:
                hits = []
            with self._prefetch_lock:
                self._prefetch_cache = hits

        self._prefetch_thread = threading.Thread(target=_run, daemon=True)
        self._prefetch_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Re-index after each turn. Background thread; debounce by skipping
        if a previous sync is still running.
        """
        import threading
        if self._sync_thread is not None and self._sync_thread.is_alive():
            self._sync_pending = True
            return

        def _run() -> None:
            try:
                self.indexer.sync()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("sync_turn failed: %s", exc)
            finally:
                if self._sync_pending:
                    self._sync_pending = False
                    self.indexer.sync()

        self._sync_thread = threading.Thread(target=_run, daemon=True)
        self._sync_thread.start()
