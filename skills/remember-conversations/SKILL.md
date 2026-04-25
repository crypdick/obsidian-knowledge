---
name: remember-conversations
description: >-
  File valuable conversation outputs as permanent vault notes and update
  the changelog. Use when a conversation produced a synthesis, analysis,
  comparison, decision rationale, research summary, narrative account,
  or discovery worth preserving. Triggered by the Stop hook reminder,
  by the user saying "file this", "save this conversation", "remember
  this", or at agent discretion when a response deserves to outlive
  chat history.
version: 0.7.0
---

# Remember Conversations

Capture valuable conversation output as permanent vault notes. Log what happened so insights compound, not vanish into chat.

## Outputs

Each session yield up to two outputs. Pick combo by what happened.

### Changelog entry

Always append to `Utility/obsidian-knowledge/changelog.md` if session produced substance — edits, decisions, discoveries, dead ends. One line per action. Link to session notes for detail, not inline doc. Follow format from vault-organizer skill. Skip if nothing meaningful or already logged.

### Session notes

Create session note when convo produced something future agent or user benefit finding later. Two types, **separate folders**:

- **Convo note** — analytical synthesis: option comparisons, decision rationales, research summaries, discoveries, non-obvious connections. Lives in `convos/` subfolder of relevant area.
- **Diary note** — narrative: what happened, what tried, what worked or not, why. Use for processes, incidents, debug sessions, event sequences worth retell. Lives in `diary/` subfolder of relevant area.

Session can produce both if notable process AND separable analytical insight.

Do **not** create session notes for:
- Simple lookups or factual answers
- Edits to existing pages (already persisted)
- Back-and-forth that didn't converge on anything useful

## Note structure

Every session note follow this structure:

```markdown
# {Descriptive title}

## Context

{What prompted this — the question, task, or trigger. 1-2 sentences.}

## {Body}

{The narrative or analysis. Section heading and structure should fit
the content — "What happened" for diaries, "Analysis" or "Comparison"
for convos, etc. As long as it needs to be.}

## Key takeaways

- {Concise bullets summarizing actionable or memorable points}

## Related

- [[wikilinks to relevant vault pages]]
```

Adapt sections to fit — not every note need every section.

## Filing location

Convo notes go in `convos/`, diary notes go in `diary/` subfolders within relevant subtree:

```
area/topic/
├── _sources/
├── convos/
│   ├── index.md
│   └── 2026-04-05-deduction-analysis.md
├── diary/
│   ├── index.md
│   └── 2026-04-06-tax-filing-process.md
├── index.md
└── ...
```

### Choosing the right subtree

Place note in most specific subtree covering topic. If convo span multiple domains, pick primary, add wikilinks to others in Related.

### Filename convention

Follow vault's CLAUDE.md for naming. No convention defined → default `YYYY-MM-DD-{slug}.md`. Folder location (`convos/` vs `diary/`) distinguish type — no type suffix required, but `-convo` or `-diary` suffix permitted for self-doc.

## Procedure

1. **Determine the subtree** — identify where session notes belong by topic.

2. **Determine the type** — convo or diary — target matching subfolder (`convos/` or `diary/`).

3. **Create the subfolder if needed** — if subtree lack target folder, create with `index.md`:
   ```markdown
   # Conversations

   - [[YYYY-MM-DD-slug]] — orientation phrase
   ```
   (Use `# Diary` for diary folders.)

4. **Write the note** — create file via Obsidian CLI so Obsidian link index stay in sync:
   ```bash
   obsidian create path="{subtree}/convos/YYYY-MM-DD-slug.md" content="..." vault="<vault-name>"
   ```
   Use `\n` for newlines in content value. Always specify vault name if more than one vault registered.

5. **Update the subfolder's `index.md`** — add entry for new note.

6. **Update parent `index.md`** — if `convos/` or `diary/` subfolder new, add to parent folder index:
   ```markdown
   - [[convos/index|Conversations]] — analytical synthesis notes
   - [[diary/index|Diary]] — narrative session accounts
   ```

7. **Update the changelog** — append dated entry to `Utility/obsidian-knowledge/changelog.md` summarizing actions. Link to session notes above, not inline detail.