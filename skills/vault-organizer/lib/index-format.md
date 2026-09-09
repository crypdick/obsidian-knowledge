# Index format

## Create a missing index

Create `<folder>/index.md`:

- Use the folder's display name as the heading.
- Add one entry per child file and subfolder.
- Omit frontmatter.

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

## Stale path-based wikilinks

Replace stale links such as `[[old/path/file|Display]]` with
`[[filename|Display]]`. Obsidian resolves these links by filename regardless
of location.

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
