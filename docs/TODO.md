# Roadmap

Design ideas and open decisions for future work.

## `grade:` YAML frontmatter property

Add a note-quality marker such as `grade: A` or `grade: stub` to support folder
scorecards, low-quality-note reminders, and an organizer grading mode.

Decide the scale, which notes require grades, and whether agents may suggest
grades or only humans may assign them.

## Note-improver agent

Propose a diff for one note: tighten prose, triage links, suggest related notes,
check frontmatter, and suggest a grade. Possible triggers include a manual
`/improve-note <path>` command or a doctor recommendation.

Require confirmation before editing primary content and respect published-file
protection.

## Convention-sweep: skip more false-positive sources

The sweep already skips fenced blocks and inline code. Extend it to:

- Skip wikilinks in HTML comments.
- Skip dated-folder checks for notes with `type: template`.
- Treat YAML errors in staging folders such as `_drafts/` as warnings.
