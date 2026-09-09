# Configuration

Run [setup](index.md#installation) before configuring search or agent access.

## Vault configuration

Store search filters, ranking weights, and organization zones in
`<vault>/.claude/obsidian-knowledge.yaml`. To create the search configuration:

```bash
obsidian-knowledge init-vault-index
```

Edit `vault_index.index` to choose files to index and `vault_index.digest` to
choose which indexed files appear in normal searches. `search --all` bypasses
the digest filter, but cannot return files excluded from the index.

Put naming conventions in the vault's `CLAUDE.md`. The organizer reads its zone
configuration from the same YAML file: `ai_managed: [wiki]` selects managed
folders and is the default. Its state lives in
`Utility/obsidian-knowledge/`: `needs-attention.md` lists issues for review,
`reports/open-questions.md` collects question callouts, and `changelog/` records
completed vault changes.

## Switch embedding models

Set these environment variables before running the CLI:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEMWEAVE_EMBEDDING_MODEL` | `ollama/bge-m3` | Embedding model identifier |
| `MEMWEAVE_EMBEDDING_API_BASE` | `http://127.0.0.1:11434` | Embedding endpoint |
| `MEMWEAVE_EMBEDDING_API_KEY` | Unset | Authentication, if required |

Changing the model causes the next search to rebuild the index.
For service and permission errors, see [search troubleshooting](CLI.md#search-health-and-network-access).

## Cache location

Each vault has a separate cache outside the vault, so vault sync tools do not
copy the search database between devices.

| OS | Cache directory |
| --- | --- |
| Linux | `${XDG_CACHE_HOME:-~/.cache}/obsidian-knowledge/<vault-key>/` |
| macOS | `~/Library/Caches/obsidian-knowledge/<vault-key>/` |

The vault key identifies the vault path. Set `OBSIDIAN_KNOWLEDGE_CACHE_ROOT` to
change the cache base; the CLI adds `obsidian-knowledge/<vault-key>/` beneath it.

## Keep the index fresh

Schedule a reindex to include edits made outside the agent. For example, this
hourly Linux cron entry uses a five-minute deadline:

```cron
0 * * * * $HOME/.local/bin/obsidian-knowledge reindex --vault $HOME/Documents/obsidian --timeout-seconds 300 >> $HOME/.cache/obsidian-knowledge/cron.log 2>&1
```

Replace the vault and log paths for your host, and create the log directory
first. On macOS, use `~/Library/Caches/obsidian-knowledge/` for the log.
Reindex processes changed files; overlapping runs skip indexing while another
process holds the lock.

## Global Codex sandbox access

Installing the plugin does not grant sandbox access. For sessions using
`workspace-write`, merge the following into `~/.codex/config.toml`. It applies
across repositories without selecting a dedicated permission profile. Replace
the example paths with absolute paths to your vault and [host cache](#cache-location).
Keep existing writable roots and domain rules; merge existing TOML tables rather
than declaring them twice. If `features.network_proxy` is already a boolean,
replace it with this table form.

```toml
[sandbox_workspace_write]
writable_roots = [
  "/path/to/obsidian/vault/wiki",
  "/path/to/obsidian/vault/Utility/obsidian-knowledge",
  "/home/your-user/.cache/obsidian-knowledge",
]
network_access = true

[features.network_proxy]
enabled = true

[features.network_proxy.domains]
"127.0.0.1" = "allow"
"localhost" = "allow"
```

The writable directories cover notes, papercut logs and their lock files,
changelog fragments, and the search cache. On macOS, use
`/Users/your-user/Library/Caches/obsidian-knowledge` for the cache entry. Run initial
`setup` from a terminal with vault access; these grants cover routine memory work,
not edits throughout every vault folder.

Keep the proxy enabled: `network_access = true` alone permits unrestricted command
network access. With the proxy active, this example allows localhost destinations
and blocks public destinations; add other required hosts to your existing policy
explicitly. The allowlist is host-based, not limited to the Ollama port. See the
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

These settings use the Codex `sandbox_workspace_write` configuration. Deployments
that enforce named permission profiles must configure the equivalent grants in
their active policy; the two permission systems do not compose. See
[Codex permissions](https://learn.chatgpt.com/docs/permissions).

Restart Codex and open a new session after changing permissions. Verify from the
repository where you normally work, using a phrase from an indexed note:

```bash
codex sandbox -c 'sandbox_mode="workspace-write"' -- obsidian-knowledge search "known note phrase"
codex sandbox -c 'sandbox_mode="workspace-write"' -- python3 -c 'import tempfile; tempfile.TemporaryFile(dir="/path/to/obsidian/vault/wiki").close()'
```

The first command should return matching notes without `ranking degraded`; the
second should exit successfully and leave no note behind. These checks were
verified on Linux with Codex 0.153.4. In that version, inherit the shell's working
directory: adding `codex sandbox -C` requires a named profile. A successful search
from an unrestricted terminal alone does not verify sandbox access.
