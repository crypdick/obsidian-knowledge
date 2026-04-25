# Improve-Harness: Design Spec

**Status:** Draft (awaiting user review)
**Date:** 2026-04-25
**Scope:** v1 — additive changes to the `obsidian-knowledge` plugin

## Motivation

The `obsidian-knowledge` plugin already redirects Claude Code's per-project auto-memory writes into a vault, treats the vault as the canonical knowledge layer, and syncs across machines. What it lacks is (a) consistent recall — agents do not reliably consult the vault during sessions — and (b) a mechanism for in-the-moment friction to convert into harness improvements without manual coding work.

This spec adds two complementary capabilities:

- **Substrate**: small additions that improve recall and ensure Claude's memory location IS the vault.
- **Meta-improvement loop**: an `improve-harness` skill that orchestrates a multi-phase, headless side-quest workflow whenever harness friction is identified — proposal, two-layer review, implementation, deploy.

The pattern is inspired by ADAS-style self-improving systems (Hu et al., 2024) and Voyager's growing skill library (Wang et al., 2023), adapted to a single-developer Claude Code environment with human-in-the-loop as the eval signal.

## Non-Goals (v1)

- No new CLI tool. All capabilities expressed as Claude Code skills + hooks.
- No semantic search / embeddings. Recall via `rg` against the vault.
- No auto-capture safety net. Existing nudges (Stop hooks + `remember-conversations` skill) trusted.
- No agent-portability layer. Claude Code only.
- No cross-machine state for the meta-improvement loop. Vault syncs across machines; `.improve-harness/` per-project state is local.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Claude Code session (any cwd, any project)               │
│                                                          │
│  SessionStart hook → recall-init.py                      │
│   - Ensures memory dir is symlinked to vault             │
│   - Writes MEMORY.md admonition if not present           │
│   - Injects recall directive into system prompt          │
│                                                          │
│  Agent works normally; reads/writes flow through symlink │
│                                                          │
│  Stop hook (after 15 bash calls) → reflect-nudge.sh      │
│   - Reminds: any friction worth feeding back?            │
│                                                          │
│  Friction detected (slash cmd or trigger phrases)        │
│   ↓                                                      │
│  improve-harness skill activates                         │
│   ↓                                                      │
│  Phase 0  Brief written to .improve-harness/<slug>/     │
│  Phase 1  PROPOSAL: claude -p sonnet (read-only side-   │
│           quest; produces proposal.md, no impl)         │
│  Phase 2  Main agent EXECUTIVE review of proposal       │
│           (resume + iterate up to 3x; escalate on cap)  │
│  Phase 3  IMPL: claude -p sonnet --worktree (resumes    │
│           Phase 1 session; uses subagent-driven-        │
│           development internally)                       │
│  Phase 4  Main agent EXECUTIVE review of diff           │
│           (resume + iterate up to 3x)                   │
│  User approves                                           │
│  Phase 5  DEPLOY: claude -p haiku (merge/bump/push      │
│           via deploy-harness skill)                     │
│  Phase 6  Main agent prompts user to reload plugins     │
└──────────────────────────────────────────────────────────┘

           Vault (synced across machines)
           ─────────────────────────────────────
           wiki/systems/repos/<slug>/memory/  ← symlinked from
                                                ~/.claude/projects/<encoded-cwd>/memory/
```

## Substrate

### `hooks/recall-init.py` (NEW, SessionStart)

A single SessionStart hook that combines three responsibilities:

1. **Ensure symlink.** For the current cwd, compute the encoded project path (`~/.claude/projects/<encoded-cwd>/memory/`). If the path is not a symlink:
   - Compute the target vault path: `<vault-root>/wiki/systems/repos/<slug>/memory/`. The slug is derived from cwd basename, with collision handling via path hash.
   - Create the target dir if it doesn't exist.
   - Move any existing memory files from the Claude path into the target vault path (preserves existing memories on first migration).
   - Replace the Claude path with a symlink to the vault path.
2. **Ensure MEMORY.md admonition.** Write or update the MEMORY.md inside the symlinked dir to include a header:

   ```
   # Memory (supplanted by harness)

   This per-project memory is symlinked to <vault-path> and supplanted by the obsidian-knowledge harness.
   For deep context, search the vault: rg <pattern> <vault-root>/wiki/
   For the harness improvement loop, see <plugin-root>/skills/improve-harness/SKILL.md
   ```

   Preserves any existing pointer entries below the header.
3. **Inject recall directive.** Add a SessionStart context block:

   > Knowledge wiki: `<vault-root>/wiki/`. Read `<plugin-root>/skills/improve-harness/SKILL.md` for harness orientation. Grep the wiki for prior context before answering non-trivial questions.

Vault root resolved via `~/.config/obsidian-knowledge/vaults.yaml` (existing config). If the cwd is not under any configured vault, the directive still injects (recall benefits any session); the symlink step is gated to "vault exists" for safety.

### `hooks/reflect-nudge.sh` (NEW, Stop)

Stop hook that fires once per session after the agent has executed 15+ bash commands. Counter state in `~/.cache/obsidian-knowledge/<session-id>/bash-count`. When threshold is crossed:

> Step back: any friction worth feeding back into the harness? If yes, invoke /improve-harness or describe the friction.

Fires once per session. Subsequent threshold crossings (30, 45, ...) suppressed via a `reflect-fired` marker.

### `hooks/protect-vault.py` (UNCHANGED)

Existing read-only `_sources/`, destructive command guards, published-file guard, and auto-memory write redirect remain. The auto-memory write redirect becomes partially redundant (writes through the symlink land in the vault naturally) but is harmless and provides type-aware semantics for `user_*`/`feedback_*`/`reference_*` types.

## `skills/improve-harness/`

The headline feature. The skill body is the *guide for the main agent* on how to orchestrate the side-quest workflow.

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
├── incident-brief.md           # Phase 0 output
├── proposal.md                 # Phase 1 output
├── review-history.md           # Main agent's executive review iterations
├── session_id                  # For resume across phases
├── synopsis.md                 # Phase 3 output (impl summary)
└── status                      # Phase marker: 1|2|3|4|5|6
```

