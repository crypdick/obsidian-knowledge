# Broken links

## Unresolved links

Pipe the JSON output of `obsidian unresolved` into the helper script. It
restricts to links from `ai_managed` zones, drops template placeholders
(`{{...}}`, `<% ... %>`), and drops link targets whose name matches a
configured stub pattern:

```bash
obsidian unresolved verbose format=json | python3 filter-unresolved-links.py "$VAULT"
```

The script reads `stub_link_patterns:` from the vault's
`.claude/obsidian-knowledge.yaml` if present; otherwise it uses built-in
defaults covering the common prefix conventions (`(PAPER) X`, `(VIDEO) X`,
`(POST) X`, `(PODCAST) X`, `(BOOK) X`, `(RECIPE) X`, `(Vision) X`,
`(Pillar) X`, `@Person`).

The output is still a list of candidates needing human judgment, not a
fixable issue list. Many concept-stub names are plain words (e.g.
`Acne`, `attention head`) and can't be filtered by pattern — these
survive the filter and have to be triaged on the same lib/broken-links
rules below.

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
