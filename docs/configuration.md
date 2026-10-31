# Configuration

Run [setup](index.md#installation) before configuring search or agent access.

## Shared preferences and host locations

Two independent files separate portable preferences from machine-specific paths:

| File | Contents | Synchronize across hosts? |
| --- | --- | --- |
| `~/.config/obsidian-knowledge/config.yaml` | Search filters and weights, protection and organization rules, relative creation-template selection | Yes, for example through a shared dotfiles overlay |
| `~/.config/obsidian-knowledge/vaults.yaml` | Ordered absolute paths to this host's vaults | Use a separate host-specific overlay or register locally |

Both follow `XDG_CONFIG_HOME` when set. `OBSIDIAN_KNOWLEDGE_CONFIG` overrides
only the preferences file; `OBSIDIAN_KNOWLEDGE_VAULTS_CONFIG` overrides only the
host registry. An explicit `--vault` selects a location without changing either
file. The shared preferences file rejects a `vaults` key, so a host's absolute
vault paths cannot accidentally become shared preferences.

Search, hooks, creation, and gardener commands all read the same preferences.
There is no implicit fallback to `<vault>/.claude/obsidian-knowledge.yaml`.
Migrate that file's preferences to the new shared path before upgrading.
Keep `vaults.yaml` local to each host.

```yaml
# config.yaml (shared)
vault_index:
  top_k: 5
ai_managed: [wiki]
```

```yaml
# vaults.yaml (host-specific)
vaults:
  - /absolute/path/on/this/host
```

### Host writer command

A shared vault should have one note-writing identity, including sync receivers,
desktop apps, MCP services and host CLI creation. Shared groups grant access but
do not make new files share an owner. Atomic replacement preserves the existing
UID/GID and fails safely when the writer cannot retain them.

To route host CLI `write` and `papercut` calls through the same identity, set an
argument-vector prefix in the host-local `vaults.yaml`:

```yaml
vaults:
  - /absolute/path/on/this/host
write_command:
  - /usr/local/bin/shared-vault-writer
```

The prefix applies only to roots registered in that host file; an explicit,
unregistered `--vault` keeps its normal local behavior. The CLI appends the
original subcommand and arguments without a shell, preserves
stdin and working directory, and returns the writer's exit code. Failures never
fall back to local writes. Reads, retrieval and lifecycle hooks stay local.
Before delegating a papercut it captures the caller's repository scope, so the
writer need not read the caller's private Git metadata. The internal
`papercut --repository owner/repo` argument carries that scope; an empty value
selects the global log, and unsafe components are rejected.

The target must run with a registry **without** `write_command`, avoiding
recursive delegation, and must have the intended shared preferences and vault
paths. Keep the writer executable and its environment accessible to that identity.
This is host execution configuration, not portable vault policy; do not put it in
shared preferences. Other tools creating notes directly must use the same identity.

To add search defaults to shared preferences, without selecting a vault:

```bash
obsidian-knowledge init-vault-index
```

Edit `vault_index.index` to choose files to index and `vault_index.digest` to
choose which indexed files appear in normal searches. `search --all` bypasses
the digest filter, but cannot return files excluded from the index.

Put naming conventions in the vault's `CLAUDE.md`. The organizer reads its zone
configuration from the shared preferences file: `ai_managed: [wiki]` selects managed
folders and is the default. Its state lives in
`Utility/obsidian-knowledge/`: `needs-attention.md` lists issues for review,
`reports/open-questions.md` collects question callouts, and `changelog/` records
completed vault changes.

`Utility/` and `wiki/` are siblings under the configured vault root. CLI paths
are relative to that root, regardless of the working directory. Use
`obsidian-knowledge write Utility/obsidian-knowledge/...` for state files;
CLI and MCP writes reject `wiki/Utility/...` before creating directories.
Existing misplaced files remain readable for recovery.

### Note creation

Creation defaults are opt-in and vault-owned. Choose a vault-relative template
and any paths to exclude in shared `config.yaml`:

```yaml
note_creation:
  template: templates/default.md
  exclude: [templates, archive]
```

There is no default template path, exclusion list, or metadata schema. In the
selected template, mark one single-line JSON mapping of frontmatter defaults:

```javascript
const defaults = /* obsidian-knowledge:creation-defaults */ {"recorded_at":"{{now}}","status":"draft"};
```

The variable name is arbitrary. The writer reads only the marked JSON value;
it never executes template code. JSON keys and values define the vault's own
metadata policy. `{{now}}` expands in strings to the current local time with
an explicit UTC offset. Static scalars, lists, objects, and null are supported.
For a Templater template, its initializer can consume the same mapping and
replace this token before merging missing properties. Keep any populated-file
guard in that template so edits and sync arrivals do not rerun initialization.

On a new Markdown file, CLI and MCP writes merge only missing frontmatter
properties before their single atomic write. Explicit properties, including
nulls, are preserved. Existing YAML formatting, comments, other properties,
body bytes, BOM, and line endings are retained. No property is implicitly added
or refreshed. Replacements and patches of existing notes never apply defaults;
`replace=True` on a missing file still counts as creation.

Without `note_creation.template`, writes retain their byte-for-byte contract.
The configured template itself, excluded paths, and non-Markdown files are
untouched by creation defaults. A missing template, invalid declaration,
malformed configuration, or malformed new-note frontmatter fails before creating
target directories. Template paths cannot resolve outside the vault.

This works with Obsidian closed. Headless writes use the supplied body and
destination; they do not execute interactive routing, prompts, or arbitrary
JavaScript from the template. The feature does not backfill existing notes,
install templates, or change any timestamp plugin's activation.

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
