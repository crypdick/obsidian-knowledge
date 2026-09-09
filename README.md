# Obsidian Knowledge

Give Claude Code, Codex, or Hermes persistent memory in an Obsidian vault.
Search your notes, save reusable knowledge, and maintain indexes and links.
The CLI also works without an agent or the Obsidian app running.

[Documentation](https://crypdick.github.io/obsidian-knowledge/) ·
[CLI reference](docs/CLI.md) ·
[Contribute to the docs](docs/contributing-docs.md)

## Installation

Install [uv](https://docs.astral.sh/uv/), then run these commands with the absolute
path to an existing vault:

```bash
uv tool install obsidian-knowledge
obsidian-knowledge setup --vault /absolute/path/to/vault
obsidian-knowledge doctor --query "a phrase from one of your notes"
```

Setup registers and indexes the vault. It also installs the Claude Code plugin
when `claude` is on `PATH`. Add `--skip-claude-plugin` for CLI-only, Codex, or
Hermes use. Setup is safe to rerun. For a large first index, add
`--timeout-seconds 900`.

The CLI requires Python 3.12 or later. uv selects it automatically.
Upgrade with `uv tool upgrade obsidian-knowledge`.

### Codex installation

After setup, install the plugin:

```bash
codex plugin marketplace add crypdick/obsidian-knowledge
codex plugin add obsidian-knowledge@obsidian-knowledge
```

Restart Codex and review enablement and hook trust through `/plugins` or `/hooks`.
Configure [sandbox access](docs/configuration.md#global-codex-sandbox-access)
if your sessions restrict vault writes or network connections.
For a source installation, follow the
[repository guidelines](https://github.com/crypdick/obsidian-knowledge/blob/main/AGENTS.md).

### Hermes plugin install

```bash
hermes plugins install crypdick/obsidian-knowledge --enable
hermes config set memory.provider obsidian-knowledge
hermes config set memory.memory_enabled false
hermes config set memory.user_profile_enabled false
```

The provider uses the wiki instead of Hermes's built-in `MEMORY.md` and `USER.md`.
Update it with `hermes plugins update obsidian-knowledge`.

### Enable semantic search

Keyword search works without a server. For semantic ranking, install and start
[Ollama](https://ollama.com/), then run:

```bash
ollama pull bge-m3
obsidian-knowledge reindex --timeout-seconds 300
```

See [search troubleshooting](docs/CLI.md#search-health-and-network-access) if
results report degraded ranking.

## Usage

Search from the terminal:

```bash
obsidian-knowledge search "topic or phrase"
```

Or ask your agent to use a skill:

| Skill | Example request | Result |
| --- | --- | --- |
| `obsidian-knowledge` | "Find my notes on this project." | Search, read, and write vault notes. |
| `remember-conversations` | "Remember this decision." | Update a relevant note with reusable knowledge. |
| `vault-organizer` | "Organize my vault and fix broken links." | Maintain indexes, filenames, and links; report ambiguous cases. |

Vault organization requires the Obsidian CLI. In Obsidian, enable
**Settings > General > Command line interface**, **Use [[Wikilinks]]**, and
**Automatically update internal links**. Put naming conventions in your vault's
`CLAUDE.md` and configure [managed zones](docs/configuration.md#vault-configuration).

Hooks provide session recall, selective memory capture, vault protection, and
secret scanning. See [hooks and vault protection](docs/hooks.md) for their
behavior and limits.

## Keep notes searchable

Run `obsidian-knowledge reindex --timeout-seconds 300` after changing notes.
The CLI has no file watcher. For scheduled indexing and other settings, see
[configuration](docs/configuration.md).

## Development

Read the [design conventions](https://github.com/crypdick/obsidian-knowledge/blob/main/CONVENTIONS.md),
[architecture](docs/ARCHITECTURE.md), and [quality checks](docs/QUALITY.md).

## License

MIT
