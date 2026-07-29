---
name: remember-conversations
description: >-
  Selectively file durable, novel conversation outcomes as canonical vault
  notes. Use when a result will materially change future action or prevent
  repeated work and is not already recoverable elsewhere, or when the user
  explicitly asks to preserve it. Triggered by the Stop-hook decision gate or
  requests such as "file this", "save this conversation", and "remember this".
version: 0.11.0
---

# Remember Conversations

Capture durable, novel conversation output as canonical vault knowledge.
Skipping is a successful result when no qualifying delta exists.

## Acceptance gate

Before writing anything:

1. Search the vault for the topic and inspect the best existing canonical note.
2. State the one-sentence durable delta that note lacks.
3. File only if the delta will materially change a future decision or prevent
   repeated work and is not cheaply recoverable from code, tracked docs, git,
   an issue, operational logs, or current runtime state.

Qualifying examples:

- An explicit user request to preserve the result.
- A durable user preference, constraint, or decision rationale.
- A reusable procedure verified successfully end to end.
- An evidence-backed, non-obvious failure mode with its cause and recovery.
- A sourced synthesis whose conclusion is expensive to reconstruct.

Do not file:

- Routine edits, commits, releases, test results, or deployment progress.
- PIDs, job IDs, temporary branches/worktrees, health snapshots, or running status.
- Quick factual lookups, generic educational answers, acknowledgements, or commands.
- Per-iteration monitoring handoffs, raw/generated output, or facts already filed.
- A transcript that did not converge on a reusable result.

Volatile technical/product facts need a source and verification date. Medical,
legal, and financial claims need sources and explicit uncertainty.

## Outputs

Normally create or materially update at most one durable wiki note. A second
note requires an explicit user request or two independently reusable topics.
Never create a diary, convo, and learning page containing the same facts.

### Changelog entry

A changelog fragment is conditional audit metadata, not a standalone capture
target. Only after this skill materially creates or updates durable vault
content, create or reuse one same-session file at
`Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`. Record only
the vault mutation as a terse pointer in the form
`YYYY-MM-DD HH:MM — <vault change> [→ [[wikilink]]]`. Do not log code, git,
host, test, release, or deployment activity by itself. No narrative, code
blocks, duplicate same-session fragments, or shared changelog index.
When the Stop hook supplies a capture key, search for
`*-session-<capture-key>.md`, reuse it if present, and otherwise end the new
filename with `-session-<capture-key>.md`. Without a key, search current-day
fragments for the canonical note wikilink before creating another file.

### Session notes

When the acceptance gate passes, choose one canonical note type:

- **Learning page** — a reusable concept synthesis that adds a durable conclusion,
  derivation, or sourced explanation to the canonical topic page. Quick or generic
  Q&A does not qualify merely because it is educational.
- **Convo note** — analytical synthesis: option comparisons, decision rationales,
  research summaries, discoveries, or non-obvious connections. Quote user wording
  only when it carries a durable constraint, preference, or rationale.
- **Diary note** — narrative: what happened, what tried, what worked or not, why. Use for processes, incidents, debug sessions, event sequences worth retell. Lives in `diary/` subfolder of relevant area.

Prefer extending an existing note over creating a new one. Do not create a
suffixed duplicate when the canonical filename already exists.

**Never write to CLAUDE.md.** That file is user-owned and edited only by explicit
user request. Agent-generated durable knowledge that passes the gate goes in
`wiki/`. Behavioral rules go there too; add a CLAUDE.md pointer only when the
user explicitly asks.

## Note structure

Every session note follow this structure:

```markdown
# {Descriptive title}

## Context

{What prompted this — question, task, or trigger. 1-2 sentences.}

## {Body}

{Narrative or analysis. Section heading + structure fit content —
"What happened" for diaries, "Analysis" or "Comparison" for convos,
etc. Keep only the evidence, reasoning, and result needed for reuse.}

{When the user's exact wording carries a durable constraint, preference, or
decision rationale, preserve only that load-bearing wording. Optional pattern:

> **Q:** "{exact user question}"
>
> **A:** {durable synthesis and necessary reasoning}

Omit this block for acknowledgements, commands, or ordinary questions.}

## Key takeaways

- {Concise bullets summarizing actionable or memorable points}

## Related

- [[wikilinks to relevant vault pages]]
```

Adapt sections to fit; not every note needs every section. Prefer 150-350 words
and rarely exceed 500 unless a verified runbook genuinely requires more.

Every durable note must be hermetic: explain any local label or scoped reference
(for example, "category 15" or "scenario 9") with the relevant system or taxonomy
and meaning. Wikilinks may add detail, but cannot replace the context needed to
understand and reuse the note without its originating conversation.

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

