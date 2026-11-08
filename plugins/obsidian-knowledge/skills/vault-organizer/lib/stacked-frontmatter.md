# Fix stacked frontmatter

Obsidian reads only the first YAML block at the start of a note. Properties in
a second block appear as body text and are unavailable to plugins.

The audit reports `STACKED_FRONTMATTER`. Preview or remove a stray duplicate
marker with a vault-relative Markdown path:

```bash
obsidian-knowledge garden frontmatter --apply NOTE_PATH
```

Omit `--apply` to preview. `WOULD_FIX` and `FIXED` identify automatic repairs.
`NEEDS_MERGE` (exit 1) means the second block contains keys: merge into one YAML
block with `obsidian-knowledge write`, preserving user-set properties. For
conflicting timestamps, prefer newer automatically injected values.

## Prevention for templates

If a Templater template emits frontmatter, the template file itself must not
start with frontmatter. Start it with a `<%*` script block and place the
frontmatter in the rendered body after the closing `-%>`.

If a plugin injects frontmatter into templates, exclude the template folder in
its settings. For `update-time-on-edit`, use `Templates`, not `Templates/*`:
its path-prefix matching includes nested files. Reload Obsidian after changing
this setting.
