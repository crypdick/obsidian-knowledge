---
name: obsidian-knowledge
description: Read, search, and create notes in the Obsidian vault/wiki memory store.
---

# Obsidian Vault / Wiki Memory

Use the configured Obsidian vault as the durable memory/source of truth for
non-trivial context, project knowledge, and conversation outcomes. Vault roots
come from `~/.config/obsidian-knowledge/vaults.yaml`; paths passed to the CLI are
relative to that root and normally begin with `wiki/`.

## Repair encountered instructions

Before stopping, fix objectively stale guidance already encountered during the task
when the correction is clear and low risk: moved paths, obsolete commands with a
verified replacement, or factual guidance contradicted by current code. Verify the
replacement, edit its canonical source (not generated copies or plugin caches), and
run the relevant check. Follow the source repository's normal edit/install workflow.

Do not start a broad instruction audit, rewrite preferences, weaken safety or approval
rules, or override higher-priority instructions. If ownership, intended policy, or the
replacement is ambiguous, report the conflict instead of guessing. Do not reopen a
completed capture decision solely because a hook ran again. A code or instruction
repair does not by itself justify a vault note or changelog entry.

## Log workflow friction

When the harness, a tool, or a repeated workaround gets in the way, record it without
starting an implementation side quest:

```bash
obsidian-knowledge papercut "search hung after an automatic rebuild"
```

The command appends an entry to `wiki/repos/<owner>/<repo>/PAPERCUTS.md` when the
current directory has an identifiable Git `origin`; otherwise it falls back to
`wiki/systems/knowledge-base/PAPERCUTS.md`. The log records the working directory
and is lock-protected for concurrent agents. It records the papercut only; continue
the task unless the user asks to investigate or fix it.

## Frontmatter timestamps

Do **not** manually edit `updated:` timestamps in Obsidian notes. The vault linter manages `updated` metadata automatically; content edits should leave existing timestamp fields alone unless the user explicitly asks for timestamp repair.

## Read a note

```bash
obsidian-knowledge read "wiki/path/to/note.md"
```

## Search

```bash
obsidian-knowledge search "concept or phrase"
```

## Create a note

`write` reads literal Markdown from stdin, rejects blank content and existing
files, writes atomically, fsyncs, then reads the final path back and compares the
bytes. Treat only `Wrote and verified:` as success.

```bash
obsidian-knowledge write "wiki/path/to/new-note.md" <<'ENDNOTE'
# Title

Literal Markdown with `identifiers`, `$()`, and [[wikilinks]].
ENDNOTE
```

## Update a note

Read the current note, integrate the change into the complete Markdown, then
replace it explicitly:

```bash
obsidian-knowledge read "wiki/path/to/existing-note.md"
obsidian-knowledge write "wiki/path/to/existing-note.md" --replace <<'ENDNOTE'
# Complete updated note

Preserved content plus the integrated durable change.
ENDNOTE
```

## Wikilinks

Obsidian links notes with `[[Note Name]]` syntax. When creating notes, use these to link related content.

## macOS TCC

If a known note cannot be read and the CLI reports `Operation not permitted`,
the parent process lacks Documents or Full Disk Access. Grant that process in
System Settings → Privacy & Security, restart it, and retry. Do not reinterpret
an access error as a missing note.
