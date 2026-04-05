#!/usr/bin/env bash
# Stop hook: remind the agent to update CHANGELOG.md in the vault.
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
  "reason": "Reminder: if this session produced anything valuable for future agents to know (edits, decisions, discoveries, context, dead ends), append a dated entry to CHANGELOG.md. If nothing substantive happened or you already logged, carry on."
}
EOF
