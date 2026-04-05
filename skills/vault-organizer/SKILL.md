---
name: vault-organizer
description: >-
  This skill should be used when the user asks to "organize the vault",
  "update indexes", "fix broken links", "garden the vault", "sync indexes",
  "clean up the vault", "maintain the vault", or after making substantial
  structural edits (creating, moving, renaming, or deleting files) in an
  Obsidian vault. Also triggered by scheduled cron invocations for routine
  vault maintenance.
version: 0.1.0
---

# Vault Organizer

Maintain an Obsidian vault's structural organization: sync indexes, organize
files, detect and fix broken links, and report unresolvable issues. This skill
runs a single-pass pipeline that never edits the content of primary files —
only indexes, links, and file locations.

## Prerequisites

- **Obsidian CLI** must be installed and configured
  (`Settings → General → Command line interface`)
- **"Use [[Wikilinks]]"** must be enabled in Obsidian settings
- **"Automatically update internal links"** must be enabled in Obsidian settings
- If more than one vault is registered in Obsidian, specify which vault to
  target in every CLI call (e.g., `obsidian vault="My Vault" ...`). The CLI
  defaults to the most recently focused vault, which may not be the one being
  organized.

## State files

All persistent state lives in `<vault>/.config/obsidian-knowledge-base-skill/`.
Create this directory on first run if it does not exist.

### CHANGELOG.md

Append-only log of actions taken. Newest entry first. Each run adds a
date-stamped section with one-line entries describing each action taken.

Format:
```
# Changelog

## YYYY-MM-DD

- Created `folder/index.md` (N entries)
- Moved `old/path.md` → `new/path.md` via `obsidian move`
- Fixed N stale links found during move sanity check
- Added N items to NEEDS_ATTENTION
- Resolved N items from NEEDS_ATTENTION
```

### NEEDS_ATTENTION.md

Living worklist of issues requiring human judgment. Entries are `- [ ]`
checkboxes with file path, issue description, and any candidates considered.
Delete entries when resolved — do not check them off.

Format:
```
# Needs Attention

- [ ] `file.md:15` — unresolved link to `target.md`. Candidate: `other.md`
  covers similar topic but not confident it's the intended target
- [ ] `file.md:30` — unresolved link to `missing.md`, no matching file found
```

## Pipeline

Execute these steps in order each run.

### Step 0: Ensure Obsidian is running

Run `obsidian version`. If it fails, launch Obsidian (e.g., run `obsidian` or
open it via the system launcher) and retry `obsidian version` up to 3 times
with a few seconds between attempts. If Obsidian still cannot be reached,
log the failure to CHANGELOG and exit.

### Step 1: Read state

Read `NEEDS_ATTENTION.md` if it exists. Parse existing entries to:
- Avoid re-investigating known issues
- Detect items that have been resolved since last run (the referenced file or
  link now exists)

### Step 2: Scan structure

Walk the vault directory tree, skipping dotfolders (`.obsidian`, `.config`,
`.git`, `.trash`, etc.). Build a map of:
- All folders and which have an `index.md`
- All `.md` files and their locations
- All non-markdown files and their locations
- Parent-child folder relationships

### Step 3: Organize files

For files clearly misplaced (in a parent folder when a more specific child
folder exists, or not matching their folder's topic scope):

When in doubt, do not move — only relocate a file when the correct
destination is unambiguous from folder naming alone.

1. Use `obsidian move path="old/path.md" to="new/folder"` to relocate files
   and `obsidian rename path="file.md" name="new-name"` for in-place renames.
   Never use raw filesystem `mv` or `rename`.
2. After each move, grep the vault for the old filename as a sanity check that
   all references were updated by Obsidian.
3. If any stale references are found during this check — whether markdown-style
   links `[text](path)`, raw unlinked path mentions (e.g., `See ../folder/file.md`),
   or wikilinks that did not update — convert them to proper wikilinks.

Do not do a standalone vault-wide scan for markdown links. Only fix link format
issues encountered opportunistically during move/rename sanity checks.

### Step 4: Sync indexes

For every folder in the vault:

**If no `index.md` exists:** Create one with a heading matching the folder name
and thin pointer entries for each file and subfolder.

**If `index.md` exists:** Add entries for files/subfolders not yet listed.
Remove entries pointing to files that no longer exist. Preserve any existing
entries that are still valid.

#### Index entry format

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

Rules:
- One entry per line: wikilink + em dash + orientation phrase (~3-8 words)
- The phrase answers "what is this?" — enough to decide whether to open the
  file. Not a summary. Not a sentence.
- Subfolders first (linking to their `index.md` with display alias), then
  files alphabetically
- Disambiguate duplicate `index.md` names with relative path:
  `[[systems/index]]` not `[[index]]`
- No frontmatter, no properties, no metadata on the index itself
- The heading is the only non-list content in the file

### Step 5: Detect and fix broken links

Run `obsidian unresolved verbose format=json` to get all unresolved links
with their source files.

For each unresolved link, apply this resolution logic in order:

1. **Exact name match:** Search the vault for a file with the same name. If
   found (it was moved), fix the link to point to the new location.
2. **Similar match:** Search for files with similar names or overlapping
   content. If one is a clear match with high confidence, fix the link.
3. **Ambiguous candidate:** If a plausible candidate exists but confidence is
   low, add to NEEDS_ATTENTION with the candidate noted.
4. **No match:** If nothing resembles the target, add to NEEDS_ATTENTION with
   no candidate.

Also run:
- `obsidian orphans` — files with no incoming links. Add orphans to their
  parent folder's index if not already present.
- `obsidian deadends` — files with no outgoing links. Informational only;
  many leaf files legitimately have no outgoing links. Do not flag these.

### Step 6: Update NEEDS_ATTENTION.md

Remove entries for issues resolved during this run. Add new entries for
unresolvable issues found. Write the file (or delete it if empty).

### Step 7: Append to CHANGELOG.md

Add a date-stamped section at the top summarizing all actions taken: files
moved, indexes created/updated, links fixed, NEEDS_ATTENTION items
added/resolved. If no actions were taken, write "No changes needed."
