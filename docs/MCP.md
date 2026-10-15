# MCP server

Expose vault search, editing, discovery, index maintenance, and binary downloads over Streamable HTTP:

```bash
obsidian-knowledge-mcp --vault /absolute/path/to/vault
```

The endpoint is `http://127.0.0.1:8000/mcp`. The server uses stateless requests
and JSON responses. Set `--host` and `--port` to change the listener. Without
`--vault`, it uses the CLI's registered-vault selection rules.

For a listener reached through a private hostname, explicitly trust its Host
header while preserving DNS rebinding protection:

```bash
obsidian-knowledge-mcp --vault /absolute/path/to/vault \
  --host 0.0.0.0 --allowed-host 'vault-server:*'
```

`--allowed-host` is repeatable. It adds trusted Host headers, not browser
origins; browser cross-origin access is not enabled.

## Authentication

The default loopback listener has no authentication. To require a bearer token,
set `OBSIDIAN_KNOWLEDGE_MCP_TOKEN` in the server environment. Clients must send
`Authorization: Bearer <token>` for every request, including discovery.
Keep tokens outside tracked files. Use TLS or a trusted private transport when
sending a token across a network. Tunnel provisioning is separate from this server.

## Tools

- `vault_search(query, top_k=None, all_paths=False)` returns a structured search
  report with `mode`, `degraded_reason`, and scored `hits`. `top_k` must be
  positive. `all_paths` bypasses the digest filter, retaining index exclusions.
- `vault_read(path)` returns UTF-8 file content.
- `download_file(path)` delivers original bytes as an embedded MCP binary
  resource, with filename, MIME type, byte count, and SHA-256 in structured
  metadata. Files above 6 MiB are rejected before encoding; the file reader
  reads at most the limit plus one byte. Empty files are supported. Unknown
  MIME types use `application/octet-stream`.
- `vault_write(path, content, replace=False)` atomically writes UTF-8 content,
  verifies final bytes, and returns the vault-relative path and success status.
  Blank content and existing files are rejected unless `replace=True` permits
  overwriting. Parent directories are created as needed.
- `vault_patch(path, old_str, new_str, expected_sha256=None)` replaces exactly
  one occurrence of `old_str` in a UTF-8 file, including frontmatter. Empty,
  missing, and ambiguous matches (including overlaps) are rejected. Untouched
  bytes, line endings, and file permissions are preserved. An optional lowercase
  SHA-256 of the original file rejects stale edits. The original bytes are
  checked again immediately before replacement; blank output is rejected.
- `vault_list(path="", recursive=False, depth=3, pattern=None, limit=100,
  offset=0)` returns `entries` and `next_offset`. Entries contain vault-relative
  `path`, `name`, `is_directory`, and `size_bytes` (null for directories).
  Nonrecursive listings return immediate children; recursive depth counts those
  children as level one and must be between 1 and 10. Pages contain at most
  `limit` matching entries (1–500). Pass `next_offset` as the next request's
  `offset`; null means the last page. Ordering is sorted depth-first. Vault
  changes between calls can shift pages. Optional case-sensitive `fnmatch`
  patterns match paths relative to the requested directory; `*` also matches
  `/`. Filtering does not prune directories. Hidden paths, `node_modules`,
  `_sources`, sync-conflict paths, and symlinks are excluded; directly requesting
  an excluded directory is rejected. Files of all formats can be listed.
- `vault_search_status()` returns `index_exists`, `indexed_files`,
  `vector_index_ready`, and `degraded_reason`. Readiness checks persisted vector
  schema and embedding settings only. Endpoint availability and file freshness
  remain unknown. Missing or unreadable indexes report a reason without creating
  or repairing the index.
- `vault_search_update()` runs incremental indexing using the existing CLI and
  fixed vault. Returns `status="updated"` with `indexed`, `skipped`, and `deleted`
  counts, or `status="busy"` with null counts when another process holds the
  index lock. Refresh after writes or patches when searches need current content.

Paths are relative to the server's fixed vault. Absolute paths and symlink or
parent-directory escapes are rejected. These tools share the CLI's file
safeguards; agent lifecycle hooks and zone policies do not run on MCP calls.
No delete or move tools are exposed.

Writes and patches serialize within one server, including when a client cancels
while its write thread is still running. Patch baseline checks detect edits
before replacement but cannot guarantee atomic comparison and replacement
against external editors or sync processes.

Search and refresh use the existing CLI in subprocesses, preserving its
configuration, cache, filtering, and semantic-ranking fallback. Searches,
refreshes, and status calls serialize. Each active subprocess uses the configured
search deadline (`OBSIDIAN_KNOWLEDGE_SEARCH_TTL_SECONDS`) plus a ten-second
cleanup allowance; refresh also passes that deadline to the CLI. Cancellation
or timeout kills and reaps the subprocess. File operations remain available
during indexing. Queue waiting is outside the active-operation deadline.

Search uses the current index. Writes and patches do not automatically reindex.
Use `vault_search_update()` or the existing
`obsidian-knowledge reindex --vault /absolute/path/to/vault` workflow after
changing notes. See [CLI reference](CLI.md) for indexing, embeddings, and search
timeout configuration.

## Binary file delivery

`download_file` works for arbitrary file formats without extracting, converting,
or decoding their contents. The resource contains a base64 `blob`; it is a
binary MCP content block, not base64 dumped into a text message. The
`obsidian-vault:///...` URI identifies the embedded resource and is not a public
download URL. The client already receives the bytes in the tool response;
this server does not expose a separate `resources/read` endpoint for that URI.

The client chooses where and how to save the file. No destination filesystem
path is sent to the server. Client support for turning this resource into an
attachment or an analysis-workspace file varies and must be tested on the
intended client. HTTP MCP tests verify byte recovery, not ChatGPT workspace
materialization. After installing the new version, restart a running MCP
server and refresh the client's tool discovery before trying `download_file`.

Base64 increases payload size by roughly one third. The raw-byte ceiling bounds
server memory use; individual clients or transports may impose lower response
limits. The tool rejects oversized files instead of truncating them.
