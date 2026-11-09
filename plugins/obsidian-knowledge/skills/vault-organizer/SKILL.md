---
name: vault-organizer
description: >-
  Maintain Obsidian vault indexes, links, filenames, and note locations. Use for
  vault cleanup, substantial structural edits, scheduled maintenance, and
  on-demand vault secret scans.
---

# Vault organizer

Maintain indexes, links, filenames, and note locations. Preserve primary note
content except for intended link and frontmatter repairs. Use relevant `lib/`
references as needed.

For secret-scan-only requests, go directly to [Secret scans](#secret-scans).

## Setup

Use installed `obsidian-knowledge garden` commands and vault-relative paths.
Commands select the configured vault and load its zone policy. Follow local
naming and layout conventions; read `Utility/obsidian-knowledge/needs-attention.md`
for a general maintenance pass or a listed issue. For another vault or an
observed target mismatch, see [multi-vault selection](lib/multi-vault.md).

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
  [index conventions](lib/index-format.md). Describe children usefully; link
  child indexes, not just descendants.
- `EMPTY_FOLDER`: check sync state and local layout. Do not create empty indexes
  or delete folders automatically.
- `DUMPING_GROUND`: classify misplaced dated, design, diary, and conversation
  notes by meaning. Follow [note locations](lib/note-types.md).
- `STACKED_FRONTMATTER`: inspect with `obsidian-knowledge garden frontmatter NOTE_PATH`; review manually, because markers may be valid thematic breaks.
  `NEEDS_MERGE` requires [manual frontmatter repair](lib/stacked-frontmatter.md).
- `ILLEGAL_FILENAME`: review the path and offending characters against configured
  `illegal_filename_chars`. Checks cover visible files, attachments, and folders.
  Rename through Obsidian to preserve internal links; the audit does not rename.

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

Report completed changes and unresolved items. Successful commands verify their
writes; no routine readback or repeat scan is needed.

Use [state-file conventions](lib/state-files.md) for unresolved issues and
consequential structural or operational changes, not routine note edits.
