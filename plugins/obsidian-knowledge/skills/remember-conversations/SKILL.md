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

# Remember conversations

Save reusable knowledge that a future session would otherwise lose.
Filing nothing is a successful outcome.

## Acceptance gate

1. Search the vault and read the best existing note on the topic.
2. State the one-sentence durable delta missing from that note.
3. File it only if it changes a future decision or prevents repeated work and
   is not cheaply recoverable from code, tracked docs, Git, issues, logs, or runtime.

An explicit request to preserve a result qualifies. Other candidates include
user preferences, decision rationale, verified procedures, non-obvious failure
modes with recovery steps, and sourced syntheses that are expensive to recreate.
Skip routine progress, test or release results, transient state, PIDs, job IDs,
temporary worktrees, handoffs, generic answers, raw output, and duplicates.

Verify claims before saving them as facts. For volatile technical or product
facts, include a source and verification date. For medical, legal, or financial
claims, include sources and uncertainty.

## Outputs

Prefer updating one canonical note. Create a second only for an explicit user
request or two independently reusable topics. Do not duplicate the same facts
across learning, conversation, and diary notes or create a suffixed copy of an
existing canonical filename.

Never write to `CLAUDE.md` unless the user explicitly requests it. Durable
knowledge and behavioral rules belong in the wiki.

### Changelog entry

Only after changing durable vault content, create or reuse one same-session file:
`Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`.
Use terse audit pointers: `YYYY-MM-DD HH:MM — <vault change> [→ [[wikilink]]]`.
Do not log code, Git, host, test, release, or deployment work alone. Include no
narrative or code blocks, and do not update a shared changelog index.

When the Stop hook supplies a capture key, reuse `*-session-<capture-key>.md`
if present; otherwise end the filename with `-session-<capture-key>.md`.
Without a key, check current-day fragments for the canonical note's wikilink
before creating another file.

## Note structure

Write only the context, evidence, reasoning, and result needed for reuse. Add
related wikilinks. Use sections that fit the content; a fixed template is not
required. Preserve exact user wording only when it carries a durable preference,
constraint, or rationale. Prefer 150-350 words; exceed 500 only for a verified
procedure that needs the detail.

Every durable note must be hermetic: explain local labels such as "category 15"
or "scenario 9" with their system and meaning. The note must be usable without
the originating conversation; links can supply further detail.

## Filing location

Read the vault's `CLAUDE.md` and top-level wiki index, then use search to find
the most specific topic subtree. Follow vault-specific naming conventions.

| Content | Location and filename |
| --- | --- |
| Reusable concept or guide | Existing topic subtree; concept name without a date prefix. Use a learning subtree only when no topic home fits. |
| Analysis, comparison, or decision rationale | Topic's `convos/YYYY-MM-DD-<slug>.md` |
| Reusable account of an incident or process | Topic's `diary/YYYY-MM-DD-<slug>.md` |
| Codebase architecture or implementation decisions | `wiki/repos/<owner>/<repo>/` |
| Deployed state, operations, or runbooks | `wiki/systems/<system>/` |

For topics spanning domains, choose one primary home and link to the others.

## Procedure

1. Apply the acceptance gate and choose a filing location. If no delta qualifies,
   stop without a note or changelog.
2. Read an existing canonical note before updating it. Integrate the result into
   its prose rather than appending a transcript.
3. Write the note first with `obsidian-knowledge write` and a quoted heredoc.
   Omit `--replace` for creation; include it for an intentional full-file update.

   ```bash
   obsidian-knowledge write "wiki/topic/concept.md" <<'ENDNOTE'
   # Descriptive title

   Reusable knowledge with literal `identifiers` and [[wikilinks]].
   ENDNOTE
   ```

4. Continue only after `Wrote and verified:`. Update the folder's `index.md`
   using the same read and replace workflow. For a new folder, also link its
   index from the parent. Never link a note before its write verifies.
5. Create or reuse the conditional changelog entry.

Use the `obsidian-knowledge` skill for access errors and note-editing conventions.
