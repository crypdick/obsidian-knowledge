# Fix: stacked frontmatter

Two consecutive `---` YAML blocks at top of file. Obsidian parses only first as frontmatter; second renders as `<hr>` + plain text + `<hr>`. Properties in second block silently invisible to dataview, bases, dg-publish, etc.

## Detect

Audit emits one line per file:

```
STACKED_FRONTMATTER	<path>
```

## Common cause

Plugin (`update-time-on-edit`, `Linter`, etc.) injects `created`/`updated`/`date` keys at top of file already containing frontmatter. Templater templates with leading frontmatter + `<%- output %>` JS-string-build also produce stacked output.

## Fix

For each flagged file:

1. Read file. Confirm two `---` blocks.
2. Merge keys from both blocks into single frontmatter. Newer/auto-injected keys (created/updated) win for timestamps; user-set keys (tags, dg-publish, aliases) win for everything else.
3. Write back single frontmatter block.

Example before:

```
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

```
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

Templater templates emitting their own frontmatter must not have leading frontmatter on the template file itself. Start template with `<%*` script block. Move template's frontmatter into the rendered body after the `-%>` close.

If a plugin keeps injecting frontmatter back into templates, add the templates folder (e.g. `Templates`) to that plugin's ignore list. Note `update-time-on-edit` matches via literal `path.startsWith()` — `Templates/*` is a no-op, use `Templates` (covers all nested files). Reload Obsidian after changing the setting so in-memory state refreshes.
