#!/usr/bin/env bash
# Stop hook: remind the agent to file valuable conversations as vault notes.
#
# Vault detection: walks up from $PWD looking for a .obsidian/ directory,
# which Obsidian creates in every vault root. If no vault is found, the
# hook exits silently so it doesn't fire in non-vault workspaces.

dir="$PWD"
while [[ "$dir" != "/" ]]; do
  [[ -d "$dir/.obsidian" ]] && break
  dir="$(dirname "$dir")"
done
[[ -d "$dir/.obsidian" ]] || exit 0

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this conversation produced a synthesis, analysis, comparison, decision rationale, or discovery worth preserving, use the remember-conversations skill to file it as a note in the relevant convos/ subfolder. If nothing worth filing or you already filed, carry on."
}
EOF
