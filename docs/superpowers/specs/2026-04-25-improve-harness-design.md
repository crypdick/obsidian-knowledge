# Improve-Harness: Design Spec

> **Superseded 2026-07-13.** This historical design must not be implemented.
> `obsidian-knowledge papercut "what happened"` now records friction as a
> lightweight, durable report; investigation and implementation remain explicit
> user-directed work.

**Status:** Draft (awaiting user review)
**Date:** 2026-04-25
**Scope:** v1 — additive changes to the `obsidian-knowledge` plugin

## Motivation

The `obsidian-knowledge` plugin already redirects Claude Code's per-project auto-memory writes into a vault, treats the vault as the canonical knowledge layer, and syncs across machines. What it lacks is (a) consistent recall — agents do not reliably consult the vault during sessions — and (b) a mechanism for in-the-moment friction to convert into harness improvements without manual coding work.

This spec adds two complementary capabilities:

- **Substrate**: small additions that improve recall, put Claude's memory directly in the vault via a top-level symlink, and inject a harness primer into every session.
- **Meta-improvement loop**: an `improve-harness` skill (organized for progressive disclosure) that orchestrates a multi-phase, headless side-quest workflow whenever harness friction is identified — proposal (with internal review), main-agent executive review, implementation (with internal review), main-agent executive review, deploy.

The pattern is inspired by ADAS-style self-improving systems (Hu et al., 2024) and Voyager's growing skill library (Wang et al., 2023), adapted to a single-developer Claude Code environment with human-in-the-loop as the eval signal.

## Non-Goals (v1)

- No new CLI tool. All capabilities expressed as Claude Code skills + hooks.
- No semantic search / embeddings. Recall via `rg` against the vault.
- No auto-capture safety net. Existing Stop nudges (`update-changelog.py`, `remind-convos.py`) trusted as decision-time reminders.
- No agent-portability layer. Claude Code only.
- No cross-machine state for the meta-improvement loop. Vault syncs across machines; `.improve-harness/` per-project state is local.
- No multi-vault support. If `vaults.yaml` lists multiple vaults, hooks throw an error directing the user to single-vault config.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Claude Code session (any cwd, any project)               │
│                                                          │
│  SessionStart hook → recall-init.py                      │
│   - Verifies ~/.claude/projects/ symlinks to vault       │
│   - Injects HARNESS PRIMER (5 directives) into context   │
│                                                          │
│  Agent works normally; memory reads/writes flow through  │
│  the symlink directly into the vault.                    │
│                                                          │
│  PostToolUse hook → reflect-nudge.sh                     │
│   - Fires every 10 bash calls (continuous reflection)    │
│                                                          │
│  Stop hooks (existing, unchanged):                       │
│   - update-changelog.py — decision-time changelog nudge  │
│   - remind-convos.py — decision-time capture nudge       │
│                                                          │
│  Friction detected (slash cmd or trigger phrases)        │
│   ↓                                                      │
│  improve-harness skill activates                         │
│   ↓                                                      │
│  Main agent reads SKILL.md (thin index) → reads relevant │
│  sub-asset files (phases.md, templates.md, conventions)  │
│   ↓                                                      │
│  Phase 0  Incident report written                        │
│  Phase 1  PROPOSAL: side quest with INTERNAL review      │
│           loop (author + reviewer subagents ping-pong)   │
│  Phase 2  Main agent EXECUTIVE review of proposal        │
│  Phase 3  IMPL: side quest with INTERNAL review loop     │
│           via superpowers:subagent-driven-development    │
│  Phase 4  Main agent EXECUTIVE review of diff            │
│  User approves                                           │
│  Phase 5  DEPLOY: claude -p haiku                        │
│  Phase 6  Main agent prompts user to reload plugins      │
└──────────────────────────────────────────────────────────┘

           Vault (synced across machines)
           ─────────────────────────────────────
           ~/.claude/projects/  →  symlinked to
           <vault-root>/wiki/systems/repos/
