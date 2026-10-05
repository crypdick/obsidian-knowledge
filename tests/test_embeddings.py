"""Embedding provider contract, HTTP failures, and offline retrieval."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import httpx
import pytest
from memweave import EmbeddingConfig
from memweave.embedding.provider import LiteLLMEmbeddingProvider
from memweave.exceptions import EmbeddingError

from lib.vault_index.embeddings import OllamaEmbeddingProvider, make_embedding_provider


@pytest.fixture
def http_client(monkeypatch):
    original = httpx.AsyncClient
    settings = []

    def install(handler):
        def client(**kwargs):
            settings.append(kwargs)
            return original(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)
        return settings

    return install


def test_provider_batches_normalizes_and_forwards_configuration(http_client):
    requests = []

    def respond(request):
        requests.append(request)
        inputs = json.loads(request.content)["input"]
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] for _ in inputs]})

    settings = http_client(respond)
    provider = OllamaEmbeddingProvider(
        EmbeddingConfig(
            model="ollama/bge-m3:latest",
            api_base="http://private-ollama:11434/",
            api_key="synthetic-token",  # pragma: allowlist secret
            timeout=7,
            batch_size=2,
        )
    )
    assert asyncio.run(provider.embed_batch(["one", "two", "three"])) == [[0.6, 0.8]] * 3
    assert [json.loads(request.content) for request in requests] == [
        {"model": "bge-m3:latest", "input": ["one", "two"]},
        {"model": "bge-m3:latest", "input": ["three"]},
    ]
    assert all(str(request.url) == "http://private-ollama:11434/api/embed" for request in requests)
    assert all(request.headers["authorization"] == "Bearer synthetic-token" for request in requests)
    assert settings[0]["timeout"] == 7


def test_query_uses_default_endpoint_and_empty_batch_needs_no_request(http_client):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"embeddings": [[0.0, 2.0]]})

    http_client(respond)
    provider = OllamaEmbeddingProvider(EmbeddingConfig(model="ollama/bge-m3"))
    assert asyncio.run(provider.embed_batch([])) == []
    assert requests == []
    assert asyncio.run(provider.embed_query("orchids")) == [0.0, 1.0]
    assert str(requests[0].url) == "http://127.0.0.1:11434/api/embed"
    assert "authorization" not in requests[0].headers
    with pytest.raises(EmbeddingError, match="empty text"):
        asyncio.run(provider.embed_query(" \n"))
    assert len(requests) == 1


@pytest.mark.parametrize("failure", [429, 500, 502, 503, 504, "connect", "timeout"])
@pytest.mark.parametrize("recovers", [True, False])
def test_only_transient_errors_retry_with_bounded_backoff(http_client, monkeypatch, failure, recovers):
    requests = []
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def respond(request):
        requests.append(request)
        if recovers and len(requests) == 3:
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
        if failure == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("embedding timed out", request=request)
        return httpx.Response(failure, json={"error": "temporarily unavailable"})

    http_client(respond)
    provider = OllamaEmbeddingProvider(EmbeddingConfig(model="ollama/bge-m3"))
    if recovers:
        assert asyncio.run(provider.embed_query("orchids")) == [1.0, 0.0]
    else:
        with pytest.raises(EmbeddingError, match="Ollama embedding request failed"):
            asyncio.run(provider.embed_query("orchids"))
    assert len(requests) == 3
    assert delays == [0.5, 2.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_errors_do_not_retry(http_client, status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "request rejected"})

    http_client(respond)
    with pytest.raises(EmbeddingError, match="Ollama embedding request failed"):
        asyncio.run(OllamaEmbeddingProvider(EmbeddingConfig(model="ollama/bge-m3")).embed_query("orchids"))
    assert len(requests) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"embeddings": []},
        {"embeddings": [[1.0, 0.0], [0.0, 1.0]]},
        {"embeddings": [[]]},
        {"embeddings": [[0.0, 0.0]]},
        {"embeddings": [[float("nan"), 1.0]]},
        {"embeddings": [[float("inf"), 1.0]]},
        {"embeddings": [["not a number", 1.0]]},
        {"embeddings": [[True, 1.0]]},
        "not json",
    ],
)
def test_malformed_embeddings_fail_without_retry(http_client, payload):
    requests = []

    def respond(request):
        requests.append(request)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, content=content)

    http_client(respond)
    with pytest.raises(EmbeddingError, match="Invalid Ollama embeddings"):
        asyncio.run(OllamaEmbeddingProvider(EmbeddingConfig(model="ollama/bge-m3")).embed_query("orchids"))
    assert len(requests) == 1


def test_batch_rejects_mixed_dimensions(http_client):
    http_client(lambda request: httpx.Response(200, json={"embeddings": [[1.0], [1.0, 0.0]]}))
    with pytest.raises(EmbeddingError, match="dimensions differ"):
        asyncio.run(
            OllamaEmbeddingProvider(EmbeddingConfig(model="ollama/bge-m3")).embed_batch(["one", "two"])
        )


def test_other_model_identifiers_keep_memweave_provider(monkeypatch):
    import litellm

    monkeypatch.setattr(litellm, "suppress_debug_info", False)
    config = EmbeddingConfig(model="text-embedding-3-small")
    assert isinstance(make_embedding_provider(config, enabled=True), LiteLLMEmbeddingProvider)
    assert litellm.suppress_debug_info is True


def test_native_index_and_hybrid_search_never_import_litellm(tmp_path):
    script = """
import asyncio, json, sys
from pathlib import Path
import httpx
from lib.vault_index.indexer import Indexer
from lib.vault_index.config import VaultIndexConfig
original = httpx.AsyncClient
requests = []
def respond(request):
    inputs = json.loads(request.content)['input']
    requests.append(inputs)
    return httpx.Response(200, json={'embeddings': [[3.0, 4.0] for _ in inputs]})
httpx.AsyncClient = lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)
root = Path(sys.argv[1])
(root / 'note.md').write_text('Purple orchids grow in a greenhouse.')
instance = Indexer(root, root / 'cache', VaultIndexConfig(), skip_probe=True)
stats = instance.full_reindex()
report = instance.search_report('orchids', top_k=1)
asyncio.run(instance._store.close())
print(json.dumps({'indexed': stats.indexed, 'mode': report.mode,
                  'paths': [hit.path for hit in report.hits], 'requests': requests,
                  'litellm_loaded': 'litellm' in sys.modules}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["indexed"] == 1
    assert report["mode"] == "hybrid"
    assert report["paths"] == ["note.md"]
    assert len(report["requests"]) == 2
    assert report["litellm_loaded"] is False
