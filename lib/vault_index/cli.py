"""CLI entry points for obsidian-knowledge tooling.

# allow: file-length  (CLI surface; decomposition tracked in docs/QUALITY.md)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

import platformdirs
import yaml

from lib.vault_index.models import Hit

DEFAULT_VAULT_INDEX_TEMPLATE = """
# Vault index config — drives memweave retrieval, filtering, and weighting.
# Path patterns are Python regexes evaluated against vault-relative paths.
vault_index:
  # What gets embedded at index time. Skipped paths are invisible to vault_search.
  index:
    allow_regex: []
    deny_regex:
      - "^Journal/"
      - "^Inbox/"
      - "^_sources/"
      - "^\\\\.obsidian/"
      - "^\\\\.config/"
      - "^\\\\.stversions/"
      - "^\\\\.trash/"
      - "^Utility/obsidian-knowledge/cache/"

  # What surfaces in default prefetch digest. Subset of indexed.
  digest:
    allow_regex:
      - "^wiki/"
      - "^.+/convos/"
    deny_regex: []

  # Score multipliers (longest-regex-match wins) applied before top-K truncation.
  weights:
    - regex: "^wiki/"
      multiplier: 1.5
    - regex: "^.+/convos/"
      multiplier: 1.3
    - regex: "^Utility/obsidian-knowledge/changelog/"
      multiplier: 0.6

  default_weight: 1.0
  top_k: 5
  # min_score: null  # uncomment to set a hard cutoff
