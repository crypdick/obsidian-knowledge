# Phases

Detailed mechanics for each of the 6 phases. SKILL.md gives high-level overview; this file is the playbook.

## Phase 0 — Incident report

Main agent writes `<target-repo>/.improve-harness/<slug>/incident-report.md` per template in `templates.md`.

Determines:
- **Slug**: kebab-case from friction description, ≤6 words, append `-YYYY-MM-DD`
- **Target repo**: plugin repo for GLOBAL, working repo for REPO-SCOPED
- **JSONL transcript path**: `~/.claude/projects/<encoded-cwd>/*.jsonl` — latest by mtime

Creates `.improve-harness/<slug>/` state directory. Writes `status` file with content `0`.

## Phase 1 — Proposal subagent (with internal review)

Main agent invokes:

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

Side quest internal flow:
1. Read incident report + JSONL transcript via `--add-dir` access
2. Dispatch **author subagent**: conduct blameless postmortem, draft proposal per template
3. Dispatch **proposal-quality reviewer subagent**: critique on completeness, blameless framing, scope, feasibility
4. If reviewer rejects: author revises, reviewer re-reviews. Max 3 iterations. Log to `proposal-review-history.md`.
5. After approval: write `proposal.md`, save own session_id to `.improve-harness/<slug>/session_id`
6. Update `status` to `1`

Side quest does NOT contact main agent during inner loop.

## Phase 2 — Main agent executive review (proposal)

Main agent reads `proposal.md`. **Executive-level critique only**: scope, intent, blameless framing, completeness. NOT line-by-line.

If satisfied: surface proposal to user with summary + "approve to proceed to implementation?"

If not satisfied: append concerns to `exec-review-history.md`, then resume side quest:

```bash
claude -r $(cat .improve-harness/<slug>/session_id) -p \
  --max-budget-usd 30 --output-format json \
  "PHASE 2 follow-up: address these executive-level concerns: <text>"
```

Iteration cap: 3 cycles. After 3 unresolved cycles, escalate to user with explicit "I have outstanding concerns: <list>" — do not silently accept.

Update `status` to `2` after user approval.

## Phase 3 — Implementation subagent (with internal review)

On user approval, main agent invokes:

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

Side quest internal flow:
- For NON-TRIVIAL: invoke `superpowers:writing-plans` then `superpowers:subagent-driven-development` (which has its own implementer + spec reviewer + code quality reviewer ping-pong internally).
- For TRIVIAL: implement directly, dispatch one code-quality reviewer subagent.
- Apply caveman skill at full intensity to any plugin skill body modifications. Exceptions per `conventions.md`.
- Leave changes on the worktree branch. DO NOT MERGE.
- Write `synopsis.md` per template
- Update `status` to `3`

## Phase 4 — Main agent executive review (diff)

Main agent runs `git -C <target-repo> diff main...improve/<slug>` and reads `synopsis.md`. Executive-level critique only.

If satisfied: surface synopsis + branch + suggested merge command to user.

If not satisfied: same iteration pattern as Phase 2 (append to `exec-review-history.md`, resume side quest, max 3 cycles, escalate on cap).

Update `status` to `4` after user approval.

## Phase 5 — Deploy

On user approval, main agent invokes the `deploy-harness` skill via:

```bash
cd <plugin-repo> && claude -p \
  --model haiku \
  --max-budget-usd 5 \
  --permission-mode acceptEdits \
  --output-format json \
  "PHASE DEPLOY of improve-harness workflow.
   Read <plugin-root>/skills/deploy-harness/SKILL.md.
   Branch: improve/<slug>."
```

Update `status` to `5` on completion.

## Phase 6 — Reload prompt

Main agent surfaces to user:

> Plugin updated to vX.Y.Z+1. Reload Claude Code plugins to activate (or restart your session).

Update `status` to `6`.
