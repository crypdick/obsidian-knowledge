# TODO

Future work for the obsidian-knowledge plugin. Not bugs — design ideas worth tracking until someone picks them up.

## `grade:` YAML frontmatter property

Add a `grade:` field to note frontmatter as a self-rated quality marker (e.g., `grade: A`, `grade: B`, `grade: stub`). Used to:

- Power the `wiki/QUALITY.md` scorecard (currently a stub idea — see vault-organizer SKILL.md history) by aggregating grades per folder
- Let the SessionStart `doctor.py` digest surface low-graded or ungraded notes alongside convention violations
- Drive a future `vault-organizer --grade` mode that prompts for grade on any note missing one

**Open questions:** grading scale (letter? 1–5? stub/draft/solid/canonical?); whether to require grades on all wiki notes or only on indexes; whether the grade is human-only or an agent can suggest one based on length, link density, and last-edited date.

## Note-improver agent

A subagent that takes a single wiki note as input and proposes improvements: tighter prose, broken-link triage, missing wikilink suggestions (find related notes that *should* be linked), frontmatter hygiene, grade suggestion (see above). Should be read-only by default, emitting a diff for human review rather than auto-editing.

**Trigger ideas:** invoked manually via `/improve-note <path>`; suggested by `doctor.py` for low-graded notes; chained from `vault-organizer` when it encounters a stub link target that resolves to a real-but-thin note.

**Constraints:** never edits primary file content without confirmation (matches vault-organizer's discipline). Should respect `dg-publish: true` (publish-guard already blocks edits to those).

## Convention-sweep code-block awareness — done

Wikilink-extension check now skips fenced (`` ``` `` / `~~~`) blocks and inline code spans. Logged here only for the next item ↓

## Convention-sweep: skip more false-positive sources

- Skip wikilinks inside HTML comments (`<!-- ... -->`)
- Skip dated-folder check for files explicitly tagged `type: template` in frontmatter
- Treat YAML errors in `_drafts/` and similar staging zones as warnings, not violations