Target repo = plugin repo for GLOBAL, working repo for REPO-SCOPED. `.improve-harness/` added to that repo's `.gitignore`.

### Phase walkthrough

**Phase 0 — Brief.**
Main agent writes `incident-brief.md`:
- What happened (friction summary, ≤3 sentences)
- JSONL transcript path: `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (find latest by mtime)
- Blameless-postmortem framing instruction
- Classification (GLOBAL vs REPO-SCOPED, TRIVIAL vs NON-TRIVIAL)

**Phase 1 — Proposal subagent.**

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --add-dir ~/.claude/projects \
  "Read .improve-harness/<slug>/incident-brief.md and the linked transcript.
   Conduct a blameless postmortem: the agent is not the unit of analysis, the system is.
   Output your proposal to .improve-harness/<slug>/proposal.md.
   Save your session_id to .improve-harness/<slug>/session_id.
   DO NOT IMPLEMENT — proposal only.
   For NON-TRIVIAL changes, use superpowers:brainstorming-style structured thinking;
   for TRIVIAL, write a tight 5-bullet proposal."
```

**Phase 2 — Main agent executive review.**

Main agent reads `proposal.md`. Executive-level critique only (scope, intent, blameless framing, completeness — NOT line-by-line). If satisfied, surface to user. If not:

```bash
claude -r $(cat .improve-harness/<slug>/session_id) -p \
  --max-budget-usd 30 --output-format json \
  "Address these concerns: <appended to review-history.md>"
```

Iterate up to 3 cycles. After 3 unresolved cycles, escalate to user with explicit "I have outstanding concerns: [list]."

**Phase 3 — Implementation subagent.**

On user approval:

```bash
cd <target-repo> && claude -p \
  --model sonnet \
  --max-budget-usd 30 \
  --output-format json \
  --worktree improve/<slug> \
  --permission-mode acceptEdits \
  "Resume from session_id: <id>. Implement the approved proposal on this worktree branch.
   For NON-TRIVIAL: use superpowers:writing-plans then superpowers:subagent-driven-development.
   For TRIVIAL: implement directly, then dispatch one code-quality reviewer subagent.
   Use the 'caveman' skill (full intensity) when authoring or editing any plugin skill body,
   with auto-clarity exceptions for security-sensitive content (hooks involving guards,
   destructive ops, irreversible actions).
   Leave changes on the branch. Do not merge. Write synopsis.md when done."
```

**Phase 4 — Main agent executive review of diff.**

Main agent runs `git diff` (or `git -C <target-repo> log <branch>`) and reads `synopsis.md`. Same iteration pattern as Phase 2: executive review (does the change match the proposal? are there obvious red flags?), send back fixes via resume, max 3 cycles. On approval, surface to user with synopsis + branch name + suggested merge command.

**Phase 5 — Deploy (delegated to deploy-harness skill).**

On user approval, invoke `deploy-harness` with the branch name. See deploy-harness section below.

**Phase 6 — Reload prompt.**

After deploy completes, main agent prompts user:

> Plugin updated to vX.Y.Z+1. Reload Claude Code plugins to activate (or restart your session).

### Caveman authoring guideline (in skill body)

The skill body itself is written in caveman-full style. Side-quest subagents are instructed:

