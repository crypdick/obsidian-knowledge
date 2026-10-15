---
name: obsidian-knowledge
description: >-
  Search and maintain Obsidian vault knowledge, preserve conversation outcomes,
  and record workflow papercuts. Use for vault access, the Stop-hook capture
  reminder, or requests such as "remember this" and "save this conversation".
---

# Obsidian vault memory

The memory system replaces `MEMORY.md` and serves several goals:

1) capture reusable knowledge or rules that benefits future AI agents trying to complete tasks.
   If you spend effort figuring out how something works, write or update a guide.
2) storing research findings for topics the user is exploring.
3) tracking historical changes in case we need to do archeology
4) capture harness and tooling papercuts so future agents can avoid repeated friction.
5) retrieve existing vault knowledge when requested or when avoiding duplicate capture.

Treat notes as fallible context and verify consequential claims against code,
runtime evidence, or primary sources.

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

## User research

When a user is researching a topic in-depth, suggest capturing the conversation as a report with citations.
Ensure that the report captures the answers to all the user's questions.

## Historical changes

Changelogs are an insurance policy to help agents that need to investigate inconsistent state
or perplexing issues. For example, if we migrate files from one drive to another, but that accidentally
breaks something and the future agent is trying to investigate why the thing is broken.

It is not meant to exhaustively record every single action we take.

Changelogs keep operational guides focused on the current state and facts without littering them
with historical trivia that are unnecessary for agents trying to complete a task.

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

## Operational notes

### Vault paths

Read, search, and write notes in the configured vault. The registry is
`~/.config/obsidian-knowledge/vaults.yaml`; CLI paths are relative to its vault
root, regardless of cwd. Wiki notes start with `wiki/`; plugin state starts with
`Utility/obsidian-knowledge/`. `Utility/` and `wiki/` are siblings. Never create
`wiki/Utility/` or use the wiki directory as the vault root.

### Read and search

```bash
obsidian-knowledge search "concept or phrase"
obsidian-knowledge read "wiki/path/to/note.md"
```

Search when the user requests vault knowledge or when something merits saving
and you need to find existing coverage. Do not search merely because an answer
is nontrivial or a capture reminder fires. Read a known note directly; read
search results before relying on them. Use exact-string tools for literal names
or phrases.

### Filing location

Use a known destination directly. Consult local naming conventions, indexes,
or search only when the destination or applicable convention is unknown.

| Content | Location and filename |
| --- | --- |
| Repo-specific knowledge | `wiki/repos/<owner>/<repo>/` |
| Deployed state, operations, or runbooks | `wiki/systems/<system>/`, or topic subtree if applicable|
| Log of an incident or process | Topic's `diary/YYYY-MM-DD-<slug>.md` |
| Analysis, comparison, or decision rationale | Topic's `convos/YYYY-MM-DD-<slug>.md` |


This list is not exhaustive. You may need to create a new topic subtree under `wiki`. You can propose this
to the user. For topics spanning domains, choose one primary home and link to the others.

### Write and link notes

Read these operational notes before issuing a write command.

Write the note first with `obsidian-knowledge write` and a quoted heredoc.
Omit `--replace` for creation; include it for an intentional full-file update.

```bash
obsidian-knowledge write "wiki/topic/concept.md" <<'ENDNOTE'
# Descriptive title

Reusable knowledge with literal `identifiers` and [[wikilinks]].
ENDNOTE
```

For an update, read the existing note, integrate the change, and write the
complete result with `--replace`. The command rejects blank input, path escapes,
and accidental overwrites, and verifies its own writes; no separate readback
is needed after success. Create the note before linking it from an index.

Update the folder's `index.md`
using the same read and replace workflow. For a new folder, also link its
index from the parent.

Leave existing `updated:` timestamps to the vault linter unless the user
explicitly requests timestamp repair. Use `[[wikilinks]]` for related notes.

### Agent memory

Use the repo or host memory directory supplied by the session primer.
Keep `MEMORY.md` as a small index linking to per-fact `.md` files: at most
20 bullets or 6000 characters, summaries under 30 words, and per-fact notes
under 200 words. Consolidate at the cap. Do not create a second generated memory/index.md.
Keep `wiki/systems/knowledge-base/index.md` as a thin, bounded wikilink index
with details in linked notes. Temporary handoffs belong in campaign records.

### Changelog entry

Log consequential structural or operational changes that could explain future
inconsistent state. Ordinary note, index, and link edits need no changelog.

Create or reuse one same-session file:
`obsidian-knowledge write Utility/obsidian-knowledge/changelog/YYYY-MM-DD-HHMMSS-<slug>.md`.
When the Stop hook supplies a capture key, reuse `*-session-<capture-key>.md`

Use terse audit pointers: `YYYY-MM-DD HH:MM — <vault change> [→ [[wikilink]]]`.
Entries shouldn't be long narratives
or code blocks; rather, self-contained bread crumbs that give future agents the context they
need to understand potentially relevant major breaking changes that happened in the past

Pass this path relative to the configured vault root. Do not create or update
`changelog/index.md`.
Without a capture key, reuse a fragment already created in this session or
create a new one. Do not search other sessions' fragments for a match.

### Repair encountered instructions

Fix clear, low-risk errors in guidance encountered during the task, such as
moved paths or commands with verified replacements. Edit the canonical source,
run the relevant check, and follow its normal edit and install workflow.

Preserve user preferences, policy, safeguards, and approval rules. Report
ambiguous corrections instead of guessing. Do not start a broader audit or
reopen a completed capture decision because a hook repeats. Repairs alone do
not justify a vault note or changelog entry.

### Log workflow friction

Fix and verify defects you introduce, failed checks of your changes, and bugs
required to complete the request. Investigate unclear causes before calling
them unrelated. If blocked, report the unfinished work and exact blocker.

For unrelated harness or tooling friction, log it and continue the task:

```bash
obsidian-knowledge papercut "obsidian-knowledge search stopped producing output after an automatic index rebuild; interrupted after 2 minutes"
```

Keep entries brief and self-contained: name the tool or operation, concrete
symptom or exact error, and relevant trigger. Explain task names or local labels
only if needed to understand or reproduce the problem; otherwise omit them.

The command selects a repository log from Git `origin`, with a global fallback.
Routine debugging needs no entry; logging does not replace an in-scope fix.

For permission or connection failures, read
[access-error recovery](references/access-errors.md).
