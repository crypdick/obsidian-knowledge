# Fix stacked frontmatter

Obsidian reads only the first YAML block at the start of a note. Properties in
a second block appear as body text and are unavailable to plugins.

The audit reports possible `STACKED_FRONTMATTER`. Inspect a vault-relative
Markdown path:

```bash
obsidian-knowledge garden frontmatter NOTE_PATH
```

`NEEDS_MERGE` (exit 1) requires manual review. The command never deletes markers,
even with compatibility flag `--apply`: a second `---` can be a valid thematic
break, and syntax alone cannot establish intent. Confirm an actual second YAML
block before merging with `obsidian-knowledge write`, preserving user-set
properties. For conflicting timestamps, prefer newer automatically injected
values only when their provenance is established.

## Prevention for templates

If a Templater template emits frontmatter, the template file itself must not
start with frontmatter. Start it with a `<%*` script block and place the
frontmatter in the rendered body after the closing `-%>`.

If a plugin injects frontmatter into templates, exclude the template folder in
its settings. For `update-time-on-edit`, use `Templates`, not `Templates/*`:
its path-prefix matching includes nested files. Reload Obsidian after changing
this setting.
