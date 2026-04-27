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

1. List inline files in the flagged folder
2. Classify each by the table above
3. Move misplaced files into typed subfolders via `obsidian move`
4. When creating a new typed subfolder, create its `index.md` too and link it from parent index
5. Files that genuinely belong inline — leave them. Not every file in a dumping ground is misplaced.

See `lib/index-format.md` for move syntax and index entry format.
