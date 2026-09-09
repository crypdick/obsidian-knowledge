# Hooks and vault protection

Hooks recall vault context at session start, protect registered vaults during
edits, and prompt agents to save reusable knowledge at session end.
Run [setup](index.md#installation) to register your vault: protection depends on
`~/.config/obsidian-knowledge/vaults.yaml`.

## Vault protection

The tool-call guard applies these rules:

| Target | Protection |
| --- | --- |
| `_sources/` directories | Block writes, renames, moves, and deletion of original files. Reading is allowed. |
| Files with `dg-publish: true` | Block writes and edits because they affect published pages. |
| Vault paths in destructive commands | Block recognized destructive operations, including recursive removal and moves. |
| Built-in project auto-memory | Redirect operational knowledge to the wiki. |

After explicit user confirmation, prefix a shell command with
`I_AM_BEING_CAREFUL=1` to bypass the source and published-file guards.
The memory redirect has no bypass. These checks cover recognized tool calls;
they do not replace filesystem permissions or backups.

## Memory and recall

The session primer gives the agent its memory location and search instructions.
Repository memory lives in `wiki/repos/<owner>/<repo>/memory/`; outside a
repository, it lives in `wiki/systems/machines/<hostname>/memory/`.
Each directory contains a small `MEMORY.md` index linked to individual facts.
Hermes profile memory uses `wiki/systems/knowledge-base/index.md`.

The capture reminder invokes `remember-conversations` only for reusable
knowledge that is not already available elsewhere. It also requests repairs to
verified stale instructions encountered during the task. It does not request a
broader audit. Filing nothing is a valid outcome.

Do not edit a user's `CLAUDE.md` unless they explicitly request it. If they want
sessions without the plugin to find their memory, they can add:

```markdown
Agent memory is managed by the obsidian-knowledge plugin; refer to it
for memory location, read/write conventions, and session-start recall.
```

## Secret scanning

The Stop hook scans for unaudited secrets. The first scan covers the vault;
subsequent scans are incremental. Run `/scan-secrets` for an on-demand scan, or
`/scan-secrets full` to rescan all eligible files while preserving audit decisions.
The scanner requires uv, which installs its dependencies automatically.

Document your secrets-management convention in the vault so the agent can
follow it when findings need attention. Review findings before redacting files
or marking false positives. For a false positive in Markdown, append this
sentinel on the same line:

```markdown
Example token: fake-token <!-- pragma: allowlist secret -->
```

To review existing findings in bulk, run `detect-secrets audit` against the
vault's `.secrets.baseline`. For leaked passphrases that the scanner misses, add
one value per line to `<vault>/.secrets.known-leaked` for exact matching.

## Workflow friction

Agents must fix and verify defects introduced by or required for their task.
For unrelated tooling friction, they can record a
[papercut](CLI.md#papercut-logs) and continue. A reminder repeats this distinction
every 100 shell calls.
