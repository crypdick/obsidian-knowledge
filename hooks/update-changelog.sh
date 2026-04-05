#!/usr/bin/env bash
# Stop hook: remind the agent to update CHANGELOG.md in the vault.
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

marker="/tmp/.obsidian-hook-changelog-${PPID}"
[[ -f "$marker" ]] && exit 0
touch "$marker"

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: if this session produced anything valuable for future agents to know (edits, decisions, discoveries, context, dead ends), append a dated entry to CHANGELOG.md. If nothing substantive happened or you already logged, carry on."
}
EOF
