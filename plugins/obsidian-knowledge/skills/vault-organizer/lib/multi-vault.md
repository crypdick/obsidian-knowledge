# Select another vault

Read this reference only when targeting another vault or when Obsidian and
`obsidian-knowledge` select different vaults.

## obsidian-knowledge

Routine vault commands, including `garden`, share this selection order:

1. Explicit `--vault ROOT`.
2. Registered vault containing the working directory.
3. First vault in `~/.config/obsidian-knowledge/vaults.yaml`.

Commands require an explicit or registered vault.
The first registered vault is the default outside registered vaults. Reorder
the registry to change that default. Malformed registries and missing selected
vaults are errors; they do not select another vault silently.

To target another vault from outside it, pass `--vault ROOT` to each command,
including reads, writes, and repairs. Note paths remain relative to that
vault's root. Follow its local instructions; commands load its zone configuration.

## Obsidian CLI

Use `obsidian vaults verbose` when the target's registered name is unknown.
For an observed target mismatch, `obsidian vault info=path` shows the current
Obsidian target.

Put `vault="NAME"` before every Obsidian subcommand targeting another vault;
after the subcommand, the CLI can silently ignore it. Use the registered name,
which can differ from the folder name. For example:

```bash
obsidian-knowledge garden audit --vault /absolute/path/to/other-vault
obsidian vault="Other Vault" unresolved verbose format=json | obsidian-knowledge garden links --vault /absolute/path/to/other-vault
obsidian vault="Other Vault" rename path="old/name.md" name="new-name.md"
```

For another vault, add the same selectors to the default-vault examples in the
organizer's other references.
