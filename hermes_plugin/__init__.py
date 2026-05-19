"""Obsidian vault memory provider for Hermes Agent CLI.

Wraps the shared lib/vault_index/ retrieval into a MemoryProvider implementation.
Activated via ``memory.provider: obsidian-knowledge`` in ~/.hermes/config.yaml.

Required env: OBSIDIAN_VAULT_ROOT — absolute path to the vault.

Architecture note: lib/vault_index requires memweave which requires Python 3.12+.
Hermes runs Python 3.11. This provider bridges to the uv venv via subprocess
to avoid the version mismatch.
"""
from __future__ import annotations

import atexit
import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any


_VAULT_SEARCH_TIMEOUT_SECONDS = 60.0

from agent.memory_provider import MemoryProvider  # type: ignore


# Path to the installed plugin root. OBSIDIAN_KNOWLEDGE_ROOT is a dev override
# for working directly from a source checkout.
_DEFAULT_PLUGIN_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_REPO = Path(os.environ.get("OBSIDIAN_KNOWLEDGE_ROOT", str(_DEFAULT_PLUGIN_REPO)))
_UV_PYTHON = _PLUGIN_REPO / ".venv" / "bin" / "python"
_HOOKS_DIR = _PLUGIN_REPO / "hooks"

_REMINDER_LOCK = threading.Lock()
_PENDING_REMINDERS: dict[str, list[str]] = {}
_SESSION_WIKI_NEW_FOLDERS: dict[str, set[str]] = {}
_SESSION_WIKI_INDEX_FOLDERS: dict[str, set[str]] = {}

_REFLECT_REMINDER = (
    "Step back: any friction worth feeding back into the harness, or insight "
    "worth saving to the knowledge base? Hermes auto-invokes improve-harness "
    "when friction patterns are detected. If knowledge worth preserving, use the "
    "`remember-conversations` skill."
)

_STOP_REMINDER = (
    "Previous turn ended under the obsidian-knowledge harness. If it produced "
    "edits, decisions, discoveries, or durable context, file a terse changelog "
    "entry and any useful diary/convo/guide note in the vault wiki. If nothing "
    "worth preserving happened, carry on."
)


def _python_cmd() -> list[str]:
    """Return a Python command that can import the plugin's uv-managed deps."""
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_PYTHON")
    if override:
        return [override]
    if _UV_PYTHON.exists():
        return [str(_UV_PYTHON)]
    return ["uv", "run", "python"]


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
        [*_python_cmd(), "-c", script],
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
        [*_python_cmd(), "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_PLUGIN_REPO),
        stdin=subprocess.DEVNULL,  # prevent watchfiles from blocking on stdin
    )
    if result.returncode != 0:
        return "You are operating under the obsidian-knowledge harness."
    return result.stdout.strip()


def _import_hookslib() -> None:
    """Make the repo hook helpers importable inside Hermes's plugin process."""
    hooks_dir = str(_HOOKS_DIR)
    if hooks_dir not in sys.path:
        sys.path.insert(0, hooks_dir)


def _session_key(session_id: str = "", task_id: str = "") -> str:
    return session_id or task_id or "default"


def _queue_reminder(key: str, message: str) -> None:
    with _REMINDER_LOCK:
        bucket = _PENDING_REMINDERS.setdefault(key, [])
        if message not in bucket:
            bucket.append(message)


def _drain_reminders(key: str) -> list[str]:
    with _REMINDER_LOCK:
        reminders = _PENDING_REMINDERS.pop(key, [])
        if key != "default":
            reminders.extend(_PENDING_REMINDERS.pop("default", []))
        return reminders


def _with_workdir(workdir: str | None):
    """Temporarily switch cwd for rules that interpret relative paths."""
    class _Workdir:
        def __enter__(self) -> None:
            self.old_cwd = os.getcwd()
            if workdir:
                os.chdir(os.path.expanduser(workdir))

        def __exit__(self, *_exc: object) -> None:
            os.chdir(self.old_cwd)

    return _Workdir()


def _extract_patch_files(patch_text: str) -> list[tuple[str, str, str]]:
    """Return (operation, path, added_text) tuples from Hermes V4A patch text."""
    files: list[tuple[str, str, str]] = []
    current_op = ""
    current_path = ""
    added: list[str] = []

    def flush() -> None:
        nonlocal current_op, current_path, added
        if current_path:
            files.append((current_op, current_path, "\n".join(added)))
        current_op = ""
        current_path = ""
        added = []

    for line in patch_text.splitlines():
        if line.startswith("*** Add File: "):
            flush()
            current_op = "add"
            current_path = line.removeprefix("*** Add File: ").strip()
            continue
        if line.startswith("*** Update File: "):
            flush()
            current_op = "update"
            current_path = line.removeprefix("*** Update File: ").strip()
            continue
        if line.startswith("*** Delete File: "):
            flush()
            current_op = "delete"
            current_path = line.removeprefix("*** Delete File: ").strip()
            continue
        if current_path and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    flush()
    return files


