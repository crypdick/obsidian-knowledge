#!/usr/bin/env bash
# new-worktree.sh -- stand up a ready-to-work git worktree in one command.
#
#   scripts/new-worktree.sh <name> [base-ref]
#
# Creates .worktrees/<name> on a fresh branch off <base-ref> (default: current
# HEAD), builds its own uv venv, installs the pre-commit hook, and copies local
# -only config that isn't tracked in git. Fast enough to run several concurrently
# -- each worktree is fully isolated (own .venv), see docs/ARCHITECTURE.md.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <name> [base-ref]" >&2
  exit 2
fi

name="$1"
base_ref="${2:-HEAD}"

repo_root="$(git rev-parse --show-toplevel)"
worktree_dir="$repo_root/.worktrees/$name"

if [[ -e "$worktree_dir" ]]; then
  echo "error: $worktree_dir already exists" >&2
  exit 1
fi

echo "==> git worktree add $worktree_dir (branch: $name, base: $base_ref)"
git -C "$repo_root" worktree add -b "$name" "$worktree_dir" "$base_ref"

echo "==> uv sync --group dev"
(cd "$worktree_dir" && uv sync --group dev)

echo "==> pre-commit install"
(cd "$worktree_dir" && uv run pre-commit install)

# Copy local-only (gitignored) config that a fresh checkout wouldn't have.
for local_file in .env .claude/settings.local.json; do
  if [[ -f "$repo_root/$local_file" ]]; then
    mkdir -p "$(dirname "$worktree_dir/$local_file")"
    cp "$repo_root/$local_file" "$worktree_dir/$local_file"
    echo "==> copied $local_file"
  fi
done

echo
echo "Ready: cd $worktree_dir"
echo "The vault registry (~/.config/obsidian-knowledge/vaults.yaml) is shared;"
echo "set OBSIDIAN_VAULT_ROOT / OBSIDIAN_KNOWLEDGE_CACHE_ROOT to a throwaway vault"
echo "if you will exercise real indexing concurrently with another worktree."
