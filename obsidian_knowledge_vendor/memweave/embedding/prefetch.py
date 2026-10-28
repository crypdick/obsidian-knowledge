"""Populate the embedding cache in batches spanning small files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from obsidian_knowledge_vendor.memweave._internal.hashing import make_provider_key, sha256_text
from obsidian_knowledge_vendor.memweave.chunking.markdown import chunk_markdown
from obsidian_knowledge_vendor.memweave.embedding.cache import get_cached_embeddings, store_embedding
from obsidian_knowledge_vendor.memweave.storage.files import build_file_entry, relative_path

if TYPE_CHECKING:
    from obsidian_knowledge_vendor.memweave.store import MemWeave

logger = logging.getLogger(__name__)
PREFETCH_FILES = 16
MAX_PREFETCH_BYTES = 16384


async def prefetch_embeddings(
    mem: MemWeave, paths: list[Path], workspace: Path, *, force: bool, completed: set[str]
) -> int:
    """Cache embeddings ahead of file transactions, retaining existing fallback behavior."""
    assert mem._store is not None
    store = mem._store
    config = mem.config
    texts: dict[str, str] = {}
    for path in paths:
        rel = relative_path(path, workspace)
        try:
            entry = build_file_entry(path)
            if entry["size"] > MAX_PREFETCH_BYTES:
                continue
            if not force or rel in completed:
                stored = await store.get_file(rel)
                if stored and stored["hash"] == entry["hash"]:
                    continue
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for chunk in chunk_markdown(
            content, chunk_tokens=config.chunking.tokens, chunk_overlap=config.chunking.overlap
        ):
            texts[sha256_text(chunk.text)] = chunk.text

    model = config.embedding.model
    provider_key = make_provider_key("litellm", model, config.embedding.api_base)
    hashes = list(texts)
    count = 0
    size = config.embedding.batch_size
    for start in range(0, len(hashes), size):
        group = hashes[start : start + size]
        cached = await get_cached_embeddings(store, group, model, provider_key)
        missing = [key for key in group if key not in cached]
        if not missing:
            continue
        try:
            vectors = await mem.embedding_provider.embed_batch([texts[key] for key in missing])
            if len(vectors) != len(missing) or any(not vector for vector in vectors):
                raise ValueError("incomplete embedding batch")
        except Exception as exc:
            logger.warning("Cross-file embedding batch failed; retrying per file: %s", exc)
            break
        for key, vector in zip(missing, vectors, strict=True):
            await store_embedding(store, key, vector, model=model, provider_key=provider_key)
        await store.commit()
        count += len(missing)
    return count
