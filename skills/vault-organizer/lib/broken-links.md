# Broken links

## Unresolved links

The recovery script keeps links from `ai_managed` zones and excludes template placeholders
and configured `stub_link_patterns` from `~/.config/obsidian-knowledge/config.yaml`.
Defaults cover prefixes such as `(PAPER)`, `(BOOK)`, and `@Person`.

Fix remaining links only when the intended existing target is unambiguous.
Record uncertain candidates or expected missing files in `needs-attention.md`.
Leave intentional concept stubs intact; remove a missing-file link only when
established vault practice supports it.

Dates, paths, extensions, and embeds suggest expected files; a bare concept
such as `[[anxiety]]` may be an intentional stub. Use context rather than link
shape alone to decide.

## Deterministic recovery

Use `obsidian-knowledge garden links --apply` for unique recoveries; omit
`--apply` to preview.
It can recover a stale prefix only when removing leading path components leaves
a unique existing suffix of at least `directory/name`. It never falls back from
a path-shaped target to an unrelated basename. Existing directories are not
note candidates. Attachments require exact filenames, including extensions;
normalized and fuzzy comparisons apply only to Markdown notes.

Hidden paths, dependency directories, sync conflicts, and symlinks are excluded
from candidates. Sources must be visible managed Markdown notes outside
`_sources/` and configured read-only paths. Apply rechecks write policy and
delegates to the verified writer; aliases, heading and block suffixes survive.

If CLI results disagree with file contents, reload Obsidian with
`obsidian command id="app:reload"` and retry.

## Orphans

Run `obsidian orphans`. Add managed-zone orphans to their
parent index if missing. Ignore orphans outside managed zones and sync conflicts.

## Dead ends

`obsidian deadends` is informational. Leaf notes can
legitimately have no outgoing links; do not flag them.