Place note in most specific subtree covering topic. Codebase architecture and
implementation decisions belong under `wiki/repos/<owner>/<repo>/`; deployed
state, operational procedures, and runbooks belong under `wiki/systems/<system>/`.
For learning pages, consult the top-level `index.md` and vault search before
defaulting to a learning subtree. Spans multiple domains: pick one primary home
and add wikilinks to the others.

### Filename convention

- **Learning pages**: concept name, no date prefix. Slugify per vault's conventions.
- **Convo/diary**: `YYYY-MM-DD-{slug}.md`. Folder location distinguishes type; `-convo` or `-diary` suffix optional.

Follow vault's CLAUDE.md for any vault-specific overrides.

## Procedure

All note, index, and changelog content writes use `obsidian-knowledge write`
with a quoted heredoc. The command resolves the configured filesystem root,
confines the vault-relative path, refuses empty content and accidental
overwrites, writes atomically, fsyncs, and verifies the final bytes. Treat only
`Wrote and verified:` as success. For a new file, omit `--replace`; for an
intentional full-file update, read it first and pass `--replace`.

Write the durable note first, then its index, then the conditional changelog.
Never create an index link before the note write verifies.

### For learning pages

1. **Identify concept** — what durable delta did this Q&A add? Pick the single
   highest-value canonical topic. A second page must satisfy the output cap.

2. **Find the right home** — route by topic, not by default location. Run all three checks before deciding:
   1. **Read wiki's top-level `index.md`** — scan for domain that fits concept.
   2. **Vault search** — run `obsidian-knowledge search "<concept>"` and inspect top hit paths to see where neighboring notes live. Use exact-string search only when looking for a literal name, phrase, or token.
   3. **Fallback** — no existing subtree clearly fits → file under dedicated learning subtree (e.g. `wiki/learning/<subtopic>/`) per vault's convention. Create subtopic folder (with `index.md`) if needed.

3. **Search for existing page** — within chosen subtree, look for page already covering concept. Check by concept name (`find <subtree> -iname '*concept*'`) + via search from step 2. Found → step 5 (append). Not found → step 4 (create).

4. **Create new page** — render the complete Markdown and write it directly to
   the configured vault. The path is relative to the vault root:
   ```bash
   obsidian-knowledge write "wiki/<subtree>/<concept>.md" <<'ENDNOTE'
   # Descriptive title

   Complete durable note with literal `identifiers` and [[wikilinks]].
   ENDNOTE
   ```
   Initial content is a one-paragraph definition plus the durable delta
   organized as wiki prose, not transcript. Continue only after the command
   reports `Wrote and verified:`.

5. **Update an existing page** — read it with `obsidian-knowledge read`, integrate
   the durable delta into the complete wiki narrative, then write the full result
   with `obsidian-knowledge write "<path>" --replace`. Do not paste a transcript.
   Add a heading only when the concept genuinely needs one. Preserve a verbatim
   user question only when its framing is load-bearing.

6. **Index and cross-link** — only after the note verifies, update the subtree's
   `index.md` with the same read/full-replace workflow. A new subtree also needs
   a parent-index link. Add `[[wikilinks]]` to related concept pages encountered.

### For convo / diary notes

1. **Determine subtree** — identify where session notes belong by topic.

2. **Determine type** — convo or diary — target matching subfolder (`convos/` or `diary/`).

3. **Create subfolder if needed** — subtree lacks target folder → create with `index.md`:
   ```markdown
   # Conversations

   - [[YYYY-MM-DD-slug]] — orientation phrase
   ```
   (Use `# Diary` for diary folders.)

4. **Write note** — render and write the complete note directly:
   ```bash
   obsidian-knowledge write "wiki/{subtree}/convos/YYYY-MM-DD-slug.md" <<'ENDNOTE'
   # Descriptive title

   Complete hermetic session note.
   ENDNOTE
   ```
   Use `diary/` instead of `convos/` for diary notes. Continue only after
   `Wrote and verified:`.

5. **Update subfolder's `index.md`** — note first, then read and fully replace
   the index with an entry for the verified note.

6. **Update parent `index.md`** — `convos/` or `diary/` subfolder new → add to parent folder index:
   ```markdown
   - [[convos/index|Conversations]] — analytical synthesis notes
   - [[diary/index|Diary]] — narrative session accounts
   ```

### After a durable vault mutation

Create or reuse one same-session changelog fragment as described under
"Changelog entry." If the acceptance gate failed or no durable vault content
changed, create no note and no changelog fragment.
