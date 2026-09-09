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

## Orphans

Run `obsidian vault="$VAULT_NAME" orphans`. Add managed-zone orphans to their
parent index if missing. Ignore orphans outside managed zones and sync conflicts.

## Dead ends

`obsidian vault="$VAULT_NAME" deadends` is informational. Leaf notes can
legitimately have no outgoing links; do not flag them.
