"""Direct Ollama embeddings with memweave's provider contract."""

from __future__ import annotations

import asyncio
import errno
import json
import urllib.error
import urllib.request
from typing import Annotated

import httpx
from pydantic import BaseModel, Field

from obsidian_knowledge_vendor.memweave import EmbeddingConfig
from obsidian_knowledge_vendor.memweave.embedding.provider import EmbeddingProvider, LiteLLMEmbeddingProvider
from obsidian_knowledge_vendor.memweave.embedding.vectors import normalize_embedding
from obsidian_knowledge_vendor.memweave.exceptions import EmbeddingError

DEFAULT_EMBEDDING_API_BASE = "http://127.0.0.1:11434"
PROBE_TIMEOUT_S = 1.5
RETRY_DELAYS = (0.5, 2.0)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

EmbeddingVector = Annotated[
    list[Annotated[float, Field(strict=True, allow_inf_nan=False)]], Field(min_length=1)
]


class OllamaResponse(BaseModel):
    embeddings: list[EmbeddingVector]


def parse_embeddings(payload: object, expected_count: int) -> list[list[float]]:
    vectors = OllamaResponse.model_validate(payload).embeddings
    if len(vectors) != expected_count:
        raise ValueError(f"expected {expected_count} embeddings, got {len(vectors)}")
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("embedding dimensions differ within batch")
    normalized = [normalize_embedding(vector) for vector in vectors]
    if any(not any(vector) for vector in normalized):
        raise ValueError("embedding vector has zero norm")
    return normalized


class OllamaEmbeddingProvider:
    """Use Ollama's batch endpoint without loading LiteLLM."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._batch_size = config.batch_size

    # NOTE: docs/CLI.md "Settled-file indexing worker" documents model residency.
    async def warm_up(self) -> None:
        """Load the model independently of query deadlines, without embedding text."""
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        url = (self.config.api_base or DEFAULT_EMBEDDING_API_BASE).rstrip("/") + "/api/embed"
        async with httpx.AsyncClient(timeout=120, headers=headers) as client:
            response = await client.post(
                url,
                json={"model": self.config.model.removeprefix("ollama/"), "input": [], "keep_alive": "1h"},
            )
            response.raise_for_status()

    async def embed_query(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("embed_query received empty text")
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
        url = (self.config.api_base or DEFAULT_EMBEDDING_API_BASE).rstrip("/") + "/api/embed"
        embeddings = []
        async with httpx.AsyncClient(timeout=self.config.timeout, headers=headers) as client:
            start = 0
            while start < len(texts):
                batch = texts[start : start + self._batch_size]
                embeddings.extend(await self._embed_batch(client, url, batch))
                start += len(batch)
        return embeddings

    async def _embed_batch(self, client: httpx.AsyncClient, url: str, batch: list[str]) -> list[list[float]]:
        if len(batch) > self._batch_size:
            vectors = []
            size = self._batch_size
            for start in range(0, len(batch), size):
                vectors.extend(await self._embed_batch(client, url, batch[start : start + size]))
            return vectors
        attempt = 0
        while True:
            try:
                response = await client.post(
                    url,
                    json={
                        "model": self.config.model.removeprefix("ollama/"),
                        "input": batch,
                        "keep_alive": "1h",
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                if isinstance(exc, httpx.TimeoutException) and len(batch) > 1:
                    # Repeating a batch that exceeds the endpoint's throughput
                    # deadline wastes the same work. Adapt to slower backends.
                    self._batch_size = min(self._batch_size, max(1, len(batch) // 2))
                    return await self._embed_batch(client, url, batch)
                retryable = (
                    not isinstance(exc, httpx.HTTPStatusError)
                    or exc.response.status_code in RETRYABLE_STATUSES
                )
                if not retryable or attempt == len(RETRY_DELAYS):
                    raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
                await asyncio.sleep(RETRY_DELAYS[attempt])
                attempt += 1
            else:
                try:
                    return parse_embeddings(response.json(), len(batch))
                except ValueError as exc:
                    raise EmbeddingError(f"Invalid Ollama embeddings: {exc}") from exc


class KeywordOnlyEmbeddingProvider:
    """Keep memweave's indexing pipeline offline when vectors are disabled.

    memweave 0.2 still calls its provider with vector.enabled=False. Empty
    vectors retain chunks and FTS entries without caching fake embeddings.
    """

    async def embed_query(self, text: str) -> list[float]:
        return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]


def make_embedding_provider(config: EmbeddingConfig, *, enabled: bool) -> EmbeddingProvider:
    if not enabled:
        return KeywordOnlyEmbeddingProvider()
    if config.model.startswith("ollama/"):
        return OllamaEmbeddingProvider(config)
    import litellm

    # Keep fallback errors from writing LiteLLM's support banner into CLI JSON.
    litellm.suppress_debug_info = True
    return LiteLLMEmbeddingProvider(config)


def ollama_probe(api_base: str, model: str) -> tuple[bool, str]:
    """Check Ollama is up and the model is pulled. Returns (ok, message).

    Strips the LiteLLM ``ollama/`` prefix from ``model`` before comparison
    against Ollama's tag list. Tags appear as e.g. ``bge-m3:latest``; we
    match on the bare name (everything before ``:``).
    """
    if not api_base.startswith("http"):
        return False, f"api_base not http(s): {api_base}"
    bare = model.split("/", 1)[1] if "/" in model else model
    bare_name = bare.split(":", 1)[0]
    url = api_base.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        if isinstance(reason, OSError) and reason.errno in {errno.EPERM, errno.EACCES}:
            return False, (
                f"Ollama access denied at {api_base}: {exc}. "
                "Sandbox or OS permissions blocked the connection; this does not show that Ollama is stopped. "
                "Retry with approved network access to this endpoint"
            )
        return False, (
            f"Ollama unreachable at {api_base}: {exc}. "
            "Check the configured endpoint and Ollama service from a process with network access"
        )
    except json.JSONDecodeError as exc:
        return False, f"Ollama returned non-JSON: {exc}"
    tags = [t.get("name", "") for t in data.get("models", [])]
    if not any(name.split(":", 1)[0] == bare_name for name in tags):
        return False, (
            f"model '{bare_name}' not pulled (have: {tags or 'none'}); "
            f"run `ollama pull {bare}` against {api_base}"
        )
    return True, f"ok: {bare_name} via {api_base}"
