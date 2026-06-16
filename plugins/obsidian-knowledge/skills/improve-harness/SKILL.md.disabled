---
name: improve-harness
description: Use when the harness causes friction or the user expresses frustration. Triggers a multi-phase headless side quest to fix the system. Triggered by /improve-harness slash command, frustration phrases ("fuck", "wtf", "bro", "this keeps happening"), or repeated friction patterns.
---

# Improve Harness

Multi-phase side-quest workflow to fix harness friction.

> **Author note:** Loaded into every session that touches the obsidian-knowledge plugin. Multiplicative token burn. Cut anything not load-bearing. See `conventions.md`.

## When to invoke

- User runs `/improve-harness <description>`
- User expresses frustration with system: "fuck", "wtf", "bro", "this keeps happening", "the harness just blocked me"
- Main agent observes repeated friction (same workaround N times across session)

Do NOT invoke for:
- One-off mistakes the agent made (use normal correction)
- Friction with code outside the harness (file in vault as project insight)
- Brand-new patterns where root cause is unclear (gather more data first)

## Classification (two axes)

Before forking, classify:

**Scope**:
- **GLOBAL** — friction in plugin behavior (hooks, skills, plugin CLAUDE.md). Side quest works on `obsidian-knowledge` plugin repo.
- **REPO-SCOPED** — friction with project-specific convention. Side quest works on user's working repo.

**Complexity**:
- **TRIVIAL** — single file, pattern-level (regex, allowlist, CLAUDE.md line). Side quest implements directly + one reviewer.
- **NON-TRIVIAL** — multi-file, abstraction, behavior change. Side quest uses `superpowers:writing-plans` + `superpowers:subagent-driven-development`.

## Slug generation

Main agent picks kebab-case slug from friction description. ≤6 words. Append `-YYYY-MM-DD`.

Example: "the protect-vault hook blocked a benign ls" → `protect-vault-ls-false-positive-2026-04-25`

User never picks slug.

## Workflow overview

| Phase | What | Output |
|---|---|---|
| 0 | Main agent writes incident report | `incident-report.md` |
| 1 | Side quest: proposal subagent (with internal review) | `proposal.md` |
| 2 | Main agent: executive review of proposal | approve or iterate |
| 3 | Side quest: implementation (with internal review via subagent-driven-development) | branch + `synopsis.md` |
| 4 | Main agent: executive review of diff | approve or iterate |
| 5 | Deploy via `deploy-harness` skill | merged to main, version bumped |
| 6 | Prompt user to reload plugins | done |

State dir: `<target-repo>/.improve-harness/<slug>/`. Each phase writes its outputs there.

## Pointers

- Phase mechanics, exact invocations, iteration caps → `phases.md`
- Incident report / proposal / synopsis structures → `templates.md`
- Caveman authoring, security exceptions, token-burn warning → `conventions.md`

## Safety properties

- Iteration cap (3) per main-agent review phase. Escalate on cap.
- Side quest never merges. Always leaves branch for human approval.
- All headless invocations have `--max-budget-usd 30` cap.
- Worktree isolation: side quest works on `improve/<slug>` branch in `--worktree`.
- Memory symlink (per substrate) means changes Synced across machines via the vault.
