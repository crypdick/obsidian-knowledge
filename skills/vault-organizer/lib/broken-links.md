# Broken links

## Unresolved links

Run `obsidian unresolved verbose format=json`.

**Filter before acting** — output almost always noisy, most entries intentional stubs. Blindly acting = busy work.

Narrow the list:
- Ignore links from files outside `ai_managed` zones.
- Recurring pattern across many unrelated files = stub convention, not mass breakage. Skip.
- Template placeholders (`{{...}}`, `<% ... %>`) — never actionable, skip.

Focus only on links **from managed-zone files** referencing filenames expected to exist: structural files, files referenced in prose as if existing, one-off links not matching stub patterns.

For each worth investigating:
1. **Exact name match** — search vault for same-name file. Found → fix link.
2. **Similar match** — clear high-confidence candidate → fix link.
3. **Ambiguous candidate** — add to needs-attention.md with candidate noted.
4. **No match** — add to needs-attention.md, no candidate.

## Orphans

Run `obsidian orphans`.

Orphans in `ai_managed` zones → add to parent folder index if missing. Ignore orphans outside managed zones.

## Dead ends

Run `obsidian deadends`. Informational only — many leaf files legitimately have none. Don't flag.
