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
survive the filter and have to be triaged on the rules below.

**Do not bulk-skip the surviving list on the assumption that everything past the script filter is also a stub.** The script removes known stub *patterns* (parenthesized prefixes, `@Person`, etc.); plain-word survivors include real misnamed links, dead refs to renamed/moved files, ambiguous candidates worth surfacing, and missing embeds (`![[...png]]`) — exactly the things this pass is here to catch. Walk every entry. Pre-existing entries that have survived prior passes are not exempt; they are the backlog this skill exists to drain.

If the list is large (hundreds of entries), that is the expected state of an unmaintained vault, not a signal to compress the work. Process in chunks if needed, but cover the full list before declaring Step 4 done.

Focus only on links **from managed-zone files** referencing filenames expected to exist: structural files, files referenced in prose as if existing, one-off links not matching stub patterns.

For each entry:
1. **Exact name match** — search vault for same-name file. Found → fix link.
2. **Similar match** — clear high-confidence candidate → fix link.
3. **Ambiguous candidate** — add to needs-attention.md with candidate noted.
4. **No match, but referenced as a real file** (e.g. `[[2025-01-12]]` clearly a journal-day reference, missing embed `![[foo.png]]`) — add to needs-attention.md, no candidate, OR remove the broken reference if precedent exists (see changelog for prior `[[xyz.zip]]`-style strips).
5. **No match, and looks like a concept stub the user intentionally left for future expansion** — leave it. These accumulate naturally and are not bugs.

Distinguishing (4) from (5): `[[Adderall]]`, `[[anxiety]]`, `[[ARR]]` look like concept stubs (single concept, no path/extension/date). `[[2025-01-12]]`, `[[20250601-foo.png]]`, `[[some/path/file]]` look like real-file references (date format, file extension, slash path). When unsure, prefer needs-attention over silent skip.

## Orphans

Run `obsidian orphans`.

Orphans in `ai_managed` zones → add to parent folder index if missing. Ignore orphans outside managed zones.

## Dead ends

Run `obsidian deadends`. Informational only — many leaf files legitimately have none. Don't flag.
