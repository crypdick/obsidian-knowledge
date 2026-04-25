# Improve-Harness: Design Spec

**Status:** Draft (awaiting user review)
**Date:** 2026-04-25
**Scope:** v1 — additive changes to the `obsidian-knowledge` plugin

## Motivation

The `obsidian-knowledge` plugin already redirects Claude Code's per-project auto-memory writes into a vault, treats the vault as the canonical knowledge layer, and syncs across machines. What it lacks is (a) consistent recall — agents do not reliably consult the vault during sessions — and (b) a mechanism for in-the-moment friction to convert into harness improvements without manual coding work.

This spec adds two complementary capabilities:

- **Substrate**: small additions that improve recall and put Claude's memory directly in the vault via a top-level symlink.
- **Meta-improvement loop**: an `improve-harness` skill that orchestrates a multi-phase, headless side-quest workflow — proposal (with internal review), main-agent executive review, implementation (with internal review), main-agent executive review, deploy.

The pattern is inspired by ADAS-style self-improving systems (Hu et al., 2024) and Voyager's growing skill library (Wang et al., 2023), adapted to a single-developer Claude Code environment with human-in-the-loop as the eval signal.

## Non-Goals (v1)

- No new CLI tool. All capabilities expressed as Claude Code skills + hooks.
- No semantic search / embeddings. Recall via `rg` against the vault.
- No auto-capture safety net. Existing nudges (Stop hooks + `remember-conversations` skill) trusted.
- No agent-portability layer. Claude Code only.
- No cross-machine state for the meta-improvement loop. Vault syncs across machines; `.improve-harness/` per-project state is local.
- No multi-vault support. If `vaults.yaml` lists multiple vaults, hooks throw an error directing the user to single-vault config.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Claude Code session (any cwd, any project)               │
│                                                          │
│  SessionStart hook → recall-init.py                      │
│   - Verifies ~/.claude/projects/ is symlinked to vault   │
│     (errors with setup instructions if not)              │
│   - Injects recall directive into system prompt          │
│                                                          │
│  Agent works normally; memory reads/writes flow through  │
│  the symlink directly into the vault.                    │
│                                                          │
│  PostToolUse hook → reflect-nudge.sh                     │
│   - Fires every 10 bash calls (continuous reflection)    │
│                                                          │
│  Friction detected (slash cmd or trigger phrases)        │
│   ↓                                                      │
│  improve-harness skill activates                         │
│   ↓                                                      │
│  Phase 0  Incident report written                        │
│  Phase 1  PROPOSAL: side quest with INTERNAL review      │
│           loop (author + reviewer subagents ping-pong    │
│           until proposal-quality reviewer approves)      │
│  Phase 2  Main agent EXECUTIVE review of proposal        │
│           (resume + iterate up to 3x; escalate on cap)   │
│  Phase 3  IMPL: side quest with INTERNAL review loop     │
│           via superpowers:subagent-driven-development    │
│  Phase 4  Main agent EXECUTIVE review of diff            │
│           (resume + iterate up to 3x)                    │
│  User approves                                           │
│  Phase 5  DEPLOY: claude -p haiku (merge/bump/push)      │
│  Phase 6  Main agent prompts user to reload plugins      │
└──────────────────────────────────────────────────────────┘

           Vault (synced across machines)
           ─────────────────────────────────────
           ~/.claude/projects/  →  symlinked to
           <vault-root>/wiki/systems/repos/

           Claude's per-project memory dirs
           (~/.claude/projects/<encoded-cwd>/)
           land naturally in
           <vault-root>/wiki/systems/repos/<encoded-cwd>/
```

## Substrate

### Memory location: top-level symlink

A one-time setup operation creates a single symlink that supplants Claude Code's per-project memory storage with vault-backed storage:

```bash
# Move existing per-project memory into the vault
mkdir -p <vault-root>/wiki/systems/repos/
mv ~/.claude/projects/* <vault-root>/wiki/systems/repos/

# Replace the projects dir with a symlink
rmdir ~/.claude/projects
ln -s <vault-root>/wiki/systems/repos/ ~/.claude/projects
```

After this:
- Every `~/.claude/projects/<encoded-cwd>/...` path is actually `<vault-root>/wiki/systems/repos/<encoded-cwd>/...`
- Claude's existing memory mechanisms (read MEMORY.md, write user_*/feedback_*/project_*/reference_*) all just work — they're operating on vault paths via the symlink
- Per-project memory now syncs across machines via the vault's sync layer
- Writes through the symlink are still subject to existing `protect-vault.py` safeguards (which keep the type-aware redirect logic as belt-and-suspenders)

