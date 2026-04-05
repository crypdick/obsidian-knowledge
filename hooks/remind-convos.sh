#!/usr/bin/env bash
# Stop hook: remind the agent to file valuable conversations as vault notes.
#
# Vault detection: walks up from $PWD looking for a .obsidian/ directory,
# which Obsidian creates in every vault root. If no vault is found, the
# hook exits silently so it doesn't fire in non-vault workspaces.
#
# Fire-once guard: uses a temp file keyed to $PPID (the Claude Code
# process) so the reminder only fires once per session. Without this,
# the "block" decision prevents the session from ending, the agent
# responds, the session tries to stop again, and the hook re-fires
# in an infinite loop.

dir="$PWD"
while [[ "$dir" != "/" ]]; do
  [[ -d "$dir/.obsidian" ]] && break
  dir="$(dirname "$dir")"
done
[[ -d "$dir/.obsidian" ]] || exit 0

marker="/tmp/.obsidian-hook-convos-${PPID}"
[[ -f "$marker" ]] && exit 0
touch "$marker"

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this conversation produced a synthesis, analysis, comparison, decision rationale, or discovery worth preserving, use the remember-conversations skill to file it as a note in the relevant convos/ subfolder. If nothing worth filing or you already filed, carry on."
}
EOF
