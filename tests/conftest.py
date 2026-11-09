"""Shared test fixtures for obsidian-knowledge plugin hooks."""

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

# Make hooks importable.
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

# Scrub repo-binding git env vars so the git-invoking tests (which `git init`
# throwaway repos under tmp_path) never inherit an ambient git context. Git and
# pre-commit export these to hook processes, so running the suite via `git
# commit` would otherwise redirect `git init`/`remote`/`rev-parse` at the real
# repo. Tests must not depend on the caller's git state; clear it once here.
for _git_var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
):
    os.environ.pop(_git_var, None)


@pytest.fixture(autouse=True)
def _isolated_preferences(tmp_path, monkeypatch):
    """Isolate preferences and clear ambient vault registry overrides."""
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_CONFIG", str(tmp_path / "preferences.yaml"))
    # Tests exercise HOME-based discovery; caller overrides must not supersede it.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", raising=False)


@pytest.fixture(autouse=True)
def _disable_ollama_probe(monkeypatch):
    """Force Indexer to skip the live Ollama probe in tests.

    Returns (False, "test-stub: probe disabled") so vector_enabled flips off
    and tests stay FTS-only without 1.5s timeouts per construction.
    """
    monkeypatch.setattr(
        "lib.vault_index.indexer._ollama_probe",
        lambda api_base, model: (False, "test-stub: probe disabled"),
    )


@pytest.fixture(autouse=True)
def _isolated_user_cache(tmp_path_factory, monkeypatch):
    """Redirect `platformdirs.user_cache_dir` into a per-session tmp dir.

    Without this, any test that calls `default_cache_dir(vault_root)` writes
    into the real user cache (`~/.cache/obsidian-knowledge/` on Linux,
    `~/Library/Caches/obsidian-knowledge/` on macOS), leaking pytest tmp
    paths into production state. Discovered 2026-05-11 after finding an
    orphan `vault-a34e8ad8/` dir from `tmp_path/"vault"` fixtures.
    """
    fake_cache = tmp_path_factory.mktemp("user_cache")
    monkeypatch.setattr(
        "lib.vault_index.cache_paths.platformdirs.user_cache_dir",
        lambda app_name: str(fake_cache / app_name),
    )


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a fake vault root with required structure."""
    vault = tmp_path / "vault"
    (vault / "wiki" / "systems" / "repos").mkdir(parents=True)
    return vault


@pytest.fixture
def tmp_vaults_yaml(tmp_path, monkeypatch, tmp_vault):
    """Create vaults.yaml pointing to tmp_vault and patch CONFIG_PATH."""
    config_dir = tmp_path / "config" / "obsidian-knowledge"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "vaults.yaml"
    config_file.write_text(f"vaults:\n  - {tmp_vault}\n")
    monkeypatch.setenv("OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def subprocess_vault(tmp_path):
    """Set up a vault discoverable by subprocess hooks via HOME override.

    Returns (vault_path, env) where env can be passed to subprocess.run
    to make the hook resolve `~/.config/obsidian-knowledge/vaults.yaml`
    against the temp HOME.
    """
    home = tmp_path / "home"
    home.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = home / ".config" / "obsidian-knowledge"
    cfg.mkdir(parents=True)
    (cfg / "vaults.yaml").write_text(f"vaults:\n  - {vault}\n")
    # Skip the doctor's live Ollama probe: this hook runs as a subprocess, so
    # the in-process `_disable_ollama_probe` monkeypatch doesn't reach it, and
    # CI has no Ollama. The env flag is the subprocess analog of that fixture.
    env = {
        **os.environ,
        "HOME": str(home),
        "OBSIDIAN_KNOWLEDGE_SKIP_OLLAMA_PROBE": "1",
    }
    return vault, env


@dataclass
class FakeOllama:
    """Deterministic local stand-in for Ollama's tags and batch-embed endpoints."""

    url: str
    requests: int = 0
    delay: float = 0
    texts: list[str] = field(default_factory=list)
    models: tuple[str, ...] = ("bge-m3:latest",)


@pytest.fixture
def fake_ollama(monkeypatch):
    """Serve deterministic embeddings and point indexer processes at them."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    endpoint = FakeOllama(url=f"http://127.0.0.1:{server.server_port}")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(json.dumps({"models": [{"name": name} for name in endpoint.models]}).encode())

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            endpoint.requests += 1
            time.sleep(endpoint.delay)
            endpoint.texts.extend(payload["input"])
            vectors = []
            for text in payload["input"]:
                digest = hashlib.sha256(text.encode()).digest()
                # Other models get another width, like a real model swap.
                width = 3 if payload["model"] == "bge-m3" else 4
                vectors.append([1.0, digest[0] / 255.0, digest[1] / 255.0, 0.5][:width])
            self.respond(json.dumps({"embeddings": vectors}).encode())

        def respond(self, payload: bytes):
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Expected when a bounded CLI terminates a slow request.

        def log_message(self, *_args):
            pass

    server.RequestHandlerClass = Handler
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MEMWEAVE_EMBEDDING_API_BASE", endpoint.url)
    # Subprocesses probe the fake server; in-process indexers bypass the stub.
    monkeypatch.setattr("lib.vault_index.indexer._ollama_probe", lambda api_base, model: (True, "ok: fake"))
    try:
        yield endpoint
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def drain_index():
    """Run settled work deterministically without a daemon or real cooldown."""
    from lib.vault_index.index_worker import IndexWorker

    async def drain(vault):
        worker = IndexWorker(vault, quiet_seconds=0)
        await worker.scan()
        from types import SimpleNamespace
        from unittest.mock import patch

        from lib.vault_index import dirty_paths

        clock = SimpleNamespace(time=lambda: time.time() + 31)
        with patch.object(dirty_paths, "time", clock):
            for _ in range(100):
                if not await worker.process_next():
                    return
        pytest.fail("index worker did not drain")

    return drain
