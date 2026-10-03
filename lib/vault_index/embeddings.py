"""Direct Ollama embeddings with memweave's provider contract."""

from __future__ import annotations

import asyncio
from typing import Annotated

import httpx
from memweave import EmbeddingConfig
from memweave.embedding.provider import EmbeddingProvider, LiteLLMEmbeddingProvider
from memweave.embedding.vectors import normalize_embedding
from memweave.exceptions import EmbeddingError
from pydantic import BaseModel, Field

DEFAULT_EMBEDDING_API_BASE = "http://127.0.0.1:11434"
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
            for start in range(0, len(texts), self.config.batch_size):
                batch = texts[start : start + self.config.batch_size]
                embeddings.extend(await self._embed_batch(client, url, batch))
        return embeddings

    async def _embed_batch(self, client: httpx.AsyncClient, url: str, batch: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            try:
                response = await client.post(
                    url, json={"model": self.config.model.removeprefix("ollama/"), "input": batch}
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
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