```

## Substrate

### Memory location: top-level symlink (one-time setup)

`/setup-harness` slash command performs the migration:

1. **Rsync first.** `rsync -av ~/.claude/projects/ <vault-root>/wiki/systems/repos/`. Existing per-project memory dirs land in the vault. Rsync is idempotent and content-preserving.
2. **Detect collisions.** If files exist in both the source and target with divergent content (likely from prior sync of the same repo across machines), rsync will note them. The command surfaces the list of collisions and **asks the agent to merge them manually** — the agent reads each conflicting file pair and produces a merged version. No automated merge.
3. **Replace projects dir with symlink.** After rsync (and any merge resolution): `rmdir ~/.claude/projects && ln -s <vault-root>/wiki/systems/repos/ ~/.claude/projects`.
4. **Idempotent re-runs.** If `~/.claude/projects/` is already the symlink, the command exits with a confirmation message. If it's a real dir but already empty, just symlink. If it's a real dir with new content (e.g., new project memory created on a different machine), re-run rsync + merge.

After setup:
- Every `~/.claude/projects/<encoded-cwd>/...` path is actually `<vault-root>/wiki/systems/repos/<encoded-cwd>/...`
- Claude's existing memory mechanisms (read MEMORY.md, write user_*/feedback_*/project_*/reference_*) all just work
- Per-project memory now syncs across machines via the vault's sync layer
- Writes through the symlink are still subject to existing `protect-vault.py` safeguards

### `hooks/recall-init.py` (NEW, SessionStart)

Two responsibilities:

1. **Verify symlink.** If `~/.claude/projects/` is not a symlink to the vault repos dir, error with: *"Memory symlink not configured. Run `/setup-harness` to migrate."*  Hook still allows session to proceed (non-blocking) — the agent works normally without vault-backed memory.
2. **Inject the harness primer.** Add a SessionStart context block:

   > **You are operating under the obsidian-knowledge harness.**
   > - **Memory:** Claude's per-project memory lives at `<vault-root>/wiki/systems/repos/`. `~/.claude/projects/` is symlinked there.
   > - **Recall:** before answering non-trivial questions, search the wiki with `rg <pattern> <vault-root>/wiki/`.
   > - **Capture:** at session end, file conversation outcomes (use the `remember-conversations` skill) and update the changelog.
   > - **Reflect on friction:** if you struggle with the harness, hit unexpected blocks, or repeat the same workaround, invoke `/improve-harness` to fix the system.
   > - **Reflect on user frustration:** if the user expresses frustration ("fuck", "wtf", "this keeps happening"), invoke `/improve-harness`. The agent is not the unit of analysis — the system is.

This primer is **the load-bearing context** for the entire harness. It must stand alone — agents that read only this primer should know what to do without reading any skill body.

Vault root resolved via `~/.config/obsidian-knowledge/vaults.yaml`. If `vaults.yaml` lists multiple vaults, hook errors with: *"Multi-vault config not supported. Configure exactly one vault."*

### `hooks/reflect-nudge.sh` (NEW, PostToolUse on Bash)

Fires every 10 bash invocations within a session. Counter state in `~/.cache/obsidian-knowledge/<session-id>/bash-count`. Continuous — no per-session suppression. On each Nth call (10, 20, 30, ...), the hook injects:

> Step back: any friction worth feeding back into the harness? If yes, invoke `/improve-harness` or describe the friction.

### `hooks/protect-vault.py` (UNCHANGED)

Existing safeguards remain (read-only `_sources/`, destructive command guards, published-file guard, auto-memory write redirect).

### Existing Stop hooks (UNCHANGED)

`update-changelog.py` and `remind-convos.py` stay. They fire at decision time (when the agent is actually about to stop), which catches forgetting that a SessionStart primer cannot. Candidates for cleanup if the SessionStart primer proves sufficient on its own; but in v1 keep both — adding redundancy is cheap, removing proven nudges is risky.

## `skills/improve-harness/` (progressive disclosure)

The skill is organized so SKILL.md is a **thin index** that points to sub-asset files for details. The skill body itself loads only when the agent invokes the skill; sub-asset files load only when SKILL.md sends the agent to them.

### Directory layout

```
skills/improve-harness/
├── SKILL.md              # Thin index: triggers, classification, phase overview, pointers
├── phases.md             # Detailed per-phase instructions (1, 2, 3, 4, 5, 6)
├── templates.md          # Incident report template, proposal structure, synopsis structure
└── conventions.md        # Caveman authoring, token-burn warning, security exceptions
```

### `SKILL.md` (top-level index)

Contents (caveman-full, ~80 lines):

- **When to invoke:** trigger phrases (slash cmd `/improve-harness`, natural-language frustration markers, repeated friction patterns)
- **Classification (two axes):**
  - GLOBAL (plugin behavior) vs REPO-SCOPED (working repo's CLAUDE.md or .claude/)
  - TRIVIAL (single file, pattern-level) vs NON-TRIVIAL (multi-file, abstraction)
- **Slug generation:** main agent picks a kebab-case slug from friction description, appends `-YYYY-MM-DD`
- **Phase overview (one-line per phase):** what each phase produces, where state goes
- **Pointers:**
  - For phase mechanics → `phases.md`
  - For incident report / proposal / synopsis structure → `templates.md`
  - For caveman authoring + security exceptions + token-burn warning → `conventions.md`

### `phases.md` (detailed per-phase instructions)

Per-phase content:

**Phase 0 — Incident report.** Main agent writes `incident-report.md`. No length cap. Includes: friction description, JSONL transcript path (`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, latest by mtime), classification, blameless-postmortem framing instruction.

