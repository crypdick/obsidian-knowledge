# Select another vault

Read this reference only when targeting another vault or when Obsidian and
`obsidian-knowledge` select different vaults.

## obsidian-knowledge

Routine vault commands, including `garden`, share this selection order:

1. Explicit `--vault ROOT`.
2. Registered vault containing the working directory.
3. First vault in `~/.config/obsidian-knowledge/vaults.yaml`.
4. Working directory when no vault is registered, for backward compatibility.

The first registered vault is the default outside registered vaults. Reorder
the registry to change that default. Malformed registries and missing selected
vaults are errors; they do not select another vault silently.

To target another vault from outside it, pass `--vault ROOT` to each command,
including reads, writes, repairs, and verification. Note paths remain relative
to that vault's root. Read its local instructions, zone configuration, and
state files before maintenance.

## Obsidian CLI

Use `obsidian vaults verbose` to find registered Obsidian names and paths.
`obsidian vault info=path` shows the current target. Confirm both CLIs target
the same root before piping link results or moving files.

Put `vault="NAME"` before every Obsidian subcommand targeting another vault;
after the subcommand, the CLI can silently ignore it. Use the registered name,
which can differ from the folder name. For example:

```bash
obsidian vault="Other Vault" vault info=path
obsidian-knowledge garden audit --vault /absolute/path/to/other-vault
obsidian vault="Other Vault" unresolved verbose format=json | obsidian-knowledge garden links --vault /absolute/path/to/other-vault
obsidian vault="Other Vault" rename path="old/name.md" name="new-name.md"
```

For another vault, add the same selectors to the default-vault examples in the
organizer's other references.
