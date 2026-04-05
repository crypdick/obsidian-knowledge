---
name: remember-conversations
description: >-
  File valuable conversation outputs as permanent vault notes. Use when a
  conversation produced a synthesis, analysis, comparison, decision rationale,
  research summary, or discovery worth preserving. Triggered by the Stop hook
  reminder, by the user saying "file this", "save this conversation",
  "remember this", or at agent discretion when a response deserves to outlive
  chat history.
version: 0.2.0
---

# Remember Conversations

Capture valuable conversation outputs as permanent notes in the vault, so
that insights compound rather than disappearing into chat history.

## When to file

File a conversation when it produced something a future agent or the user
would benefit from finding later:

- An analysis that synthesizes multiple sources or pages
- A comparison between options (mortgage terms, migration strategies, etc.)
- A decision rationale — "we chose X because Y"
- A research summary from web searches or deep dives
- A discovery — a connection or insight that wasn't obvious before
- A dead end — something that was tried, didn't work, and why

Do **not** file:
- Simple lookups or factual answers
- Edits to existing pages (already persisted)
- Back-and-forth that didn't converge on anything useful

## Note structure

Every conversation note follows this structure:

```markdown
# {Descriptive title}

## Context

{What prompted this — the question, task, or trigger. 1-2 sentences.}

## Synthesis

{The actual analysis, comparison, finding, or decision rationale. This is
the meat of the note — as long as it needs to be.}

## Key takeaways

- {Concise bullets summarizing actionable or memorable points}

## Related

- [[wikilinks to relevant vault pages]]
```

Adapt the sections to fit the content — not every note needs every section.
A short discovery might just have Context + Synthesis + Related. A long
analysis might split Synthesis into subsections. Use judgment.

## Filing location

Notes go in a `convos/` subfolder within the relevant subtree:

```
life/finance-property/taxes/
├── _sources/
├── convos/                          ← conversation notes live here
│   ├── index.md
│   └── 2026-04-05-deduction-analysis.md
├── index.md
└── ...
```

### Choosing the right subtree

Place the note in the most specific subtree that covers its topic. A note
about 2024 tax deductions goes in `life/finance-property/taxes/convos/`,
not `life/convos/`. If a conversation spans multiple domains, choose the
primary one and add wikilinks to the others in the Related section.

### Filename convention

`YYYY-MM-DD-{slug}.md` — date-prefixed, lowercase, hyphen-separated slug.

Examples:
- `2026-04-05-deduction-analysis.md`
- `2026-03-15-zfs-vs-btrfs-comparison.md`
- `2026-02-20-why-we-kept-vaults-separate.md`

## Procedure

1. **Determine the subtree** — identify where the note belongs based on topic.

2. **Create `convos/` if needed** — if the subtree doesn't have a `convos/`
   folder yet, create it with an `index.md`:
   ```markdown
   # Conversations

   - [[YYYY-MM-DD-slug]] — orientation phrase
   ```

3. **Write the note** — create the file at `{subtree}/convos/YYYY-MM-DD-{slug}.md`
   following the note structure above.

4. **Update `convos/index.md`** — add an entry for the new note.

5. **Update parent `index.md`** — if the `convos/` subfolder is new, add it
   to the parent folder's index:
   ```markdown
   - [[convos/index|Conversations]] — filed conversation outputs and analyses
   ```

6. **Use the Obsidian CLI** for file creation so Obsidian's link index stays
   in sync. Syntax:
   ```bash
   obsidian create path="{subtree}/convos/YYYY-MM-DD-slug.md" content="..." vault="<vault-name>"
   ```
   Use `\n` for newlines in the content value. Always specify the vault name
   if more than one vault is registered.
