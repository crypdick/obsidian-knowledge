# MCP server

Expose vault search, read, write, and binary download operations over Streamable HTTP:

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
