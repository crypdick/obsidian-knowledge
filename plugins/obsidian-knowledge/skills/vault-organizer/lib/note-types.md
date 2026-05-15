# Note types

## Type → subfolder

| Type | Where it lives | Signal |
|------|---------------|--------|
| Background reference | `reference/` | Lookup-only, rarely edited. Editable notes — ≠ `_sources/` originals (write-protected). |
| Design doc / plan | `plans/` | Decision records, implementation plans, roadmaps |
| Convo note | `convos/` | Agent synthesis: comparisons, decision rationales, research summaries |
| Diary note | `diary/` | Narrative account of process, incident, event |
| Wiki / Guide / TODO | inline | Compiled knowledge, how-tos, task backlogs — stay at folder root |

## Fixing a DUMPING_GROUND

The audit only flags a folder when it sees ≥4 inline files whose **filenames
match a misplaced-file pattern**: date-prefixed (`2024-09-5-*.md`),
`*-design.md`, `*-convo.md`, or `*-diary.md`. Plain-named wiki/guide notes
never count toward the threshold — convention says they belong inline.

So when a folder is flagged, the inline files in question are almost
always genuinely misplaced. Audit output reports both the misplaced count
and the total inline count:

```
DUMPING_GROUND  <folder>  misplaced=5  inline_total=12  subfolders=3
```

Steps:

1. List inline files in the flagged folder; identify the ones matching the
   misplaced patterns (date-prefixed, design/convo/diary suffix).
2. For each, classify by the table above and move to the right typed
   subfolder via `obsidian move`.
3. When creating a new typed subfolder, create its `index.md` too and link
   it from the parent index.
4. Plain-named wiki notes — leave them. They belong inline.

See `lib/index-format.md` for move syntax and index entry format.