Setup is documented in README. The SessionStart hook (below) verifies the symlink exists and errors with setup instructions if not.

### `hooks/recall-init.py` (NEW, SessionStart)

Two responsibilities:

1. **Verify symlink.** If `~/.claude/projects/` is not a symlink to the vault repos dir, error with: *"Memory symlink not configured. See README for setup. Run `/setup-harness` (or follow the README steps) to migrate."*  Hook still allows the session to proceed (non-blocking warning) — the agent works normally without vault-backed memory.
2. **Inject recall directive.** Add a SessionStart context block:

   > Knowledge wiki: `<vault-root>/wiki/`. Claude's memory system is supplanted by the obsidian-knowledge harness — read `<plugin-root>/skills/improve-harness/SKILL.md` completely. Grep the wiki for prior context before answering non-trivial questions.

Vault root resolved via `~/.config/obsidian-knowledge/vaults.yaml` (existing config). If `vaults.yaml` lists multiple vaults, hook errors with: *"Multi-vault config not supported. Configure exactly one vault."*

### `hooks/reflect-nudge.sh` (NEW, PostToolUse on Bash)

Fires every 10 bash invocations within a session. Counter state in `~/.cache/obsidian-knowledge/<session-id>/bash-count`. Continuous reflection — no per-session suppression. On each Nth call (10, 20, 30, ...), the hook injects:

> Step back: any friction worth feeding back into the harness? If yes, invoke `/improve-harness` or describe the friction.

### `hooks/protect-vault.py` (UNCHANGED)

Existing read-only `_sources/`, destructive command guards, published-file guard, and auto-memory write redirect remain. The auto-memory write redirect becomes partially redundant (writes through the symlink already land in the vault) but is harmless and provides type-aware semantics for `user_*`/`feedback_*`/`reference_*` types if desired.

## `skills/improve-harness/`

The headline feature. The skill body is the **single source of truth** for the workflow — every phase's actual instructions live here. Phase invocations are minimal: they reference the skill, identify which phase to execute, and pass inputs.

### Trigger

Two trigger paths, both supported:

1. **Slash command:** `/improve-harness <free-text friction description>`
2. **Natural-language phrases** detected by main agent: "the harness just fucked me", "wtf this keeps happening", "let's fix this hook", "this keeps blocking me", bare profanity ("fuck", "wtf") near a description of friction.

In both cases, the main agent generates a slug from the friction description (kebab-case, ≤6 words, append `-YYYY-MM-DD` for uniqueness).

### Classification (in skill body)

Before forking, the main agent classifies along two axes:

**Scope:**
- **GLOBAL** — friction in plugin behavior (hooks, skills, CLAUDE.md instructions). Side quest works on `obsidian-knowledge` plugin repo.
- **REPO-SCOPED** — friction with a project-specific convention or workflow. Side quest works on the user's current working repo.

**Complexity:**
- **TRIVIAL** — single file, pattern-level change (regex/allowlist tweak), CLAUDE.md line, no new abstractions. Side quest skips brainstorming + writing-plans + subagent-driven-development; implements directly with one reviewer pass.
- **NON-TRIVIAL** — multi-file, new abstraction, behavior change. Side quest uses the full superpowers flow internally.

### State directory

Created at phase 0:

```
<target-repo>/.improve-harness/<slug>/
├── incident-report.md          # Phase 0 output (no length cap)
├── proposal.md                 # Phase 1 output
├── proposal-review-history.md  # Phase 1 internal review iterations
├── exec-review-history.md      # Phase 2/4 main-agent executive review iterations
├── session_id                  # For resume across phases
├── synopsis.md                 # Phase 3 output
└── status                      # Phase marker: 1|2|3|4|5|6
```

Target repo = plugin repo for GLOBAL, working repo for REPO-SCOPED. `.improve-harness/` added to that repo's `.gitignore`.

### Phase invocations (minimal — instructions live in skill body)

The skill body documents the per-phase behavior. Phase invocations are intentionally thin:

