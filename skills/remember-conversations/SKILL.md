---
name: remember-conversations
description: >-
  File valuable conversation outputs as permanent vault notes and update
  the changelog. Use when a conversation produced a synthesis, analysis,
  comparison, decision rationale, research summary, narrative account,
  educational Q&A, or discovery worth preserving. Triggered by the Stop
  hook reminder, by the user saying "file this", "save this conversation",
  "remember this", or at agent discretion when a response deserves to
  outlive chat history.
version: 0.9.3
---

# Remember Conversations

Capture valuable conversation output as permanent vault notes. Log so insights compound, not vanish into chat.

## Outputs

Each session up to two outputs. Pick combo by what happened.

### Changelog entry

Append to `Utility/obsidian-knowledge/changelog.md` if session produced substance — edits, decisions, discoveries, dead ends. One line per action. Link to session notes for detail, not inline doc. Follow format from vault-organizer skill. Skip if nothing meaningful or already logged.

### Session notes

Create session note when convo produced something future agent or user benefit finding later. Three types, **separate locations**:

- **Learning page** — wiki-style topic note. Built by accretion: each Q&A on a topic enriches same topic page. Use for educational Q&A — concept explanations, technical deep-dives, "explain X" exchanges, things user learned. Synthesize answer into wiki prose; preserve key user questions verbatim as `> **Q:** ...` blockquotes when framing load-bearing. **Default output for any Q&A with meaningful answer** — even quick concept lookup, accrete it. Filing topic-driven: page goes in existing wiki subtree covering topic. Dedicated learning subtree (if vault has one, e.g. `wiki/learning/`) is fallback when no better home. See "Filing location" below for search procedure.
- **Convo note** — analytical synthesis: option comparisons, decision rationales, research summaries, discoveries, non-obvious connections. **Always preserve user's questions verbatim alongside answers** — question is half the value (frames problem, surfaces what user actually wanted to know). Lives in `convos/` subfolder of relevant area.
- **Diary note** — narrative: what happened, what tried, what worked or not, why. Use for processes, incidents, debug sessions, event sequences worth retell. Lives in `diary/` subfolder of relevant area.

Single session can produce multiple types (e.g., debug session that also taught a concept → diary + learning page).

Do **not** create session notes for:
- Pure factual lookups, no conceptual content ("what time is it", "what's path to X")
- Edits to existing pages (already persisted)
- Back-and-forth that didn't converge on anything useful

In doubt for educational Q&A: file learning page. Cost of extra short page low; cost of losing synthesis high.

**Never write to CLAUDE.md.** That file user-owned, edited only by explicit user request. Agent-generated knowledge → `wiki/`. Behavioral rules → `wiki/` too, pointer in CLAUDE.md only if user explicitly says "add this to CLAUDE.md". In doubt, wiki note wins.

## Note structure

Every session note follow this structure:

```markdown
# {Descriptive title}

## Context

{What prompted this — question, task, or trigger. 1-2 sentences.}

## {Body}

{Narrative or analysis. Section heading + structure fit content —
"What happened" for diaries, "Analysis" or "Comparison" for convos,
etc. As long as it needs to be.}

{Convo notes especially: capture user's actual questions verbatim
(quoted) followed by substantive answer. Q&A format preserves framing
user brought, often load-bearing — paraphrasing destroys nuance.
Pattern:

> **Q:** "{exact user question}"
>
> **A:** {full answer with reasoning, not just conclusion}

Use whenever conversation driven by user asking things.}

## Key takeaways

- {Concise bullets summarizing actionable or memorable points}

## Related

- [[wikilinks to relevant vault pages]]
```

Adapt sections to fit — not every note needs every section.

## Filing location

Three filing patterns:

### Learning pages (topic-driven, anywhere in wiki)

Topical wiki pages, one per concept. Knowledge accretes — return visits enrich same page rather than spawn new files.

**Filing decision: route by topic, not by type.** If vault already has subtree covering concept's domain, page goes there. Fall back to dedicated learning subtree only when no suitable home exists. User's `CLAUDE.md` + wiki's top-level `index.md` declare layout; defer to them.

