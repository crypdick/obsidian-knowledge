# MCP server

Expose vault search, read, and write operations over Streamable HTTP:

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
- `vault_write(path, content, replace=False)` atomically writes UTF-8 content,
  verifies final bytes, and returns the vault-relative path and success status.
  Blank content and existing files are rejected unless `replace=True` permits
  overwriting. Parent directories are created as needed.

Paths are relative to the server's fixed vault. Absolute paths and symlink or
parent-directory escapes are rejected. These tools share the CLI's file
safeguards; agent lifecycle hooks and zone policies do not run on MCP calls.
No delete or move tools are exposed.

Search uses the existing CLI in a subprocess, preserving its configuration,
cache, filtering, and semantic-ranking fallback. Concurrent searches serialize.
Each active search has the CLI deadline plus a ten-second cleanup allowance;
cancellation or timeout kills and reaps its subprocess. The server remains
available for file operations during searches. Queue waiting is outside this
active-search deadline.

Search uses the current index. After changing notes, run the existing
`obsidian-knowledge reindex --vault /absolute/path/to/vault` workflow to refresh
it. MCP writes do not automatically reindex. See [CLI reference](CLI.md) for
indexing, embeddings, and search timeout configuration.
