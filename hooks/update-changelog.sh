#!/usr/bin/env bash
# Stop hook: remind the agent to update CHANGELOG.md in the vault.
#
# Vault detection: walks up from $PWD looking for a .obsidian/ directory,
# which Obsidian creates in every vault root. If no vault is found, the
# hook exits silently so it doesn't fire in non-vault workspaces.
#
# Fire-once guard: the Stop hook input includes stop_hook_active (true
# when Claude is already continuing due to a prior stop hook block).
# We also use a session-scoped marker keyed to session_id from the
# hook input so the reminder fires exactly once per session, even with
# multiple agents working on the same vault.

input=$(cat)

dir="$PWD"
while [[ "$dir" != "/" ]]; do
  [[ -d "$dir/.obsidian" ]] && break
  dir="$(dirname "$dir")"
done
[[ -d "$dir/.obsidian" ]] || exit 0

# If a stop hook already blocked this turn, let Claude finish
stop_active=$(echo "$input" | jq -r '.stop_hook_active // false')
[[ "$stop_active" == "true" ]] && exit 0

# One reminder per session
session_id=$(echo "$input" | jq -r '.session_id // empty')
if [[ -n "$session_id" ]]; then
  marker="/tmp/.obsidian-hook-changelog-${session_id}"
  [[ -f "$marker" ]] && exit 0
  touch "$marker"
fi

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this session produced anything valuable for future agents to know (edits, decisions, discoveries, context, dead ends), append a dated entry to CHANGELOG.md. If nothing substantive happened or you already logged, carry on."
}
EOF
