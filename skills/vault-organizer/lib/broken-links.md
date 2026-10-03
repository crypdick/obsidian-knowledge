# Broken links

## Unresolved links

Use the vault and script paths set in the organizer skill:

```bash
obsidian vault="$VAULT_NAME" unresolved verbose format=json | uv run --no-project --with pyyaml python "$SCRIPTS/filter-unresolved-links.py" "$VAULT"
```

The filter keeps links from `ai_managed` zones and excludes template placeholders
and configured `stub_link_patterns` from `.claude/obsidian-knowledge.yaml`.
Defaults cover prefixes such as `(PAPER)`, `(BOOK)`, and `@Person`.

Inspect every remaining candidate, in batches if needed. Plain-word links can
be intentional concept stubs or broken references. Apply these rules:

1. **Exact match:** Find the existing file and fix the link.
2. **Similar match:** Fix the link only when the candidate is unambiguous.
3. **Ambiguous match:** Add the issue and candidate to `needs-attention.md`.
4. **Missing file:** For a reference to an expected file, record the missing
   target. Remove the link only when an established vault precedent supports it.
5. **Intentional concept stub:** Leave it for future expansion.

Dates, paths, extensions, and missing embeds usually indicate expected files.
A bare concept such as `[[anxiety]]` might be an intentional stub. When uncertain,
add the issue to the worklist rather than silently skipping it.

## Deterministic recovery and verification

`recover-unresolved-links.py` defaults to reporting. Review before `--apply`.
It can recover a stale prefix only when removing leading path components leaves
a unique existing suffix of at least `directory/name`. It never falls back from
a path-shaped target to an unrelated basename. Existing directories are not
note candidates. Attachments require exact filenames, including extensions;
normalized and fuzzy comparisons apply only to Markdown notes.

Hidden paths, dependency directories, sync conflicts, and symlinks are excluded
from candidates. Sources must be visible managed Markdown notes outside
`_sources/` and configured read-only paths. Apply rechecks write policy and
delegates to the verified writer; aliases, heading and block suffixes survive.

Before repair, retain exact source bytes as a baseline. After repair, compare
the diff and confirm only intended link targets changed. Primary prose, aliases,
headings, block references, and frontmatter must remain intact. Then obtain
fresh `obsidian vault="$VAULT_NAME" unresolved verbose format=json` results and
confirm each repaired target disappeared from the relevant source's findings.
If file contents and CLI results disagree, reload Obsidian with
`obsidian vault="$VAULT_NAME" command id="app:reload"` and retry after it loads.
Review fresh orphan results too; unrelated totals can change during sync.

## Orphans

Run `obsidian vault="$VAULT_NAME" orphans`. Add managed-zone orphans to their
parent index if missing. Ignore orphans outside managed zones and sync conflicts.

## Dead ends

`obsidian vault="$VAULT_NAME" deadends` is informational. Leaf notes can
legitimately have no outgoing links; do not flag them.
