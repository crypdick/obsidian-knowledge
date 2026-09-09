# Index format

## Create a missing index

Create `<folder>/index.md`:

- Heading = folder display name
- One entry per child file and subfolder
- No frontmatter

## Entry format

```markdown
# Folder Name

- [[subfolder/index|Subfolder Display Name]] — orientation phrase
- [[some-file]] — orientation phrase
```

- One entry per line: wikilink + em dash + short orientation phrase
- Use a short phrase that helps the reader decide whether to open the note.
- Subfolders first, then files alphabetically
- Disambiguate duplicate `index.md` names with path prefix: `[[systems/index]]` not `[[index]]`

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

Use sections when ≥2 groups are clearly distinct. Default flat list when homogeneous.

## Stale path-based wikilinks

Watch for `[[old/path/file|Display]]` in existing indexes. Replace with `[[filename|Display]]` — Obsidian resolves by filename regardless of location.

## Move files

Always use obsidian CLI, never raw filesystem `mv`:
```bash
obsidian vault="<vault>" move path="old/path.md" to="new/folder/file.md" silent
```
After each move, verify the new path exists and the old path does not under the
configured filesystem root; CLI success text alone is insufficient. Then search
the vault for the old filename to verify Obsidian updated all refs. Fix any stale
wikilinks found.