def _run_protect_rules(tool_name: str, tool_input: dict[str, Any], workdir: str | None = None) -> str | None:
    """Run the existing Claude/Codex vault-protection rules in-process."""
    _import_hookslib()
    module_path = _HOOKS_DIR / "protect-vault.py"
    spec = importlib.util.spec_from_file_location("obsidian_knowledge_protect_vault", module_path)
    if spec is None or spec.loader is None:
        return None
    protect_vault = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = protect_vault
    spec.loader.exec_module(protect_vault)
    vault_root = os.environ.get("OBSIDIAN_VAULT_ROOT")
    if vault_root:
        protect_vault.VAULT_ROOTS = [os.path.abspath(os.path.expanduser(vault_root))]

    if tool_name == "Bash" and protect_vault.ESCAPE_HATCH in tool_input.get("command", ""):
        return None

    with _with_workdir(workdir):
        for rule in protect_vault.RULES:
            reason = rule(tool_name, tool_input)
            if reason:
                return reason
    return None


def _hermes_tool_as_protect_inputs(
    tool_name: str,
    args: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str | None]]:
    """Translate Hermes tool calls into the existing hook input shape."""
    if tool_name == "terminal":
        return [("Bash", {"command": args.get("command", "")}, args.get("workdir"))]
    if tool_name == "write_file":
        return [("Write", {"file_path": args.get("path", ""), "content": args.get("content", "")}, None)]
    if tool_name != "patch":
        return []

    if args.get("mode", "replace") == "patch":
        translated = []
        for op, path, added_text in _extract_patch_files(str(args.get("patch") or "")):
            if op == "add":
                translated.append(("Write", {"file_path": path, "content": added_text}, None))
            else:
                translated.append(("Edit", {"file_path": path, "new_string": added_text}, None))
        return translated

    return [(
        "Edit",
        {"file_path": args.get("path", ""), "new_string": args.get("new_string", "")},
        None,
    )]


def _on_pre_tool_call(
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, str] | None:
    """Hermes pre_tool_call bridge for the existing vault protection rules."""
    if not isinstance(args, dict):
        return None
    for compat_name, compat_input, workdir in _hermes_tool_as_protect_inputs(tool_name, args):
        reason = _run_protect_rules(compat_name, compat_input, workdir=workdir)
        if reason:
            return {"action": "block", "message": reason}
    return None


def _cache_root() -> Path:
    override = os.environ.get("OBSIDIAN_KNOWLEDGE_CACHE_ROOT")
    return Path(override) if override else Path.home() / ".cache" / "obsidian-knowledge"


def _track_wiki_index_state(
    key: str,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
) -> None:
    """Track wiki file edits so Hermes can emit the index-sync nudge."""
    if tool_name not in {"write_file", "patch"}:
        return
    if isinstance(result, str) and '"error"' in result[:200].lower():
        return

    paths: list[str] = []
    if tool_name == "write_file":
        paths = [str(args.get("path") or "")]
    elif args.get("mode", "replace") == "patch":
        paths = [path for _, path, _ in _extract_patch_files(str(args.get("patch") or ""))]
    else:
        paths = [str(args.get("path") or "")]

    with _REMINDER_LOCK:
        new_folders = _SESSION_WIKI_NEW_FOLDERS.setdefault(key, set())
        index_folders = _SESSION_WIKI_INDEX_FOLDERS.setdefault(key, set())
        for path in paths:
            parts = Path(path).parts
            if "wiki" not in parts:
                continue
            wiki_i = parts.index("wiki")
            if len(parts) <= wiki_i + 2:
                continue
            folder = parts[wiki_i + 1]
            basename = parts[-1]
            if basename == "index.md":
                index_folders.add(folder)
            elif basename.endswith(".md"):
                new_folders.add(folder)


def _on_post_tool_call(
    tool_name: str = "",
    args: dict[str, Any] | None = None,
    task_id: str = "",
    session_id: str = "",
    result: Any = None,
    **_: Any,
) -> None:
    """Hermes post_tool_call bridge for reflection and index-sync tracking."""
    if not isinstance(args, dict):
        args = {}
    key = _session_key(session_id, task_id)
    _track_wiki_index_state(key, tool_name, args, result)

    if tool_name != "terminal":
        return
    try:
        _import_hookslib()
        from hookslib import reflect_counter  # type: ignore  # noqa: WPS433

        count = reflect_counter.increment(_cache_root() / key)
        if reflect_counter.should_fire(count):
            _queue_reminder(key, _REFLECT_REMINDER)
    except Exception:
        return


