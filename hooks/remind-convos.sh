#!/usr/bin/env bash
# Stop hook: remind the agent to file valuable conversations as vault notes.
# Only fires when working inside an Obsidian vault directory.
[[ "$PWD" == *obsidian* ]] || exit 0

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this conversation produced a synthesis, analysis, comparison, decision rationale, or discovery worth preserving, use the remember-conversations skill to file it as a note in the relevant convos/ subfolder. If nothing worth filing or you already filed, carry on."
}
EOF
