---
name: remember-conversations
description: >-
  Selectively file durable, novel conversation outcomes as canonical vault
  notes. Use when a result will materially change future action or prevent
  repeated work and is not already recoverable elsewhere, or when the user
  explicitly asks to preserve it. Triggered by the Stop-hook decision gate or
  requests such as "file this", "save this conversation", and "remember this".
version: 0.11.1
---

# Remember conversations

The memory system replaces `MEMORY.md` and serves several goals:

1) capture reusable knowledge or rules that benefits future AI agents trying to complete tasks.
   If you spend effort figuring out how something works, write or update a guide.
2) storing research findings for topics the user is exploring.
3) tracking historical changes in case we need to do archeology

## Guides benefiting future agents

Do:
- ensure that guides reflect current state and is self-consistent
- integrate edits into note's natural prose rather than appending a transcript
- clean up notes that are messy or are not complaint with these guidelines
- capture reasoning for major decisions, user preferences and guidance, important contraints.
- add related wikilinks

Don't:
- litter guides with historical trivia. Use changelog for tracking important historical changes.
- over-generalize user preferences and constraints -- ask for clarification if unsure.
- document knowledge already captured in repos (always use pointers rather than duplicating content)
  or cheaply recoverable from the environment.
- overexplain concepts or document unnecessary details
- over-capture. Don't document transient state (PIDs, job IDs), test results, etc.

## Changelog entry

Changelogs are an insurance policy to help agents that need to investigate inconsistent state
or perplexing issues. For example, if we migrate files from one drive to another, but that accidentally
breaks something and the future agent is trying to investigate why the thing is broken.

It is not meant to exhaustively record every single action we take.

Changelogs keep operational guides focused on the current state and facts without littering them
with historical trivia that are unnecessary for agents trying to complete a task.

Create or reuse one same-session file:
`obsidian-knowledge write <vault_root>/Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`.
When the Stop hook supplies a capture key, reuse `*-session-<capture-key>.md`

Use terse audit pointers: `YYYY-MM-DD HH:MM — <vault change> [→ [[wikilink]]]`.
Entries shouldn't be long narratives
or code blocks; rather, self-contained bread crumbs that give future agents the context they
need to understand potentially relevant major breaking changes that happened in the past

## User research

When a user is researching a topic in-depth, suggest capturing the conversation as a report with citations.
Ensure that the report captures the answers to all the user's questions.

## Rules

- Verify claims before saving them as facts. Cite sources and state your uncertainty.
- For volatile technical or product facts, include a verification date.
- Prefer linking to existing notes instead of duplicating content. Split into more notes
if it makes sense to but don't over-fragment content.
- Don't create notes if they aren't necessary.
- Never write to `CLAUDE.md` or `AGENTS.md` without explicit approval (you may suggest
updates).
- Notes must be self-contained. They must be understandable without the originating conversation.
  Avoid local labels such as "category 15" or "scenario 9", or explain their meaning or link to
  clarifying context.

## Filing location

Read the vault's `CLAUDE.md` and top-level wiki index, then use search to find
the most specific topic subtree. Follow vault-specific naming conventions.

| Content | Location and filename |
| --- | --- |
| Repo-specific knowledge | `wiki/repos/<owner>/<repo>/` |
| Deployed state, operations, or runbooks | `wiki/systems/<system>/`, or topic subtree if applicable|
| Log of an incident or process | Topic's `diary/YYYY-MM-DD-<slug>.md` |
| Analysis, comparison, or decision rationale | Topic's `convos/YYYY-MM-DD-<slug>.md` |


This list is not exhaustive. You may need to create a new topic subtree under `wiki`. You can propose this
to the user. For topics spanning domains, choose one primary home and link to the others.

## Procedure

Write the note first with `obsidian-knowledge write` and a quoted heredoc.
Omit `--replace` for creation; include it for an intentional full-file update.

```bash
obsidian-knowledge write "wiki/topic/concept.md" <<'ENDNOTE'
# Descriptive title

Reusable knowledge with literal `identifiers` and [[wikilinks]].
ENDNOTE
```

Update the folder's `index.md`
using the same read and replace workflow. For a new folder, also link its
index from the parent.

Use the `obsidian-knowledge` skill for access errors and note-editing conventions.
