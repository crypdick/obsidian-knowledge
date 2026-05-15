# Templates

Document structures for the three artifacts produced by the workflow.

## Incident report (Phase 0 output)

Path: `<target-repo>/.improve-harness/<slug>/incident-report.md`

Required sections:
- **Friction summary** — what happened, in user's words if available
- **Transcript path** — path to the JSONL transcript at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (find latest by mtime)
- **Classification** — GLOBAL or REPO-SCOPED; TRIVIAL or NON-TRIVIAL
- **Postmortem framing** — explicit instruction: "blameless postmortem; agent is not the unit of analysis, the system is"

Recommended sections:
- **Recent context** — what was the agent doing when friction hit
- **Attempted workarounds** — what didn't work
- **Suspected root cause** — main agent's guess (subagent will verify or refute)

No length cap. Main agent decides how much context the side quest needs.

## Proposal (Phase 1 output)

Path: `<target-repo>/.improve-harness/<slug>/proposal.md`

Required sections:
- **Diagnosis** — what about the system caused the friction (blameless)
- **Proposed change** — what to modify, where (specific files)
- **Why this fixes it** — causal chain from change to outcome
- **Expected outcome** — observable behavior change
- **Scope** — files touched, classification confirmed (TRIVIAL/NON-TRIVIAL)
- **Feasibility notes** — anything tricky about implementing

Reviewer subagent checks: completeness, blameless framing, scope appropriateness, expected-outcome clarity, feasibility.

## Synopsis (Phase 3 output)

Path: `<target-repo>/.improve-harness/<slug>/synopsis.md`

Required sections:
- **What changed** — one paragraph summary
- **Files touched** — explicit list
- **Branch name** — `improve/<slug>`
- **Plugin reload required** — yes (always for v1)
- **Follow-ups** — anything the change surfaced that's not in scope
