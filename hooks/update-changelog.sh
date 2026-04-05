#!/usr/bin/env bash
# Stop hook: remind the agent to update CHANGELOG.md in the vault.
# Only fires when working inside an Obsidian vault directory.
[[ "$PWD" == *obsidian* ]] || exit 0

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this session produced anything valuable for future agents to know (edits, decisions, discoveries, context, dead ends), append a dated entry to CHANGELOG.md. If nothing substantive happened or you already logged, carry on."
}
EOF