**Phase 1 — Proposal subagent (with internal review).**

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --add-dir ~/.claude/projects \
  "PHASE 1 of improve-harness workflow.
   Read <plugin-root>/skills/improve-harness/SKILL.md and follow pointers.
   Slug: <slug>.
   Inputs: .improve-harness/<slug>/incident-report.md
   Save your session_id to .improve-harness/<slug>/session_id when done."
```

Internal review: side quest dispatches an **author subagent** (reads incident report + transcript, conducts blameless postmortem, produces draft proposal); then a **proposal-quality reviewer subagent** (critiques on completeness, blameless framing, scope, expected-outcome clarity, feasibility). Author + reviewer ping-pong (max 3 iterations) until reviewer approves. Iteration log in `proposal-review-history.md`. Final to `proposal.md`.

**Phase 2 — Main agent executive review of proposal.**

Main agent reads `proposal.md`. **Executive-level critique only** (scope, intent, blameless framing, completeness — NOT line-by-line). If satisfied, surface to user. If not, resume side quest with concerns:

```bash
claude -r $(cat .improve-harness/<slug>/session_id) -p \
  --max-budget-usd 30 --output-format json \
  "PHASE 2 follow-up: address these executive-level concerns: <appended to exec-review-history.md>"
```

Iterate up to 3 cycles; escalate to user with explicit "I have outstanding concerns: [list]" on cap.

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
   Read <plugin-root>/skills/improve-harness/SKILL.md and follow pointers.
   Resume from session_id: <id>. Slug: <slug>.
   Implement the approved proposal on this worktree branch."
```

Internal review:
- For NON-TRIVIAL: side quest invokes `superpowers:writing-plans` then `superpowers:subagent-driven-development` (which has its own implementer + spec reviewer + code quality reviewer ping-pong internally).
- For TRIVIAL: side quest implements directly, then dispatches one code-quality reviewer subagent.

Side quest leaves changes on the worktree branch; does not merge. Writes `synopsis.md` when done.

**Phase 4 — Main agent executive review of diff.**

Main agent runs `git -C <target-repo> diff main...improve/<slug>` and reads `synopsis.md`. Same iteration pattern as Phase 2 (executive review only). On approval, surface synopsis + branch + suggested merge command to user.

**Phase 5 — Deploy (delegated to deploy-harness skill).**

On user approval, invoke `deploy-harness` with branch name. See deploy-harness section.

**Phase 6 — Reload prompt.**

After deploy, main agent prompts user:

> Plugin updated to vX.Y.Z+1. Reload Claude Code plugins to activate (or restart your session).

### `templates.md`

- **Incident report template:** required sections (description, transcript path, classification, postmortem framing), recommended sections (recent context, attempted workarounds), no length cap
- **Proposal structure:** what change is proposed, why (blameless reasoning), expected outcome, scope (files touched), feasibility notes
- **Synopsis structure:** what changed, files touched, branch name, plugin reload required (always yes for v1), follow-ups

### `conventions.md`

- **Caveman authoring:** when modifying any plugin skill body, use `caveman` skill at **full** intensity. Cut anything not load-bearing.
- **Caveman exceptions** (use normal prose): security warnings, hook guards involving destructive operations, multi-step sequences where fragment order risks misread, irreversible actions
- **Token-burn warning:** This skill is loaded into every session that touches the plugin. Multiplicative burn applies. If adding a sentence, ask whether absence would cause a wrong outcome — if not, delete it.
- **Sub-asset discipline:** new content goes into the right sub-asset file. SKILL.md must stay a thin index. If SKILL.md grows past ~100 lines, refactor.

### State directory (per incident)

```
<target-repo>/.improve-harness/<slug>/
├── incident-report.md          # Phase 0
├── proposal.md                 # Phase 1
├── proposal-review-history.md  # Phase 1 internal iterations
├── exec-review-history.md      # Phase 2/4 main-agent iterations
├── session_id                  # Resume token
├── synopsis.md                 # Phase 3 output
└── status                      # Phase marker
```

Target repo = plugin repo for GLOBAL, working repo for REPO-SCOPED. `.improve-harness/` added to that repo's `.gitignore`.

## `skills/deploy-harness/`

Single-file skill (no sub-assets — operation is too small to warrant progressive disclosure).

```
skills/deploy-harness/
└── SKILL.md
```