Filename: human-readable concept name, no date prefix. Date prefix implies chronology; learning pages concept-keyed.

Example layout (abstract — concrete paths come from vault):

```
wiki/
├── index.md                       # always start here
├── <topic-area>/
│   ├── index.md
│   └── <concept>.md               # learning page accretes here
├── learning/                      # fallback subtree if vault uses one
│   ├── index.md
│   └── <subtopic>/<concept>.md
└── ...
```

### Convo + diary notes

Convo notes in `convos/`, diary notes in `diary/` subfolders within relevant area subtree:

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

Place note in most specific subtree covering topic. For learning pages, see procedure below — consult wiki's top-level `index.md` + run vault search before defaulting to learning subtree. Spans multiple domains: pick primary, add wikilinks to others in Related.

### Filename convention

- **Learning pages**: concept name, no date prefix. Slugify per vault's conventions.
- **Convo/diary**: `YYYY-MM-DD-{slug}.md`. Folder location distinguishes type; `-convo` or `-diary` suffix optional.

Follow vault's CLAUDE.md for any vault-specific overrides.

## Procedure

### For learning pages

1. **Identify concept** — what did this Q&A teach? One concept per page. Multi-concept session → file separately under each.

2. **Find the right home** — route by topic, not by default location. Run all three checks before deciding:
   1. **Read wiki's top-level `index.md`** — scan for domain that fits concept.
   2. **Vault search** — if semantic/vector search tool available (e.g. Obsidian-vault MCP server's search), query concept + inspect top hits' paths to see where neighboring notes live. Fall back to keyword/grep search if no vector search available.
   3. **Fallback** — no existing subtree clearly fits → file under dedicated learning subtree (e.g. `wiki/learning/<subtopic>/`) per vault's convention. Create subtopic folder (with `index.md`) if needed.

3. **Search for existing page** — within chosen subtree, look for page already covering concept. Check by concept name (`find <subtree> -iname '*concept*'`) + via search from step 2. Found → step 5 (append). Not found → step 4 (create).

4. **Create new page** via Obsidian CLI:
   ```bash
   obsidian create path="<subtree>/<concept>.md" content="..." vault="<vault-name>"
   ```
   Initial content: one-paragraph definition + Q&A material organized as wiki prose, not transcript. Add page to subtree's `index.md`. New subtree → also link from parent `index.md`.

5. **Append to existing page** — read current content. Integrate new Q&A into wiki narrative — don't paste transcript. New heading section if question covered new ground; extend existing section if refined existing material. Preserve verbatim user question as `> **Q:** "..."` blockquote when framing matters (most cases).

6. **Cross-link** — add `[[wikilinks]]` to related concept pages encountered. Search results from step 2 good candidates.

### For convo / diary notes

1. **Determine subtree** — identify where session notes belong by topic.

2. **Determine type** — convo or diary — target matching subfolder (`convos/` or `diary/`).

3. **Create subfolder if needed** — subtree lacks target folder → create with `index.md`:
   ```markdown
   # Conversations

   - [[YYYY-MM-DD-slug]] — orientation phrase
   ```
   (Use `# Diary` for diary folders.)

4. **Write note** — create file via Obsidian CLI so Obsidian link index stays in sync:
   ```bash
   obsidian create path="{subtree}/convos/YYYY-MM-DD-slug.md" content="..." vault="<vault-name>"
   ```
   Use `\n` for newlines in content value. Always specify vault name if more than one vault registered.

5. **Update subfolder's `index.md`** — add entry for new note.

6. **Update parent `index.md`** — `convos/` or `diary/` subfolder new → add to parent folder index:
   ```markdown
   - [[convos/index|Conversations]] — analytical synthesis notes
   - [[diary/index|Diary]] — narrative session accounts
   ```

### Always

**Update changelog** — append dated entry to `Utility/obsidian-knowledge/changelog.md` summarizing actions. Link to session notes (or learning pages enriched), not inline detail.
