# Rename ambiguous files

Rename when a descriptive name improves discovery: device-generated names,
hashes, numeric-only names, generic labels such as `scan`, or duplicate extensions.
Leave descriptive names, dotfolders, and `.trash/` alone.

Read or view the file and use context or metadata to identify it. Follow local
naming conventions. Prefer dates from content, then EXIF, filename, or folder;
omit dates without reliable evidence. For low-confidence cases, record a
proposed name and reason in `needs-attention.md` rather than guessing.

Use Obsidian so internal links update:

```bash
obsidian rename path="old/name.ext" name="new-name.ext"
```

Renaming `_sources/` requires explicit human approval. In Codex/Claude, use
i-insist approval (`I insist`, or an explicitly authorized
`HUMAN_PERMISSION_GRANTED=1` shell call). Do not modify original content there;
record content problems in `needs-attention.md`. Repair stale links encountered
within scope.
