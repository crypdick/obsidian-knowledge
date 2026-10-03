# Index format

## Create a missing index

Create `<folder>/index.md`:

- Use the folder's display name as the heading.
- Add one entry per child file and subfolder.
- Omit frontmatter.

Create indexes for nonempty managed folders only. Handle `EMPTY_FOLDER` as
triage. Respect local layouts that explicitly replace an index with another
navigation file. Create and verify child indexes before linking them from a
parent; a link to a descendant note does not index the child folder.

## Entry format

Use this structure for index entries:

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

- Put each entry on its own line: a wikilink, an em dash, and a short phrase
  that helps the reader decide whether to open the note.
- List subfolders first, then files alphabetically.
- Add a path prefix to distinguish duplicate `index.md` names, such as
  `[[systems/index]]` instead of `[[index]]`.

## Sectioned indexes

When folder contents split into distinct groups, use `##` headings:

```markdown
# Folder Name

## Active

- [[pantry]] — current inventory
- [[food-diary]] — tracking log

## Reference

- [[reference/index|Reference]] — background protocols and guides
```

Use sections for two or more distinct groups. Otherwise, use a flat list.

## Reviewed index editing

Read child notes and choose orientation phrases before editing. The helper
accepts reviewed entries; it does not infer categories or descriptions:

```json
{
  "section": "Reference",
  "entries": [
    {"target": "wiki/topic/reference/index", "label": "Reference", "description": "protocols and guides"},
    {"target": "wiki/topic/note", "description": "topic overview"}
  ]
}
```

Save the review as JSON, then render without writing:

```bash
uv run --no-project --with pyyaml --with pydantic python "$SCRIPTS/edit-index.py" \
  "$VAULT" wiki/topic/index.md < /tmp/index-review.json > /tmp/index-preview.md
```

Inspect the diff against the current index, then repeat with `--apply`. Supply
`"title": "Topic"` instead of `section` when creating a flat index. For an
existing sectioned index, `section` must identify one leaf heading exactly.
Multiple entry blocks, continuation text, and fenced examples are refused for
manual review.

Only the selected entry block is sorted: subfolder indexes first, then files
alphabetically. Existing matching entries are updated; other prose and sections
are preserved. Targets must exist and be visible. Protected sources, hidden
paths, symlinks, read-only paths, and paths outside managed zones are refused.
All applied writes use `obsidian-knowledge write` and verify final bytes.

## Stale path-based wikilinks

Resolve the intended existing file before replacing a stale path. Prefer a
vault-relative target when basenames collide. See `broken-links.md` for safe
prefix recovery and ambiguity rules.

## Move files

Always use the Obsidian CLI to move files; never use filesystem `mv`:

```bash
obsidian vault="<vault>" move path="old/path.md" to="new/folder/file.md" silent
```

After each move, verify that the new path exists and the old path no longer
exists within the configured filesystem root. CLI success text alone is
insufficient. Then search
the vault for the old filename to verify Obsidian updated all references. Fix any
stale wikilinks found.
