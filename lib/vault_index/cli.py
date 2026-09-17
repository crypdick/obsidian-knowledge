# allow: file-length  (CLI surface; decomposition tracked in docs/QUALITY.md)
"""CLI entry points for obsidian-knowledge tooling."""

from __future__ import annotations

import argparse
import contextlib
import errno
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

from lib.vault_index.models import Hit, IndexBusyError
from lib.vault_index.registration import existing_vault, read_registry, register_vault
from lib.vault_index.vault_files import read_vault_file, write_vault_file

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
        if use_alarm:  # pragma: no branch  # generator-exit arc is not executable
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_alarm:  # pragma: no branch  # generator-exit arc is not executable
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
    data = read_registry(config_path or vaults_config_path())
    return [Path(root).expanduser().resolve() for root in data.get("vaults", [])]


def resolve_vault(vault: Path | None, cwd: Path | None = None) -> Path:
    """Resolve the vault for a command.

    Precedence:
    1. explicit --vault
    2. configured vault containing cwd
    3. first configured vault
    4. cwd, preserving legacy behavior when no registry exists
    """
    if vault is not None:
        return existing_vault(vault)

    cwd = (cwd or Path.cwd()).expanduser().resolve()
    configured = load_configured_vaults()
    for root in configured:
        try:
            cwd.relative_to(root)
        except ValueError:
            continue
        return existing_vault(root)
    if configured:
        return existing_vault(configured[0])
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
    "knowledge-base",
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
    except SearchTimeoutError:
        raise
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
        except SearchTimeoutError:
            raise
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
        ("stop", "capture-session"): "capture-session.py",
        # Rolling-compatibility aliases for older cached hook manifests. Both
        # wrappers use the consolidated capture-session cooldown marker.
        ("stop", "update-changelog"): "capture-session.py",
        ("stop", "remind-convos"): "capture-session.py",
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
            existing = yaml.safe_load(yaml_path.read_text())
        except yaml.YAMLError as exc:
            print(f"error: malformed YAML in {yaml_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ValueError(f"expected a YAML mapping in {yaml_path}")
        if "vault_index" in existing:
            print(f"vault_index section already present in {yaml_path}; not modified.")
            return
        with yaml_path.open("a") as f:
            f.write("\n" + DEFAULT_VAULT_INDEX_TEMPLATE)
    else:
        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_path.write_text(DEFAULT_VAULT_INDEX_TEMPLATE)
    print(f"Wrote vault_index template to {yaml_path}")


def setup(vault: Path, *, skip_claude_plugin: bool = False) -> None:
    """First-time setup: register vault, install claude plugin, initial reindex."""
    import shutil

    from lib.vault_index.config import load_config
    from lib.vault_index.indexer import Indexer, default_cache_dir

    vault = existing_vault(vault)
    cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
    # 1. Validate and atomically update vaults.yaml.
    vaults_yaml = vaults_config_path()
    vault_str = str(vault)
    if register_vault(vault, vaults_yaml):
        print(f"vaults.yaml: registered {vault_str} in {vaults_yaml}")
    else:
        print(f"vaults.yaml: {vault_str} already registered")

    from lib.vault_index.guard_install import install_rules

    print(f"i-insist rules: {install_rules(Path.home())}")

    # 2. Claude plugin install (skip if claude not on PATH)
    if skip_claude_plugin:
        print("claude: plugin install skipped (--skip-claude-plugin)")
    elif shutil.which("claude") is None:
        print("claude: not found on PATH — skipping plugin install")
    else:
        for cmd in [
            ["claude", "plugin", "marketplace", "add", "crypdick/obsidian-knowledge"],
            ["claude", "plugin", "install", "obsidian-knowledge@obsidian-knowledge"],
        ]:
            print(f"running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, timeout=120)

    # 3. Initial reindex
    print(f"\nreindexing {vault_str} (may take a minute on first run)…")
    cache = default_cache_dir(vault)
    cache.mkdir(parents=True, exist_ok=True)
    idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
    if not idx.vector_enabled:
        print(f"Search mode: keyword-only ({idx.vector_status}).")
        print(
            "To enable semantic search, resolve the reported embedding access or model issue, then reindex."
        )
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
    except OSError as exc:
        print(f"papercut: could not complete vault log write: {exc}", file=sys.stderr)
        if exc.errno in {errno.EROFS, errno.EACCES, errno.EPERM}:
            print(
                f"papercut: vault write access is required under {vault}, including the log's directory "
                "and lock file. In a sandbox, retry through the host's approved permission mechanism. "
                "If access is unavailable, report the logging failure once and continue the original task; "
                "do not recursively log this failure.",
                file=sys.stderr,
            )
        return 1
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Logged papercut: {record.path.relative_to(vault)}")
    return 0


def run_vault_file_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> int:
    """Run the lightweight read/write commands without loading the indexer."""
    try:
        vault = resolve_vault(args.vault)
        if args.cmd == "read":
            sys.stdout.buffer.write(read_vault_file(vault, args.path))
            return 0
        target = write_vault_file(
            vault,
            args.path,
            sys.stdin.buffer.read(),
            replace=args.replace,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Wrote and verified: {target}")
    return 0


def run_retrieval_command(args: argparse.Namespace) -> int:
    """Initialize and query inside the caller's whole-command deadline."""
    from lib.vault_index.config import load_config
    from lib.vault_index.indexer import Indexer, default_cache_dir

    vault = resolve_vault(args.vault)
    cfg = load_config(vault / ".claude" / "obsidian-knowledge.yaml")
    cache = default_cache_dir(vault)
    idx = Indexer(vault_root=vault, cache_dir=cache, config=cfg)
    if args.cmd == "doctor":
        code, report = run_search_doctor(
            vault=vault,
            cache=cache,
            idx=idx,
            queries=args.queries or DEFAULT_DOCTOR_QUERIES,
            top_k=args.top_k,
            override_digest_filter=not args.digest_only,
        )
        print(report)
        return code
    if not idx.vector_enabled:
        print(f"# search ranking degraded ({idx.vector_status})", file=sys.stderr)
    query = args.query if args.cmd == "search" else args.memory
    hits = idx.search(query, top_k=args.top_k, override_digest_filter=args.all)
    if args.cmd == "remember":
        print(format_remember_candidates(hits))
    else:
        print(format_search_hits(hits) if hits else "(no results)")
    return 0


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(prog="obsidian-knowledge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser(
        "setup",
        help="First-time setup: register vault, install claude plugin, initial reindex",
    )
    p_setup.add_argument("--vault", type=Path, required=True, help="Vault root path")
    p_setup.add_argument("--skip-claude-plugin", action="store_true", help="Register and index only")
    p_setup.add_argument(
        "--timeout-seconds", type=int, default=300, help="Whole-command deadline (default: 300)"
    )

    p_init = sub.add_parser(
        "init-vault-index",
        help="Add vault_index template to .claude/obsidian-knowledge.yaml",
    )
    p_init.add_argument("--vault", type=Path, default=None, help="Vault root")

    p_read = sub.add_parser("read", help="Read exact bytes from a vault-relative file")
    p_read.add_argument("path", type=Path, help="Path relative to the vault root")
    p_read.add_argument("--vault", type=Path, default=None, help="Vault root")

    p_write = sub.add_parser(
        "write",
        help="Atomically write stdin to a vault-relative file and verify final bytes",
    )
    p_write.add_argument("path", type=Path, help="Path relative to the vault root")
    p_write.add_argument("--vault", type=Path, default=None, help="Vault root")
    p_write.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing file; new files are create-only by default",
    )

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
    p_search.add_argument("--top-k", type=positive_int, default=None)
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
    p_remember.add_argument("--top-k", type=positive_int, default=None)
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
    p_doctor.add_argument("--top-k", type=positive_int, default=3)
    p_doctor.add_argument(
        "--digest-only",
        action="store_true",
        help="Apply the normal digest filter instead of searching all indexed paths.",
    )

    p_rules = sub.add_parser("install-rules", help="Install i-insist and provider-owned vault rules")
    p_rules.add_argument("--global", dest="global_scope", action="store_true", help="Install in ~/.i-insist")

    p_hook = sub.add_parser("_hook", help=argparse.SUPPRESS)
    hook_sub = p_hook.add_subparsers(dest="hook_event", required=True)
    for name in ("pre-tool-use", "post-tool-use", "session-start", "stop"):
        p = hook_sub.add_parser(name, help=argparse.SUPPRESS)
        p.add_argument("--kind", default=None)
        p.add_argument("--agent", choices=("claude", "codex"), default="claude")

    args = parser.parse_args()

    if args.cmd == "setup":
        with search_ttl(args.timeout_seconds, label="setup"):
            setup(args.vault, skip_claude_plugin=args.skip_claude_plugin)
    elif args.cmd == "install-rules":
        from lib.vault_index.guard_install import install_rules

        try:
            path = install_rules(Path.home() if args.global_scope else Path.cwd())
        except (OSError, subprocess.CalledProcessError) as exc:
            print(
                f"i-insist setup failed: {exc}. Install or upgrade i-insist, enable its hooks, then retry.",
                file=sys.stderr,
            )
            return 2
        print(f"Installed i-insist rules: {path}")
    elif args.cmd == "_hook":
        return run_hook_entrypoint(args.hook_event, kind=args.kind, agent=args.agent)
    elif args.cmd == "init-vault-index":
        vault = resolve_vault(args.vault)
        init_vault_index(vault / ".claude" / "obsidian-knowledge.yaml")
    elif args.cmd in {"read", "write"}:
        return run_vault_file_command(args, parser)
    elif args.cmd == "reindex":
        # Bound the ENTIRE reindex, not just full_reindex(): setup steps
        # (vault resolution, config load, Indexer init / fingerprint check) also
        # do filesystem reads that can block indefinitely on a contended/stalled
        # path. A hang there escaped the old full_reindex-only guard and left an
        # orphaned process (observed via a worker stuck in a bare open() during
        # Indexer init). The watchdog inside search_ttl force-exits regardless.
        try:
            with search_ttl(args.timeout_seconds, label="reindex"):
                from lib.vault_index.config import load_config
                from lib.vault_index.indexer import Indexer

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
    elif args.cmd == "papercut":
        return run_papercut(
            vault=resolve_vault(args.vault),
            description=args.description,
            parser=parser,
        )
    elif args.cmd in {"doctor", "search", "remember"}:  # pragma: no branch  # exhaustive parser
        with search_ttl(search_ttl_seconds(), label=args.cmd):
            return run_retrieval_command(args)

    return 0


def _exit_hard(code: int) -> None:
    """Flush stdio then `os._exit` to skip Python's atexit/asyncio shutdown.

    memweave/litellm/aiohttp leave non-daemon threads or pending tasks alive
    after `idx.full_reindex()` and `idx.search()` finish, which makes the
    interpreter hang on shutdown — confirmed on both dream-machine (Linux
    Python 3.13) and mac mini (Apple Silicon Python 3.13), where the hourly
    cron piled up zombie `reindex` processes overnight. Force-exit is the
    workaround required for the asyncio daemon-thread mismatch.

    Called from `cli_main()` (the console-script entry point) so it applies
    whether the CLI is invoked via `python -m lib.vault_index.cli` or via
    the `obsidian-knowledge` entry point.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def cli_main() -> None:
    """Console-script entry point. See [project.scripts] in pyproject.toml."""
    try:
        code = main()
    except SearchTimeoutError as exc:
        print(f"obsidian-knowledge: timed out ({exc})", file=sys.stderr)
        code = 124
    except (OSError, ValueError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"obsidian-knowledge: {exc}", file=sys.stderr)
        code = 2
    _exit_hard(code)


if __name__ == "__main__":
    cli_main()
