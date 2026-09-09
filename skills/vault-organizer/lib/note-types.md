# Note types

## Note locations

Classify files by their content:

| Type | Subfolder | Content |
| --- | --- | --- |
| Background reference | `reference/` | Editable lookup notes, distinct from protected `_sources/` originals |
| Design or plan | `plans/` | Decision records, implementation plans, roadmaps |
| Conversation | `convos/` | Comparisons, decision rationale, research synthesis |
| Diary | `diary/` | Accounts of incidents, events, or processes |
| Wiki, guide, or TODO | Folder root | Compiled knowledge, how-tos, backlogs |

## Fix a `DUMPING_GROUND`

The audit flags folders with at least four inline files whose names are
date-prefixed or end in `-design.md`, `-convo.md`, or `-diary.md`.
It does not count ordinary wiki or guide filenames.

1. Inspect the matching files and classify them using the table.
2. Move misplaced files into typed subfolders with `obsidian move`.
3. Create an index for each new subfolder and link it from the parent.
4. Leave ordinary wiki notes at the folder root.

Follow [index and move conventions](index-format.md).
