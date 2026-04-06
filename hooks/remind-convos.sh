#!/usr/bin/env bash
# Stop hook: remind the agent to file valuable conversations as vault notes.
#
# Vault detection: walks up from $PWD looking for a .obsidian/ directory,
# which Obsidian creates in every vault root. If no vault is found, the
# hook exits silently so it doesn't fire in non-vault workspaces.
#
# Fire-once guard: the Stop hook input includes stop_hook_active (true
# when Claude is already continuing due to a prior stop hook block).
# Cooldown: fires at most once every 5 minutes per session, using a
# marker file's mtime as the timestamp.

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

# Cooldown: at most once every 5 minutes per session
session_id=$(echo "$input" | jq -r '.session_id // empty')
if [[ -n "$session_id" ]]; then
  marker="/tmp/.obsidian-hook-convos-${session_id}"
  if [[ -f "$marker" ]]; then
    age=$(( $(date +%s) - $(stat -c %Y "$marker") ))
    (( age < 300 )) && exit 0
  fi
  touch "$marker"
fi

cat <<'EOF'
{
  "decision": "block",
  "reason": "Reminder: before wrapping up, consider what's worth preserving from this session. Options: (1) Changelog entry — always, if anything substantive happened. (2) Diary note — if you worked through a process, incident, or debugging session worth narrating. (3) Convo note — if you produced analysis, comparisons, or decision rationales. (4) Guide — if you discovered a procedure others would need to repeat. Think especially about gotchas for future maintainers — tricky configurations, non-obvious failure modes, things that cost time to figure out. Use the remember-conversations skill to file. If nothing worth preserving or you already filed, carry on."
}
EOF