def _on_session_end(
    session_id: str = "",
    task_id: str = "",
    completed: bool = True,
    interrupted: bool = False,
    **_: Any,
) -> None:
    """Queue Stop-hook style reminders for the next Hermes turn."""
    key = _session_key(session_id, task_id)
    if completed and not interrupted:
        _queue_reminder(key, _STOP_REMINDER)

    with _REMINDER_LOCK:
        new_folders = _SESSION_WIKI_NEW_FOLDERS.pop(key, set())
        index_folders = _SESSION_WIKI_INDEX_FOLDERS.pop(key, set())
    unsynced = sorted(new_folders - index_folders)
    if unsynced:
        folders = ", ".join(f"wiki/{folder}/" for folder in unsynced)
        _queue_reminder(
            key,
            "Previous turn created or moved files under "
            f"{folders} without updating the parent index.md. Run "
            "vault-organizer, or update the index(es) manually.",
        )


def _on_pre_llm_call(session_id: str = "", task_id: str = "", **_: Any) -> dict[str, str] | None:
    """Inject queued Hermes hook reminders into the next active turn."""
    reminders = _drain_reminders(_session_key(session_id, task_id))
    if not reminders:
        return None
    return {"context": "\n\n".join(reminders)}


def register(ctx: Any) -> None:
    """Register Hermes plugin hooks that bridge Claude/Codex hook behavior."""
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)


# Module-level ref so atexit handler can call shutdown() even on crash.
_last_active_provider: "ObsidianKnowledgeProvider | None" = None


def _atexit_shutdown() -> None:
    if _last_active_provider is not None:
        try:
            _last_active_provider.shutdown()
        except Exception:
            pass


atexit.register(_atexit_shutdown)


class ObsidianKnowledgeProvider(MemoryProvider):
    """Hermes MemoryProvider backed by the Obsidian knowledge base."""

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

    MEMORY_REDIRECT_SCHEMA: dict[str, Any] = {
        "name": "memory",
        "description": (
            "Disabled built-in Hermes memory tool for this profile. "
            "Returns an error directing agents to use the Obsidian knowledge base instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Ignored; built-in memory is disabled."},
                "target": {"type": "string", "description": "Ignored; built-in memory is disabled."},
                "content": {"type": "string", "description": "Ignored; write durable facts to the vault instead."},
                "old_text": {"type": "string", "description": "Ignored; edit the relevant vault note instead."},
            },
            "required": [],
        },
    }

    @property
    def name(self) -> str:
        return "obsidian-knowledge"

    def is_available(self) -> bool:
        root = os.environ.get("OBSIDIAN_VAULT_ROOT")
        if not root:
            return False
        vault = Path(root)
        if not vault.is_dir():
            return False
        if not (vault / ".claude" / "obsidian-knowledge.yaml").exists():
            return False
        # Verify the plugin dependency environment has memweave.
        try:
            result = subprocess.run(
                [*_python_cmd(), "-c", "import memweave"],
                capture_output=True,
                cwd=str(_PLUGIN_REPO),
            )
        except FileNotFoundError:
            return False
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
        """Return same-turn vault_search results for the current user query."""
        query = (query or "").strip()
        if not query:
            return ""

        hits = _run_vault_search(query)
        if not hits:
            shown_query = query[:80]
            if len(query) > 80:
                shown_query += "..."
            return (
                f"Obsidian memory provider warning: vault_search({shown_query!r}) "
                "returned no hits for the current query. Treat automatic Obsidian "
                "recall as suspect and fix the memory plugin, vault index, digest "
                "filters, or vault access before relying on this memory context."
                + self.NUDGE
            )

        shown_query = query[:80]
        if len(query) > 80:
            shown_query += "..."
        lines = [f"Results for vault_search({shown_query!r}):"]
        for h in hits:
            lines.append(f"  {h['score']:.1f}  {h['path']}")
        return "\n".join(lines) + self.NUDGE

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Compression is about to drop earlier turns; allow paths to be re-injected."""
        self.injected_paths_this_session.clear()
        return ""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [self.VAULT_SEARCH_SCHEMA, self.MEMORY_REDIRECT_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        if tool_name == "memory":
            return json.dumps({
                "success": False,
                "error": (
                    "Built-in Hermes memory is disabled for this profile. "
                    "Use the Obsidian knowledge base instead: update "
                    "wiki/systems/knowledge-base/index.md or a linked vault note, "
                    "and use vault_search/obsidian-knowledge for recall."
                ),
                "replacement": "obsidian-knowledge",
            })
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
        """No-op: prefetch() runs same-turn vault_search to avoid stale memory."""
        return None

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Re-index after each turn. Background thread; debounced."""
        import threading
        if self._sync_thread is not None and self._sync_thread.is_alive():
            self._sync_pending = True
            return

        plugin_root = self.plugin_root
        vault_root = self.vault_root
        python_cmd = _python_cmd()

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
                    [*python_cmd, "-c", script],
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
