# Index format

Create `index.md` for nonempty managed folders unless local layout uses another
navigation file. Use the folder display name as title, omit frontmatter, and
link each child file and subfolder. Create child indexes before linking them;
a descendant link does not replace a child-index link. Empty folders need
triage, not empty indexes.

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

Give each entry a short description that helps readers choose what to open.
List subfolders first, then files alphabetically. Use path prefixes to resolve
ambiguous names, especially `index.md`. Add sections when they improve navigation.

## Reviewed index editing

Review child content to choose descriptions. The helper accepts reviewed
entries; it does not infer categories or descriptions:

```json
{
  "section": "Reference",
  "entries": [
    {"target": "wiki/topic/reference/index", "label": "Reference", "description": "protocols and guides"},
    {"target": "wiki/topic/note", "description": "topic overview"}
  ]
}
```

Pass reviewed entries as JSON:

```bash
obsidian-knowledge garden index wiki/topic/index.md --apply < entries.json
```

Omit `--apply` to preview. Supply `"title": "Topic"` instead of `section`
when creating a flat index. For an
existing sectioned index, `section` must identify one leaf heading exactly.
Multiple entry blocks, continuation text, and fenced examples are refused for
manual review.

Only the selected entry block is sorted: subfolder indexes first, then files
alphabetically. Existing matching entries are updated; other prose and sections
are preserved. Targets must exist and be visible. Protected sources, hidden
paths, symlinks, read-only paths, and paths outside managed zones are refused.
Applied writes use `obsidian-knowledge write`.

## Stale path-based wikilinks

Resolve the intended existing file before replacing a stale path. Prefer a
vault-relative target when basenames collide. See `broken-links.md` for safe
prefix recovery and ambiguity rules.

## Move files

Use Obsidian moves, not filesystem `mv`, so internal links update:

```bash
obsidian move path="old/path.md" to="new/folder/file.md" silent
```

Repair stale links when encountered.
