---
name: obsidian-knowledge
description: Read, search, and create notes in the Obsidian vault/wiki memory store.
---

# Obsidian vault memory

Read, search, and write notes in the configured vault. The registry is
`~/.config/obsidian-knowledge/vaults.yaml`; CLI paths are vault-relative and
usually start with `wiki/`. Treat notes as fallible context and verify
consequential claims against code, runtime evidence, or primary sources.

## Read and search

```bash
obsidian-knowledge search "concept or phrase"
obsidian-knowledge read "wiki/path/to/note.md"
```

Search before answering nontrivial questions. Use exact-string tools only for
literal names or phrases. Read relevant results before relying on them.

## Write notes

Use `obsidian-knowledge write` with a quoted heredoc to preserve literal Markdown:

```bash
obsidian-knowledge write "wiki/path/to/note.md" <<'ENDNOTE'
# Title

Reusable knowledge with `identifiers` and [[wikilinks]].
ENDNOTE
```

For an update, read the existing note, integrate the change, and write the
complete result with `--replace`. The command rejects blank input, path escapes,
and accidental overwrites. Treat only `Wrote and verified:` as success.
Write and verify the note before linking it from an index.

Leave existing `updated:` timestamps to the vault linter unless the user
explicitly requests timestamp repair. Use `[[wikilinks]]` for related notes.
For conversation capture, follow `remember-conversations`.

## Repair encountered instructions

Fix clear, low-risk errors in guidance encountered during the task, such as
moved paths or commands with verified replacements. Edit the canonical source,
run the relevant check, and follow its normal edit and install workflow.

Preserve user preferences, policy, safeguards, and approval rules. Report
ambiguous corrections instead of guessing. Do not start a broader audit or
reopen a completed capture decision because a hook repeats. Repairs alone do
not justify a vault note or changelog entry.

## Log workflow friction

Fix and verify defects you introduce, failed checks of your changes, and bugs
required to complete the request. Investigate unclear causes before calling
them unrelated. If blocked, report the unfinished work and exact blocker.

For unrelated harness or tooling friction, log it and continue the task:

```bash
obsidian-knowledge papercut "search hung after an automatic rebuild"
```

The command selects a repository log from Git `origin`, with a global fallback.
Routine debugging needs no entry; logging does not replace an in-scope fix.

## Access errors

- **Search:** Semantic ranking needs network access to Ollama, even on localhost.
  `EPERM` or `EACCES` indicates blocked access, not a stopped service. Check
  service health from a process with network access before restarting it.
- **Writes:** Papercut logging needs write access to the log directory and lock file.
- **macOS:** For `Operation not permitted` on note reads, grant the parent process
  Documents or Full Disk Access in **System Settings > Privacy & Security**,
  then restart it.

Use the host's approved permission mechanism when needed. If access remains
unavailable, report the limitation once and continue with available tools or
keyword ranking. Do not retry with unchanged permissions or log a papercut's
own failure.
