---
description: Hybrid (BM25 + dense vector) search over the Obsidian vault. Returns top-K paths ranked by relevance. Use this before answering non-trivial questions instead of `rg`.
---

# Vault Search

Run hybrid retrieval against the vault index. Combines BM25 keyword scoring with dense embedding similarity (Ollama / `bge-m3` by default), fused by memweave. The vector lane gracefully falls back to FTS-only if Ollama is unreachable.

## When to use

- Looking up a topic, person, system, or concept by meaning, not exact phrase.
- You want freshness + relevance ranking, not a flat grep dump.
- Paraphrased queries: ask in your own words, the embed lane handles synonyms.

For exact-string lookups (a known function name, a specific token, a literal phrase), `rg` is still faster and exact.

## Steps

1. Run the search. If `$ARGUMENTS` is empty, ask the user what they want to search for and stop.

   ```bash
   uv run --project "${CLAUDE_PLUGIN_ROOT}" obsidian-knowledge search "$ARGUMENTS"
   ```

   To include normally-hidden paths (Inbox, Journal, sources), append `--all`:

   ```bash
   uv run --project "${CLAUDE_PLUGIN_ROOT}" obsidian-knowledge search "$ARGUMENTS" --all
   ```

2. Surface the printed `score  path` lines verbatim.

3. Open the top 1–3 results with `Read` if the user wants the actual content (don't dump everything — paths are cheap, full reads aren't).

4. If the first stderr line says `vector lane off`, mention it once so the user knows results are FTS-only and can fix Ollama if they want semantic search back.

User arguments: $ARGUMENTS
