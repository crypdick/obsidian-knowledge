# Repository guidelines

## Codex plugin maintenance

Use native Codex marketplace commands, not manual edits to
`~/.codex/plugins/cache`, except emergency recovery from a hook that prevents
Codex tools from running.

For local changes, register the permanent control checkout and install:

```bash
codex plugin marketplace add "$(pwd)"
codex plugin add obsidian-knowledge@obsidian-knowledge
uv tool install --reinstall --python 3.13 "$(pwd)"
```

Never register a disposable worktree. For a configured Git marketplace, use
`codex plugin marketplace upgrade obsidian-knowledge` before `plugin add`.
Refreshing a marketplace alone does not install the plugin.

Codex hooks call the installed CLI, so keep it in sync with source. Fix CLI
hook failures there, not in the plugin cache. Restart Codex after installation
and review enablement and hook trust through `/plugins` or `/hooks`.

## Development

See `CONVENTIONS.md` for design, `docs/ARCHITECTURE.md` for boundaries and
worktree setup, and `docs/QUALITY.md` for checks. Edit root hook and skill sources;
regenerate the Codex copy with `uv run python scripts/sync_codex_plugin.py`.

`new-feature merge` runs the full manual-stage gate before integration; do not
repeat it at commit or after merge. Release CI owns versions; ordinary commits
need no version bumps.
