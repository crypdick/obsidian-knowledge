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

Capture valuable conversation outputs as permanent notes in the vault
and log what happened, so that insights compound rather than disappearing
into chat history.

## Outputs

Each session can produce up to two outputs. Decide which combination
fits based on what happened.

### Changelog entry

Always append to `Utility/obsidian-knowledge/changelog.md` if the
session produced anything substantive — edits, decisions, discoveries,
dead ends. Keep entries terse (one line per action) and link out to
session notes for detail rather than documenting inline. Follow the
format defined by the vault-organizer skill. Skip if nothing meaningful
happened or you already logged.

### Session notes

Create a session note when the conversation produced something a future
agent or the user would benefit from finding later. There are two types,
filed in **separate folders**:

- **Convo note** — analytical synthesis: comparisons between options,
  decision rationales, research summaries, discoveries, or connections
  that weren't obvious before. Lives in a `convos/` subfolder of the
  relevant area.
- **Diary note** — narrative account: what happened, what was tried,
  what worked or didn't, and why. Use for processes, incidents, debugging
  sessions, or any sequence of events worth retelling. Lives in a
  `diary/` subfolder of the relevant area.

A session can produce both types if it involved a notable process AND
yielded a separable analytical insight.

Do **not** create session notes for:
- Simple lookups or factual answers
- Edits to existing pages (already persisted)
- Back-and-forth that didn't converge on anything useful

## Note structure

Every session note follows this structure:

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

Adapt sections to fit — not every note needs every section.

## Filing location

Convo notes go in `convos/` and diary notes go in `diary/` subfolders
within the relevant subtree:

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

Place the note in the most specific subtree that covers its topic. If a
conversation spans multiple domains, choose the primary one and add
wikilinks to the others in the Related section.

### Filename convention

Follow the vault's CLAUDE.md for naming style. If no convention is
defined, default to `YYYY-MM-DD-{slug}.md`. The folder location
(`convos/` vs `diary/`) distinguishes the note type — no type suffix
is required, though adding `-convo` or `-diary` to a filename is
permitted for self-documentation.

## Procedure

1. **Determine the subtree** — identify where session notes belong
   based on topic.

2. **Determine the type** — convo or diary — and target the
   corresponding subfolder (`convos/` or `diary/`).

3. **Create the subfolder if needed** — if the subtree doesn't have
   the target folder yet, create it with an `index.md`:
   ```markdown
   # Conversations

   - [[YYYY-MM-DD-slug]] — orientation phrase
   ```
   (Use `# Diary` for diary folders.)

4. **Write the note** — create the file using the Obsidian CLI so
   Obsidian's link index stays in sync:
   ```bash
   obsidian create path="{subtree}/convos/YYYY-MM-DD-slug.md" content="..." vault="<vault-name>"
   ```
   Use `\n` for newlines in the content value. Always specify the vault
   name if more than one vault is registered.

5. **Update the subfolder's `index.md`** — add an entry for the new
   note.

6. **Update parent `index.md`** — if the `convos/` or `diary/`
   subfolder is new, add it to the parent folder's index:
   ```markdown
   - [[convos/index|Conversations]] — analytical synthesis notes
   - [[diary/index|Diary]] — narrative session accounts
   ```

7. **Update the changelog** — append a dated entry to
   `Utility/obsidian-knowledge/changelog.md` summarizing actions taken.
   Link to session notes created above rather than documenting detail
   inline.
