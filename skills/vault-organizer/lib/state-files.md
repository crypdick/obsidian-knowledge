# State files

State lives at `<vault_root>/Utility/obsidian-knowledge/`. Create the directory if missing.
Use the configured vault root, not its `wiki/` subdirectory. `Utility/` and
`wiki/` are siblings. Pass `Utility/obsidian-knowledge/...` unchanged to
`obsidian-knowledge write`, regardless of cwd; never prepend `wiki/`.

## `changelog/`

Log consequential structural or operational changes that could help explain
future inconsistent state. Routine note, index, and link edits need no fragment.
When logging is warranted, create one file for the session and reuse it;
never append to another session's file.

Name the file `YYYY-MM-DD-HHMMSS-<slug>.md`; when the Stop hook supplies a
capture key, reuse `*-session-<capture-key>.md`. Use short, self-contained lines:

```text
YYYY-MM-DD HH:MM — Migrated wiki/old-system/ → wiki/new-system/
```

For session logs, do not create or update `changelog/index.md`. The Utility
zone is excluded from structural index enforcement; a shared index risks
concurrent writes. No consequential change means no fragment.

## `needs-attention.md`

Use `- [ ]` entries with the affected path, issue, and any useful candidate or
proposed fix. Remove resolved entries. Leave `## Secret scan findings` to the
scanner.