> When authoring or editing any plugin skill body, use the caveman skill at full intensity. This skill is loaded into every Claude Code session that touches the plugin — multiplicative token burn applies. Cut anything not load-bearing. EXCEPTIONS (use normal prose): security warnings, hook guards involving destructive operations, multi-step sequences where fragment order risks misread.

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
  "Merge branch <branch> into main (no-ff). Bump patch in plugin.json (X.Y.Z → X.Y.Z+1).
   Create commit 'chore(harness): release vX.Y.Z+1'. Push to origin.
   Report final SHA and version."
```

Skill body: ~30 lines covering the routine, the version-bump regex, and expected report format. No orchestration logic.

## File-by-file changes

| Path | Change |
|---|---|
| `hooks/recall-init.py` | NEW — SessionStart hook (symlink + admonition + recall directive) |
| `hooks/reflect-nudge.sh` | NEW — Stop hook (fires once after 15 bash calls per session) |
| `skills/improve-harness/SKILL.md` | NEW — orchestration spec, caveman-authored |
| `skills/improve-harness/incident-brief-template.md` | NEW — what a good brief contains |
| `skills/deploy-harness/SKILL.md` | NEW — merge/bump/push routine |
| `.gitignore` | UPDATE — add `.improve-harness/` |
| `plugin.json` | UPDATE — register new hooks + skills |
| `README.md` | UPDATE — document new pieces, trigger phrases, phase flow |
| `commands/improve-harness.md` | NEW — slash command shim |
| `hooks/protect-vault.py` | UNCHANGED |
| `skills/vault-organizer/` | UNCHANGED |
| `skills/remember-conversations/` | UNCHANGED |

## Acceptance criteria

- `recall-init.py` fires at SessionStart in any cwd, creates symlink + admonition for vault-known projects, injects recall directive in all sessions
- `reflect-nudge.sh` fires once per session after 15 bash calls; subsequent thresholds suppressed
- `/improve-harness <description>` and natural-language triggers both invoke the skill
- Slug auto-generated from description; main agent never asks user to pick one
- State directory created at `<target-repo>/.improve-harness/<slug>/` with all six files as appropriate per phase
- GLOBAL changes land on plugin repo worktree branch; REPO-SCOPED changes land on working repo worktree branch
- TRIVIAL classification skips brainstorming and writing-plans; NON-TRIVIAL uses full superpowers flow
- Main agent's executive review honors 3-cycle cap with explicit escalation when exceeded
- Side quest never auto-merges; always leaves branch for human approval
- Deploy phase only fires on explicit user approval, performs merge + bump + push
- Caveman skill applied to authored skill bodies; security-sensitive content exempted
- Token-burn warning prominent in `improve-harness` skill body
- README documents user-facing trigger phrases and phase walkthrough

## Open TODOs (block implementation)

1. **Inspect Claude Code's auto-memory format.** Before writing `recall-init.py`, examine `~/.claude/projects/*/memory/MEMORY.md` and individual memory files (user_*, feedback_*, project_*, reference_*) to understand structure, frontmatter conventions, and naming. Borrow what's good for the vault layout under `wiki/systems/repos/<slug>/memory/`. Document findings in implementation plan.

## Follow-ups (out of scope for v1)

- **Skill golfing pass.** After v1 ships, golf each existing plugin skill body (`vault-organizer`, `remember-conversations`, `protect-vault`) for token efficiency. Multiplicative burn applies retroactively.
- **Claude Code system prompt audit.** Evaluate disabling parts of Claude Code's default system prompt (`--bare`, custom `--system-prompt-file`) for token savings in tightly-scoped sessions.
- **Embeddings layer (Tier 2 recall).** If `rg`-based recall proves insufficient (synonym/concept mismatch), add a sqlite-FTS5 BM25 index, then optionally an embedding index via `llm` CLI. Strictly additive over v1 substrate.
- **Symlink type-aware refinement.** If type-mixing in per-project memory dirs becomes a problem (e.g., `user_*` facts not compounding across projects), add a gardener pass that periodically extracts type-prefixed files into global vault locations.
- **CLI extraction.** If/when other agents (Cursor, aider, Codex) become daily drivers, extract recall + capture into a standalone CLI; current Claude-Code-specific implementation can wrap it.

## Open design decisions deferred to implementation

- Exact bash-call counting mechanism in `reflect-nudge.sh` (parse transcript JSONL vs. PostToolUse counter)
- Slug collision handling: hash suffix vs. timestamp suffix
- Whether to gate auto-symlink creation on `vaults.yaml` listing (safety) or attempt for any cwd
- Multi-vault behavior: if `vaults.yaml` lists multiple vaults, which one houses per-project memory? Options: first-listed, designated `primary:` field in vaults.yaml, or skip symlink creation when ambiguous
- Cwd-inside-vault sessions: when the user is working IN the vault itself (e.g., editing notes), skip symlink creation to avoid recursive paths