"""

VAULTS_CONFIG_ENV = "OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG"
APP_NAME = "obsidian-knowledge"
CACHE_ROOT_ENV = "OBSIDIAN_KNOWLEDGE_CACHE_ROOT"
SEARCH_TTL_ENV = "OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS"
DEFAULT_SEARCH_TTL_SECONDS = 30
# Extra time past the signal-based deadline before the watchdog hard-exits.
# Lets the clean SIGALRM/unwind path win when it can; the watchdog only fires
# when the work is wedged in a C call the signal cannot interrupt.
_HARD_TIMEOUT_GRACE_SECONDS = 5
SANDBOX_CACHE_ROOT = Path("/tmp") / "obsidian-knowledge-cache"


class SearchTimeoutError(TimeoutError):
    """Raised when a CLI search exceeds its process-level TTL."""


@contextlib.contextmanager
def search_ttl(seconds: int | None, *, label: str = "search"):
    """Bound CLI searches so stuck retrieval cannot leave orphaned processes.

    Two lines of defense:

    1. ``signal.alarm`` raises :class:`SearchTimeoutError` at the deadline —
       clean and catchable, but only on the main thread and only between Python
       bytecodes.  It cannot interrupt a long C-extension call (e.g. a hung TLS
       read inside an embedding HTTP request), because the pending signal is
       only serviced once control returns to the interpreter.
    2. A daemon watchdog thread force-exits the process a few seconds past the
       deadline if the clean path did not unwind.  This guarantees the process
       dies regardless of where it is stuck, which is what prevents orphaned
       reindex processes from piling up (observed: 255 stuck processes
       accumulating from the hourly cron because a C-level SSL read swallowed
       the SIGALRM and ``--timeout-seconds`` silently never fired).
    """
    if not seconds or seconds <= 0:
        yield
        return

    cancel = threading.Event()

    def _watchdog():
        if not cancel.wait(seconds + _HARD_TIMEOUT_GRACE_SECONDS):
            sys.stderr.write(
                f"{label}: hard timeout after "
                f"{seconds + _HARD_TIMEOUT_GRACE_SECONDS}s — signal-based "
                "timeout did not fire (likely stuck in a C call); force-exiting "
                "to avoid an orphaned process\n"
            )
            sys.stderr.flush()
            os._exit(124)

    watchdog = threading.Thread(target=_watchdog, name="search-ttl-watchdog", daemon=True)
    watchdog.start()

    use_alarm = hasattr(signal, "SIGALRM")
    previous_handler = None
    previous_alarm = 0
    if use_alarm:
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_alarm = signal.alarm(0)

        def _raise_timeout(_signum, _frame):
            raise SearchTimeoutError(f"{label} exceeded {seconds}s TTL")

        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.alarm(seconds)

    try:
        yield
    finally:
        cancel.set()
        if use_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_alarm:
                signal.alarm(previous_alarm)


def search_ttl_seconds() -> int:
    """Return configured search TTL, defaulting to a conservative bound."""
    raw = os.environ.get(SEARCH_TTL_ENV)
    if raw is None:
        return DEFAULT_SEARCH_TTL_SECONDS
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_SEARCH_TTL_SECONDS


def _cache_base_dir() -> Path:
    """Return a writable cache base, falling back for restricted sandboxes."""
    cache_root = os.environ.get(CACHE_ROOT_ENV)
    if cache_root:
        return Path(cache_root).expanduser() / APP_NAME

    base = Path(platformdirs.user_cache_dir(APP_NAME))
    parent = base if base.exists() else base.parent
    if parent.exists() and not os.access(parent, os.W_OK):
        return SANDBOX_CACHE_ROOT / APP_NAME
    return base


def default_cache_dir_for_vault(vault_root: Path) -> Path:
    """Return the cache dir without importing the memweave-backed indexer."""
    resolved = vault_root.resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "-", resolved.name) or "vault"
    return _cache_base_dir() / f"{safe_name}-{digest}"


def vaults_config_path() -> Path:
    """Return the global vault registry path, with a test override."""
    override = os.environ.get(VAULTS_CONFIG_ENV)
    if override:
        return Path(override)
    return Path.home() / ".config" / "obsidian-knowledge" / "vaults.yaml"


def load_configured_vaults(config_path: Path | None = None) -> list[Path]:
    """Return configured vault roots in order."""
    path = config_path or vaults_config_path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return []
    roots = data.get("vaults") or []
    if not isinstance(roots, list):
        return []
    return [Path(str(root)).expanduser().resolve() for root in roots if str(root).strip()]


def resolve_vault(vault: Path | None, cwd: Path | None = None) -> Path:
    """Resolve the vault for a command.

    Precedence:
    1. explicit --vault
    2. configured vault containing cwd
    3. first configured vault
    4. cwd, preserving legacy behavior when no registry exists
    """
    if vault is not None:
        return vault.expanduser().resolve()

    cwd = (cwd or Path.cwd()).expanduser().resolve()
    configured = load_configured_vaults()
    for root in configured:
        try:
            cwd.relative_to(root)
        except ValueError:
            continue
        return root
    if configured:
        return configured[0]
    return cwd


def format_remember_candidates(hits: list[Hit]) -> str:
    """Format scored candidate homes for a memory."""
    if not hits:
        return "Potential homes:\n(no candidates)"
    lines = ["Potential homes:"]
    lines.extend(f"{hit.score:6.1f}  {hit.path}" for hit in hits)
    return "\n".join(lines)


def format_search_hits(hits: list[Hit]) -> str:
    """Format vault search hits with an optional snippet under each path."""
    lines: list[str] = []
    for hit in hits:
        lines.append(f"{hit.score:6.1f}  {hit.path}")
        if hit.snippet:
            lines.append(f"      {hit.snippet}")
    return "\n".join(lines)


DEFAULT_DOCTOR_QUERIES = (
    "hermes-agent-operating-profile",
    "automated-systems-review",
)


def run_search_doctor(
    *,
    vault: Path,
    cache: Path,
    idx,
    queries: list[str] | tuple[str, ...] = DEFAULT_DOCTOR_QUERIES,
    top_k: int = 3,
    override_digest_filter: bool = True,
) -> tuple[int, str]:
    """Run a concise live vault-search health check.

    Returns ``(exit_code, text)`` so the CLI and tests share exactly the same
    verdict. Exit 0 means the index has rows and every known-hit query returned
    at least one result. Exit 2 means the index is empty/unreadable or a
    known-hit query returned no hits.
    """
    lines = [
        "obsidian-knowledge search doctor",
        f"vault: {vault}",
        f"cache: {cache}",
    ]
    ok = True
    try:
        rows = idx.row_count()
    except Exception as exc:  # pragma: no cover  # allow: exception-handling
        rows = None
        ok = False
        lines.append(f"rows: ERROR ({type(exc).__name__}: {exc})")
    else:
        lines.append(f"rows: {rows}")
        if rows <= 0:
            ok = False

    vector_status = getattr(idx, "vector_status", "unknown")
    vector_enabled = bool(getattr(idx, "_vector_enabled", False))
    vector_label = "enabled" if vector_enabled else "degraded"
    lines.append(f"vector: {vector_label} ({vector_status})")

    for query in queries:
        lines.append(f"query: {query}")
        try:
            hits = idx.search(
                query,
                top_k=top_k,
                override_digest_filter=override_digest_filter,
            )
        except Exception as exc:  # pragma: no cover  # allow: exception-handling
            ok = False
            lines.append(f"  hits: ERROR ({type(exc).__name__}: {exc})")
            continue
        lines.append(f"  hits: {len(hits)}")
        if not hits:
            ok = False
            continue
        top = hits[0]
        lines.append(f"  top: {top.path} ({top.score})")

    lines.append(f"status: {'PASS' if ok else 'FAIL'}")
    return (0 if ok else 2), "\n".join(lines)


def hook_script_path(name: str) -> Path:
    """Return the packaged path for an existing hook script."""
    package_root = Path(__file__).resolve().parents[2]
    script = package_root / "hooks" / name
    if not script.exists():
        raise FileNotFoundError(f"hook script not found: {script}")
    return script


def package_root() -> Path:
    """Return the installed package root that contains bundled assets."""
    return Path(__file__).resolve().parents[2]


def run_hook_entrypoint(event: str, kind: str | None = None, agent: str = "claude") -> int:
    """Dispatch private hook entry points to the existing hook scripts."""
    scripts = {
        ("pre-tool-use", "protect-vault"): "protect-vault.py",
        ("post-tool-use", "reflect-nudge"): "reflect-nudge.py",
        ("session-start", "recall-init"): "recall-init.py",
        ("stop", "update-changelog"): "update-changelog.py",
        ("stop", "remind-convos"): "remind-convos.py",
        ("stop", "nudge-index-sync"): "nudge-index-sync.py",
    }
    effective_kind = kind
    if effective_kind is None:
        defaults = {
            "pre-tool-use": "protect-vault",
            "post-tool-use": "reflect-nudge",
            "session-start": "recall-init",
        }
        effective_kind = defaults.get(event)
    if effective_kind is None:
        print(f"error: unsupported hook event/kind: {event}/{kind}", file=sys.stderr)
        return 2
    script_name = scripts.get((event, effective_kind))
    if script_name is None:
        print(f"error: unsupported hook event/kind: {event}/{kind}", file=sys.stderr)
        return 2
    script = hook_script_path(script_name)
    payload = sys.stdin.read()
    env = os.environ.copy()
    env["OBSIDIAN_KNOWLEDGE_HOOK_AGENT"] = agent
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=Path.cwd(),
        env=env,
        check=False,
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


def init_vault_index(yaml_path: Path) -> None:
    """Add a `vault_index:` section template to the per-vault config file.

    No-op if the section already exists. Preserves any other sections.
    """
    if yaml_path.exists():
        try:
            existing = yaml.safe_load(yaml_path.read_text()) or {}
        except yaml.YAMLError as exc:
            print(f"error: malformed YAML in {yaml_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        if "vault_index" in existing:
            print(f"vault_index section already present in {yaml_path}; not modified.")
            return
        with yaml_path.open("a") as f:
            f.write("\n" + DEFAULT_VAULT_INDEX_TEMPLATE)
    else:
        yaml_path.write_text(DEFAULT_VAULT_INDEX_TEMPLATE)
    print(f"Wrote vault_index template to {yaml_path}")


def link_hermes_memories(vault_root: Path, hermes_memories_dir: Path) -> None:
    """Symlink Hermes built-in MEMORY.md and USER.md into the vault.

    Symlinks live at <vault>/Utility/obsidian-knowledge/hermes/{MEMORY,USER}.md.
    Idempotent — overwrites existing symlinks.

    NOTE: Obsidian linter must be configured to skip this directory before
    symlinks go live, or the linter's frontmatter rewrites will corrupt the
    section-sign delimiter format Hermes uses. See:
      <vault>/.obsidian/plugins/obsidian-linter/data.json (excluded_paths)
    """
    if not hermes_memories_dir.exists():
        raise FileNotFoundError(f"Hermes memories dir not found: {hermes_memories_dir}")

    link_dir = vault_root / "Utility" / "obsidian-knowledge" / "hermes"
    link_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("MEMORY.md", "USER.md"):
        target = hermes_memories_dir / filename
        link = link_dir / filename
        if not target.exists():
            print(f"Source missing, skipping: {target}", file=sys.stderr)
            continue
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
        print(f"Symlinked: {link} -> {target}")

    print(
        f"\nIMPORTANT: configure your Obsidian linter to exclude '{link_dir.relative_to(vault_root)}/' "
        "before opening these files in Obsidian. The linter would corrupt Hermes's "
        "section-sign delimiter format otherwise."
    )


def setup(vault: Path) -> None:
    """First-time setup: register vault, install claude plugin, initial reindex."""
    import shutil

    # 1. Write/update vaults.yaml
    config_dir = Path.home() / ".config" / "obsidian-knowledge"
    config_dir.mkdir(parents=True, exist_ok=True)
    vaults_yaml = config_dir / "vaults.yaml"
    vault_str = str(vault.resolve())

    if vaults_yaml.exists():
        existing = vaults_yaml.read_text()
        if vault_str in existing:
            print(f"vaults.yaml: {vault_str} already registered")
        else:
            with vaults_yaml.open("a") as f:
                f.write(f"  - {vault_str}\n")
            print(f"vaults.yaml: added {vault_str}")
    else:
        vaults_yaml.write_text(f"vaults:\n  - {vault_str}\n")
        print(f"vaults.yaml: created at {vaults_yaml}")

    # 2. Claude plugin install (skip if claude not on PATH)
    if shutil.which("claude") is None:
        print("claude: not found on PATH — skipping plugin install")
    else:
        for cmd in [
            ["claude", "plugin", "marketplace", "add", "crypdick/obsidian-knowledge"],
            ["claude", "plugin", "install", "obsidian-knowledge@obsidian-knowledge"],
        ]:
            print(f"running: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=False)
            if result.returncode != 0:
                print(f"  warning: exited {result.returncode} — continuing")

    # 3. Initial reindex
    print(f"\nreindexing {vault_str} (may take a minute on first run)…")
    from lib.vault_index.config import load_config
    from lib.vault_index.indexer import IndexBusyError, Indexer, default_cache_dir

    cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
    cache = default_cache_dir(vault)
    cache.mkdir(parents=True, exist_ok=True)
    idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
    try:
        stats = idx.full_reindex(force=False)
    except IndexBusyError:
        print("reindex: another index operation in progress; skipping")
        return
    print(f"Indexed: {stats.indexed}, Skipped: {stats.skipped}, Deleted: {stats.deleted}")

    print("\nSetup complete.")


def run_papercut(*, vault: Path, description: str, parser: argparse.ArgumentParser) -> int:
    """Record a papercut without loading the search/indexing stack."""
    from lib.vault_index.papercuts import record_papercut

    try:
        record = record_papercut(vault, description)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Logged papercut: {record.path.relative_to(vault)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="obsidian-knowledge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser(
        "setup",
        help="First-time setup: register vault, install claude plugin, initial reindex",
    )
    p_setup.add_argument("--vault", type=Path, required=True, help="Vault root path")

    p_init = sub.add_parser(
        "init-vault-index",
        help="Add vault_index template to .claude/obsidian-knowledge.yaml",
    )
    p_init.add_argument("--vault", type=Path, default=None, help="Vault root")

    p_reindex = sub.add_parser("reindex", help="Run a full re-index of the vault")
    p_reindex.add_argument("--vault", type=Path, default=None)
    p_reindex.add_argument("--force", action="store_true")
    p_reindex.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help="Abort reindex if it exceeds this many seconds.",
    )

    p_search = sub.add_parser("search", help="Search the vault index")
    p_search.add_argument("query", help="Free-text query")
    p_search.add_argument("--vault", type=Path, default=None)
    p_search.add_argument("--top-k", type=int, default=None)
    p_search.add_argument(
        "--all",
        action="store_true",
        help="Override digest filter (include paths normally hidden from prefetch).",
    )

    p_remember = sub.add_parser(
        "remember",
        help="Print scored candidate homes for a memory; does not write files",
    )
    p_remember.add_argument("memory", help="Memory text to place")
    p_remember.add_argument("--vault", type=Path, default=None)
    p_remember.add_argument("--top-k", type=int, default=None)
    p_remember.add_argument(
        "--all",
        action="store_true",
        help="Override digest filter (include paths normally hidden from prefetch).",
    )

    p_papercut = sub.add_parser(
        "papercut",
        help="Record workflow friction in the vault; does not diagnose or change anything",
    )
    p_papercut.add_argument("description", help="What caused friction; quote multi-word descriptions")
    p_papercut.add_argument("--vault", type=Path, default=None, help="Vault root")

    p_doctor = sub.add_parser(
        "doctor",
        help="Run a live vault-search health check with known-hit queries",
    )
    p_doctor.add_argument("--vault", type=Path, default=None)
    p_doctor.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Known-hit query to test; may be repeated.",
    )
    p_doctor.add_argument("--top-k", type=int, default=3)
    p_doctor.add_argument(
        "--digest-only",
        action="store_true",
        help="Apply the normal digest filter instead of searching all indexed paths.",
    )

    p_hook = sub.add_parser("_hook", help=argparse.SUPPRESS)
    hook_sub = p_hook.add_subparsers(dest="hook_event", required=True)
    for name in ("pre-tool-use", "post-tool-use", "session-start", "stop"):
        p = hook_sub.add_parser(name, help=argparse.SUPPRESS)
        p.add_argument("--kind", default=None)
        p.add_argument("--agent", choices=("claude", "codex"), default="claude")

    p_link = sub.add_parser(
        "link-hermes-memories",
        help="Symlink Hermes MEMORY.md/USER.md into the vault",
    )
    p_link.add_argument("--vault", type=Path, default=None)
    p_link.add_argument(
        "--hermes-memories-dir",
        type=Path,
        default=Path.home() / ".hermes" / "memories",
    )

    args = parser.parse_args()

    if args.cmd == "setup":
        setup(args.vault)
    elif args.cmd == "_hook":
        return run_hook_entrypoint(args.hook_event, kind=args.kind, agent=args.agent)
    elif args.cmd == "init-vault-index":
        vault = resolve_vault(args.vault)
        init_vault_index(vault / ".claude" / "obsidian-knowledge.yaml")
    elif args.cmd == "reindex":
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import IndexBusyError, Indexer

        # Bound the ENTIRE reindex, not just full_reindex(): setup steps
        # (vault resolution, config load, Indexer init / fingerprint check) also
        # do filesystem reads that can block indefinitely on a contended/stalled
        # path. A hang there escaped the old full_reindex-only guard and left an
        # orphaned process (observed via a worker stuck in a bare open() during
        # Indexer init). The watchdog inside search_ttl force-exits regardless.
        try:
            with search_ttl(args.timeout_seconds, label="reindex"):
                vault = resolve_vault(args.vault)
                cache = default_cache_dir_for_vault(vault)
                cache.mkdir(parents=True, exist_ok=True)
                cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
                idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
                stats = idx.full_reindex(force=args.force)
        except IndexBusyError:
            print(
                "reindex: another index operation is in progress (lock held); exiting cleanly.",
                file=sys.stderr,
            )
            return 0
        except SearchTimeoutError as exc:
            print(f"reindex: timed out ({exc})", file=sys.stderr)
            return 124
        print(
            f"Indexed: {stats.indexed}, Skipped: {stats.skipped}, Deleted: {stats.deleted}",
            flush=True,
        )
    elif args.cmd == "link-hermes-memories":
        vault = resolve_vault(args.vault)
        link_hermes_memories(vault, args.hermes_memories_dir)
    elif args.cmd == "papercut":
        return run_papercut(
            vault=resolve_vault(args.vault),
            description=args.description,
            parser=parser,
        )
    elif args.cmd == "doctor":
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import Indexer, default_cache_dir

        vault = resolve_vault(args.vault)
        cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
        cache = default_cache_dir(vault)
        idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
        code, text = run_search_doctor(
            vault=vault,
            cache=cache,
            idx=idx,
            queries=args.queries or DEFAULT_DOCTOR_QUERIES,
            top_k=args.top_k,
            override_digest_filter=not args.digest_only,
        )
        print(text)
        return code
    elif args.cmd in {"search", "remember"}:
        from lib.vault_index.config import load_config
        from lib.vault_index.indexer import Indexer, default_cache_dir

        vault = resolve_vault(args.vault)
        cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
        cache = default_cache_dir(vault)
        idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
        if not idx._vector_enabled:
            print(f"# search ranking degraded ({idx.vector_status})", file=sys.stderr)
        query = args.query if args.cmd == "search" else args.memory
        try:
            with search_ttl(search_ttl_seconds()):
                hits = idx.search(query, top_k=args.top_k, override_digest_filter=args.all)
        except SearchTimeoutError as exc:
            print(f"# search timed out ({exc})", file=sys.stderr)
            return 124
        if not hits:
            print("(no results)" if args.cmd == "search" else format_remember_candidates([]))
            return 0
        if args.cmd == "remember":
            print(format_remember_candidates(hits))
            return 0
        print(format_search_hits(hits))

    return 0


def _exit_hard(code: int) -> None:
    """Flush stdio then `os._exit` to skip Python's atexit/asyncio shutdown.

    memweave/litellm/aiohttp leave non-daemon threads or pending tasks alive
    after `idx.full_reindex()` and `idx.search()` finish, which makes the
    interpreter hang on shutdown — confirmed on both dream-machine (Linux
    Python 3.13) and mac mini (Apple Silicon Python 3.13), where the hourly
    cron piled up zombie `reindex` processes overnight. Force-exit is the
    same workaround used in `hermes_plugin` for the asyncio-daemon-thread
    mismatch.

    Called from `cli_main()` (the console-script entry point) so it applies
    whether the CLI is invoked via `python -m lib.vault_index.cli` or via
    the `obsidian-knowledge` entry point.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def cli_main() -> None:
    """Console-script entry point. See [project.scripts] in pyproject.toml."""
    _exit_hard(main())


if __name__ == "__main__":
    cli_main()