Skill body documents the routine in caveman-full: merge no-ff, bump patch in plugin.json, commit `chore(harness): release vX.Y.Z+1`, push to origin, report SHA + version. Callable from `improve-harness` Phase 5 OR manually for hand-edited changes.

Invocation:

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

## File-by-file changes

| Path | Change |
|---|---|
| `hooks/recall-init.py` | NEW — SessionStart hook (verify symlink + inject harness primer) |
| `hooks/reflect-nudge.sh` | NEW — PostToolUse on Bash, fires every 10 calls |
| `skills/improve-harness/SKILL.md` | NEW — thin index, ~80 lines caveman-full |
| `skills/improve-harness/phases.md` | NEW — detailed per-phase instructions |
| `skills/improve-harness/templates.md` | NEW — incident report / proposal / synopsis structures |
| `skills/improve-harness/conventions.md` | NEW — caveman, exceptions, token-burn warning, sub-asset discipline |
| `skills/deploy-harness/SKILL.md` | NEW — single-file skill, deploy routine |
| `commands/improve-harness.md` | NEW — slash command shim |
| `commands/setup-harness.md` | NEW — rsync + symlink + manual merge |
| `.gitignore` | UPDATE — add `.improve-harness/` |
| `.claude-plugin/plugin.json` | UPDATE — register new hooks + skills + commands |
| `README.md` | UPDATE — document setup, primer, triggers, phase flow |
| `hooks/protect-vault.py` | UNCHANGED |
| `hooks/update-changelog.py` | UNCHANGED |
| `hooks/remind-convos.py` | UNCHANGED |
| `skills/vault-organizer/` | UNCHANGED |
| `skills/remember-conversations/` | UNCHANGED |

## Acceptance criteria

- `/setup-harness` rsyncs existing memory into vault, surfaces collisions for manual merge, then symlinks; idempotent on re-run
- `recall-init.py` fires at SessionStart, verifies symlink (errors with setup instructions if missing), injects harness primer in all sessions
- Harness primer stands alone — no skill read required for an agent to know what the harness expects
- `reflect-nudge.sh` fires every 10 bash calls per session — continuous, no suppression
- Multi-vault `vaults.yaml` errors out cleanly with single-vault instructions
- `/improve-harness <description>` and natural-language triggers both invoke the skill
- Slug auto-generated from description; main agent never asks user to pick one
- improve-harness `SKILL.md` is a thin index (~80 lines) with pointers to sub-asset files; sub-assets hold the details
- Sub-asset files load only when SKILL.md sends the agent to them (progressive disclosure)
- State directory created at `<target-repo>/.improve-harness/<slug>/` with all files as appropriate per phase
- GLOBAL changes land on plugin repo worktree branch; REPO-SCOPED on working repo worktree branch
- TRIVIAL classification skips writing-plans + subagent-driven-development; NON-TRIVIAL uses full flow
- Phase invocations are minimal (point to SKILL.md, identify phase, pass inputs); detailed instructions live in `phases.md`
- Phase 1 has internal author + proposal-quality reviewer ping-pong (max 3 iterations) before main-agent review
- Phase 3 has internal review via subagent-driven-development (NON-TRIVIAL) or single reviewer (TRIVIAL)
- Main agent's executive review (Phases 2 + 4) honors 3-cycle cap with explicit escalation
- Side quest never auto-merges; always leaves branch for human approval
- Deploy phase only fires on explicit user approval
- Caveman skill applied at **full** intensity to authored skill bodies; security-sensitive content exempted
- README documents user-facing trigger phrases, setup steps, and phase walkthrough

## Follow-ups (out of scope for v1)

- **Stop hook cleanup.** If the SessionStart primer proves sufficient to drive changelog/capture behavior reliably, retire `update-changelog.py` and `remind-convos.py`.
- **Claude Code system prompt audit.** Evaluate disabling parts of Claude Code's default system prompt (`--bare`, custom `--system-prompt-file`) for token savings.
- **Embeddings layer (Tier 2 recall).** If `rg`-based recall proves insufficient, add a sqlite-FTS5 BM25 index, then optionally an embedding index via `llm` CLI.
- **Multi-vault support.** v1 errors out; future work could pick a primary vault or symlink per-vault.
- **CLI extraction.** If/when other agents (Cursor, aider, Codex) become daily drivers, extract recall + capture into a standalone CLI.

## Open design decisions deferred to implementation

- Exact bash-call counting mechanism in `reflect-nudge.sh` (parse transcript JSONL vs. file counter incremented per PostToolUse)
- Slug collision handling: hash suffix vs. timestamp suffix
- Cwd-inside-vault sessions: when the user is working IN the vault itself, behavior of recall-init.py's primer (still inject? skip?)
