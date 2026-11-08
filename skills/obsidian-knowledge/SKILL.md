---
name: obsidian-knowledge
description: >-
  Search and maintain Obsidian vault knowledge, preserve conversation outcomes,
  and record workflow papercuts. Use for vault access, the Stop-hook capture
  reminder, or requests such as "remember this" and "save this conversation".
---

# Obsidian vault memory

Save knowledge that helps future work: reusable findings, user preferences,
research, consequential changes, and actionable tooling friction. Retrieve vault
knowledge when requested. Don't create notes if they aren't necessary.

## Capture goals

Decide what merits saving before searching for existing coverage. A reminder
alone does not warrant a search or note. Update existing coverage where possible.

Keep guides focused on current state, integrating changes into their prose.
Link to repository documentation rather than copying it; omit cheaply
recoverable facts, transient state, and routine test results. Preserve reasoning
and constraints that affect future decisions without generalizing a one-task
preference into permanent policy.

Notes must be self-contained. Verify consequential claims against code, runtime
evidence, or primary sources; cite sources, state uncertainty, and date volatile
technical or product findings. Use related wikilinks without fragmenting a topic
unnecessarily. For in-depth user research, offer a cited report answering the
user's questions.

Do not edit `CLAUDE.md` or `AGENTS.md` without explicit user authorization.

## Operational notes

### Vault paths

Read, search, and write notes in the configured vault. The registry is
`~/.config/obsidian-knowledge/vaults.yaml`; CLI paths are relative to its vault
root, regardless of cwd. Shared preferences live separately in
`~/.config/obsidian-knowledge/config.yaml`; keep absolute vault locations in the
host registry. The former vault-local `.claude/obsidian-knowledge.yaml` is no
longer loaded. Wiki notes start with `wiki/`; plugin state starts with
`Utility/obsidian-knowledge/`. `Utility/` and `wiki/` are siblings. Never create
`wiki/Utility/` or use the wiki directory as the vault root.

### Read and search

```bash
obsidian-knowledge search "concept or phrase"
obsidian-knowledge read "wiki/path/to/note.md"
```

Read known notes directly and search results before relying on them. Use
exact-string tools for literal names or phrases.

### Filing location

Use a known destination directly. Consult local naming conventions, indexes,
or search only when the destination or applicable convention is unknown.

| Content | Location and filename |
| --- | --- |
| Repo-specific knowledge | `wiki/repos/<owner>/<repo>/` |
| Deployed state, operations, or runbooks | `wiki/systems/<system>/`, or topic subtree if applicable |
| Log of an incident or process | Topic's `diary/YYYY-MM-DD-<slug>.md` |
| Analysis, comparison, or decision rationale | Topic's `convos/YYYY-MM-DD-<slug>.md` |

Create topic subtrees when existing ones do not fit. Choose one primary home
for cross-domain topics and link from related areas.

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

New notes receive creation-only metadata when the vault configures
`note_creation.template` and declares defaults in that template. Supply the intended body
and destination; headless writes do not run Templater's interactive router.
Preserve existing `created:`, `updated:`, and `modified:` values during edits;
do not refresh timestamps unless the user explicitly requests timestamp repair.
Use `[[wikilinks]]` for related notes.

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
When the Stop hook supplies a capture key, reuse `*-session-<capture-key>.md`.

Use short, self-contained audit pointers:
`YYYY-MM-DD HH:MM — <vault change> [→ [[wikilink]]]`.
Do not create or update `changelog/index.md`. Without a capture key, reuse this
session's fragment or create one; do not search other sessions' fragments.

### Repair encountered instructions

Fix clear, low-risk errors encountered during the task in their canonical
source, using verified replacements and normal checks and installation.
Preserve policy and approval boundaries; report ambiguous corrections.
This does not authorize a broader audit or warrant capture by itself.

### Log workflow friction

Fix and verify defects introduced by or required for the task. Report unfinished
work and blockers; logging is not a substitute for an in-scope fix.

Log unrelated friction only when a future agent has a known workaround or the
user can fix it in their tools, hooks, repos, config, or machine:

```bash
obsidian-knowledge papercut "<tool or operation>: <symptom or exact error>; <trigger and known workaround>"
```

Keep entries brief and self-contained, then continue the task. Skip routine
debugging, one-off transient failures, expected concurrency, and upstream or
harness limits with no local action or workaround, unless recurring.
The command selects a repository log from Git `origin`, with a global fallback.

For permission or connection failures, read
[access-error recovery](references/access-errors.md).
