# Repository Guidelines

## Codex Plugin Maintenance

Use Codex's native plugin marketplace flow for normal install, refresh, and upgrade work. Do not edit `~/.codex/plugins/cache` by hand except as a break-glass recovery step when a broken hook prevents Codex from running tools.

This repo is a local Codex marketplace. Register it with:

```bash
codex plugin marketplace add "$(pwd)"
```

For a configured Git marketplace, refresh its published snapshot through Codex:

```bash
codex plugin marketplace upgrade obsidian-knowledge
codex plugin add obsidian-knowledge@obsidian-knowledge
```

For local source changes, register the control checkout path with `marketplace add`
and then run `codex plugin add obsidian-knowledge@obsidian-knowledge`. A marketplace
refresh alone does not install the plugin. Never register a temporary worktree that
will be removed after integration.

This plugin's Codex hooks call the installed `obsidian-knowledge` CLI, so keep the uv tool install in sync with the source package:

```bash
uv tool install --reinstall --python 3.13 "$(pwd)"
```

Then restart Codex and use `/plugins` or `/hooks` for install, enablement, and hook trust review. If `obsidian-knowledge _hook ...` fails, fix or reinstall the CLI; do not treat the plugin cache as the source of truth.
