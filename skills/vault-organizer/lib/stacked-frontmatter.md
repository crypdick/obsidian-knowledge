# Fix stacked frontmatter

Obsidian reads only the first YAML block at the start of a note. Properties in
a second block appear as body text and are unavailable to plugins.

## Detect

Audit emits one line per file:

```text
STACKED_FRONTMATTER	<path>
```

## Fix

For a stray duplicate `---` after the frontmatter, use the helper script.
Replace `NOTE_PATH` with the note's filesystem path:

```bash
# Dry run (reports what would change)
uv run --no-project --with pyyaml python "$SCRIPTS/fix-stacked-frontmatter.py" NOTE_PATH

# Apply the fix
uv run --no-project --with pyyaml python "$SCRIPTS/fix-stacked-frontmatter.py" --fix NOTE_PATH
```

Output codes:

- `WOULD_FIX` or `FIXED`: a stray duplicate marker can be removed automatically.
- `NEEDS_MERGE`: the second block contains keys and requires a manual merge.
  The script exits with code 1.

For `NEEDS_MERGE` cases:

1. Read the note and confirm two YAML blocks.
2. Merge the keys into one block. For timestamps, prefer the newer automatically
   injected values. For other properties, preserve user-set values.
3. Write and verify the note with one frontmatter block.

Example before:

```yaml
---
created: 2026-04-29T13:24
updated: 2026-04-29T13:27
---
---
tags:
dg-publish: false
aliases:
---

# Title
```

After:

```yaml
---
created: 2026-04-29T13:24
updated: 2026-04-29T13:27
tags:
dg-publish: false
aliases:
---

# Title
```

## Prevention for templates

If a Templater template emits frontmatter, the template file itself must not
start with frontmatter. Start it with a `<%*` script block and place the
frontmatter in the rendered body after the closing `-%>`.

If a plugin injects frontmatter into templates, exclude the template folder in
its settings. For `update-time-on-edit`, use `Templates`, not `Templates/*`:
its path-prefix matching includes nested files. Reload Obsidian after changing
this setting.
