---
name: vault-organizer
description: >-
  Maintain Obsidian vault indexes, links, filenames, and note locations. Use for
  vault cleanup, substantial structural edits, scheduled maintenance, and
  on-demand vault secret scans.
---

# Vault organizer

Maintain indexes, links, filenames, and note locations. Preserve primary note
content except for intended link and frontmatter repairs. Use only the sections
needed for the request; read `lib/` references when their guidance applies.

For secret-scan-only requests, go directly to [Secret scans](#secret-scans).

## Setup

Use the installed `obsidian-knowledge garden` commands. After setup, they use
the configured default vault without environment variables or flags. All note
paths are vault-relative.

Trust the configured vault and successful command output. Investigate targeting
or write problems when errors or results give reason. For another vault or an
observed target mismatch, read
[multi-vault selection](lib/multi-vault.md).

Follow the vault's local naming and layout instructions. Commands load
`.claude/obsidian-knowledge.yaml` themselves. Read
`Utility/obsidian-knowledge/needs-attention.md` for a general maintenance pass
or when working on a listed issue.

Exclude hidden files, protected sources, and Syncthing sync conflicts from
maintenance. Handle conflicts separately. Repairs refuse existing published
notes; use the manual edit and human-consent workflow. Use `obsidian-knowledge
write` for manual Markdown edits; its writer verifies the result.

## Structure

```bash
obsidian-knowledge garden audit
```

Triage findings within the requested scope:

- `MISSING_INDEX`, `NOT_INDEXED`: create or complete indexes using
  [index conventions](lib/index-format.md). Read children to write useful
  orientation phrases; a descendant link does not replace a child-index link.
- `EMPTY_FOLDER`: check sync state and local layout. Do not create empty indexes
  or delete folders automatically.
- `DUMPING_GROUND`: classify misplaced dated, design, diary, and conversation
  notes by meaning. Follow [note locations](lib/note-types.md).
- `STACKED_FRONTMATTER`: use `obsidian-knowledge garden frontmatter --apply NOTE_PATH`.
  `NEEDS_MERGE` requires [manual frontmatter repair](lib/stacked-frontmatter.md).

Rename ambiguous files using [rename guidance](lib/rename-files.md).
Use Obsidian move and rename commands with automatic internal-link updates.

## Links

```bash
obsidian unresolved verbose format=json | obsidian-knowledge garden links --apply
```

The command repairs unique recoveries and reports remaining links. Omit
`--apply` to preview. Triage remaining links using
[broken-link guidance](lib/broken-links.md). Preserve aliases, headings,
block references, and primary text. Leave intentional concept stubs intact.

```bash
obsidian orphans
```

Add managed notes to their parent indexes where appropriate. Respect established
exceptions and ignore orphans outside managed zones.

## Question report

```bash
obsidian-knowledge garden questions --apply
```

Fix `WIKILINK_EXT` (`.md` in note links), `UNDATED_FILE` (missing required date
prefix), and `YAML_ERR` from the audit. The question report defaults to
`Utility/obsidian-knowledge/reports/open-questions.md`, preserving its header,
frontmatter, and scope. Use `--report` to preview or `--timestamp` to override
current local time. With no flags, the scanner emits TSV.

## Secret scans

For an on-demand secret scan, run from inside the registered target vault:

```bash
uv run --script "<plugin-root>/hooks/scan-vault-secrets.py" --manual
```

Resolve `<plugin-root>` from this skill's loaded path: two directories above
`skills/vault-organizer/`. This works in Claude and Codex without assuming a
host-specific environment variable. uv installs the scanner's dependencies.

`--manual` bypasses the Stop-hook cooldown. Append `--full` when the user requests
a full rescan; it preserves audit decisions for surviving findings. The first
scan also covers all eligible files; subsequent scans are incremental.

Report counts, paths, and next steps from the scanner's output. Redact secret
values from known-leaked literal samples before displaying them. Exit status
zero also occurs with findings; claim clean only when output says clean.
Do not redact notes or change audit decisions automatically; the user decides
which findings are real and authorizes remediation.

## Finish

Report completed changes and unresolved items. Successful commands need no
separate readback, checksum comparison, or repeat scan.

Update unresolved items in `needs-attention.md`. Record consequential structural
or operational changes in one same-session changelog fragment using
[state-file conventions](lib/state-files.md). Routine note, index, and link
edits need no changelog. Do not edit a shared changelog index.