**Phase 0 — Incident report.**
Main agent writes `incident-report.md`. No length cap; main agent decides how much context the side quest needs. Includes (at minimum): friction description, JSONL transcript path (`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, latest by mtime), classification (GLOBAL/REPO-SCOPED, TRIVIAL/NON-TRIVIAL), blameless-postmortem framing instruction.

**Phase 1 — Proposal subagent (with internal review).**

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --add-dir ~/.claude/projects \
  "PHASE 1 of improve-harness workflow.
   Read <plugin-root>/skills/improve-harness/SKILL.md completely.
   Slug: <slug>.
   Inputs: .improve-harness/<slug>/incident-report.md
   Save your session_id to .improve-harness/<slug>/session_id when done."
```

The skill body specifies Phase 1 behavior:
- Side quest dispatches an **author subagent** to read the incident report + JSONL transcript, conduct the blameless postmortem, and produce a draft proposal.
- Side quest then dispatches a **proposal-quality reviewer subagent** that critiques the draft on: completeness, blameless framing, scope appropriateness, expected-outcome clarity, and (for NON-TRIVIAL) implementation feasibility.
- Author + reviewer ping-pong (max 3 iterations) until reviewer approves. Iteration log appended to `proposal-review-history.md`.
- Final proposal written to `proposal.md`.

**Phase 2 — Main agent executive review of proposal.**

Main agent reads `proposal.md`. **Executive-level critique only** (scope, intent, blameless framing, completeness — NOT line-by-line). If satisfied, surface to user. If not:

```bash
claude -r $(cat .improve-harness/<slug>/session_id) -p \
  --max-budget-usd 30 --output-format json \
  "PHASE 2 follow-up: address these executive-level concerns: <appended to exec-review-history.md>"
```

Iterate up to 3 cycles. After 3 unresolved cycles, escalate to user with explicit "I have outstanding concerns: [list]."

**Phase 3 — Implementation subagent (with internal review).**

On user approval:

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --worktree improve/<slug> \
  --permission-mode acceptEdits \
  "PHASE 3 of improve-harness workflow.
   Read <plugin-root>/skills/improve-harness/SKILL.md completely.
   Resume from session_id: <id>. Slug: <slug>.
   Implement the approved proposal on this worktree branch."
```

The skill body specifies Phase 3 behavior:
- For NON-TRIVIAL: side quest invokes `superpowers:writing-plans` then `superpowers:subagent-driven-development` (which has its own implementer + spec reviewer + code quality reviewer ping-pong internally).
- For TRIVIAL: side quest implements directly, then dispatches one code-quality reviewer subagent.
- Side quest uses the `caveman` skill at **full intensity** (not ultra) when authoring or editing any plugin skill body, with auto-clarity exceptions for security-sensitive content (hook guards involving destructive operations, irreversible actions).
- Side quest leaves changes on the worktree branch. Does not merge. Writes `synopsis.md` when done.

**Phase 4 — Main agent executive review of diff.**

Main agent runs `git -C <target-repo> diff main...improve/<slug>` and reads `synopsis.md`. Same iteration pattern as Phase 2 (executive review only). On approval, surface to user with synopsis + branch name + suggested merge command.

**Phase 5 — Deploy (delegated to deploy-harness skill).**

On user approval, invoke `deploy-harness` with the branch name. See deploy-harness section below.

**Phase 6 — Reload prompt.**

After deploy completes, main agent prompts user:

> Plugin updated to vX.Y.Z+1. Reload Claude Code plugins to activate (or restart your session).

### Caveman authoring guideline (in skill body)

The skill body itself is written in caveman-full style. Side-quest subagents are instructed:

> When authoring or editing any plugin skill body, use the caveman skill at **full** intensity. This skill is loaded into every Claude Code session that touches the plugin — multiplicative token burn applies. Cut anything not load-bearing. EXCEPTIONS (use normal prose): security warnings, hook guards involving destructive operations, multi-step sequences where fragment order risks misread.

### Token-burn warning (in skill body header)

> **Author's note to future you:**
> This skill is loaded into every Claude Code session that touches the obsidian-knowledge plugin. Multiplicative token burn applies. Caveman the prose. Cut anything not load-bearing. If adding a sentence, ask whether absence would cause a wrong outcome — if not, delete it.

## `skills/deploy-harness/`

Tiny standalone skill, callable from `improve-harness` Phase 5 OR manually for hand-edited changes.

```bash
cd <plugin-repo> && claude -p \
  --model haiku \
  --max-budget-usd 5 \
  --permission-mode acceptEdits \
  --output-format json \
  "PHASE DEPLOY of improve-harness workflow.
   Read <plugin-root>/skills/deploy-harness/SKILL.md.
   Branch: <branch>."
```

Skill body documents the routine: merge no-ff, bump patch in plugin.json, commit `chore(harness): release vX.Y.Z+1`, push to origin, report SHA + version.

## File-by-file changes

| Path | Change |
|---|---|
| `hooks/recall-init.py` | NEW — SessionStart hook (verify symlink + inject recall directive) |
| `hooks/reflect-nudge.sh` | NEW — PostToolUse on Bash, fires every 10 calls |
| `skills/improve-harness/SKILL.md` | NEW — orchestration spec, source of truth for all phase behavior |
| `skills/deploy-harness/SKILL.md` | NEW — merge/bump/push routine |
| `commands/improve-harness.md` | NEW — slash command shim |
| `commands/setup-harness.md` | NEW — one-time symlink migration |
| `.gitignore` | UPDATE — add `.improve-harness/` |
| `plugin.json` | UPDATE — register new hooks + skills + commands |
| `README.md` | UPDATE — document setup, triggers, phase flow |
| `hooks/protect-vault.py` | UNCHANGED |
| `skills/vault-organizer/` | UNCHANGED |
| `skills/remember-conversations/` | UNCHANGED |

## Acceptance criteria

- One-time symlink migration documented in README; `/setup-harness` slash command performs it
- `recall-init.py` fires at SessionStart, verifies symlink (errors with setup instructions if missing), injects recall directive in all sessions
- `reflect-nudge.sh` fires every 10 bash calls per session — continuous, no suppression
- Multi-vault `vaults.yaml` errors out cleanly with single-vault instructions
- `/improve-harness <description>` and natural-language triggers both invoke the skill
- Slug auto-generated from description; main agent never asks user to pick one
- State directory created at `<target-repo>/.improve-harness/<slug>/` with all files as appropriate per phase
- GLOBAL changes land on plugin repo worktree branch; REPO-SCOPED on working repo worktree branch
- TRIVIAL classification skips writing-plans + subagent-driven-development; NON-TRIVIAL uses full flow
- Phase invocations are minimal (point to skill, identify phase, pass inputs); detailed instructions live in skill body
- Phase 1 has internal author + proposal-quality reviewer ping-pong (max 3 iterations) before main-agent review
- Phase 3 has internal review via subagent-driven-development (NON-TRIVIAL) or single reviewer (TRIVIAL)
- Main agent's executive review (Phases 2 + 4) honors 3-cycle cap with explicit escalation
- Side quest never auto-merges; always leaves branch for human approval
- Deploy phase only fires on explicit user approval
- Caveman skill applied at **full** intensity to authored skill bodies; security-sensitive content exempted
- Token-burn warning prominent in `improve-harness` skill body
- README documents user-facing trigger phrases, setup steps, and phase walkthrough

## Follow-ups (out of scope for v1)

- **Claude Code system prompt audit.** Evaluate disabling parts of Claude Code's default system prompt (`--bare`, custom `--system-prompt-file`) for token savings in tightly-scoped sessions.
- **Embeddings layer (Tier 2 recall).** If `rg`-based recall proves insufficient (synonym/concept mismatch), add a sqlite-FTS5 BM25 index, then optionally an embedding index via `llm` CLI. Strictly additive over v1 substrate.
- **Multi-vault support.** v1 errors out; future work could pick a primary vault or symlink per-vault.
- **CLI extraction.** If/when other agents (Cursor, aider, Codex) become daily drivers, extract recall + capture into a standalone CLI; current Claude-Code-specific implementation can wrap it.

## Open design decisions deferred to implementation

- Exact bash-call counting mechanism in `reflect-nudge.sh` (parse transcript JSONL vs. file counter incremented per PostToolUse)
- Slug collision handling: hash suffix vs. timestamp suffix
- Cwd-inside-vault sessions: when the user is working IN the vault itself, behavior of recall-init.py's directive (still inject? skip?)
- `/setup-harness` UX: idempotent re-runs, what to do if `~/.claude/projects/` already contains a non-empty real directory (existing memories — migrate them, ask user, refuse?)
