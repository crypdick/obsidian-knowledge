---
name: deploy-harness
description: Merge an approved improve-harness branch into main, bump patch version, push to origin. Callable from improve-harness Phase 5 OR manually for hand-edited changes.
---

# Deploy Harness

Single-purpose skill: ship a branch.

## Inputs

- `<branch>` — branch name to merge (typically `improve/<slug>`)
- Cwd: must be the plugin repo

## Steps

1. Verify cwd is plugin repo:
   ```bash
   git remote get-url origin
   ```
   Confirm origin is the obsidian-knowledge repo.

2. Verify branch exists locally:
   ```bash
   git branch --list <branch>
   ```

3. Checkout main and pull latest:
   ```bash
   git checkout main && git pull origin main
   ```

4. Merge no-ff:
   ```bash
   git merge --no-ff <branch>
   ```
   If merge conflicts: STOP. Surface to user. Do not attempt resolution autonomously.

5. Bump patch version in `.claude-plugin/plugin.json`:
   - Read current version (e.g., "2.1.0")
   - Bump patch (→ "2.1.1")
   - Write back, preserving JSON formatting

6. Stage version bump:
   ```bash
   git add .claude-plugin/plugin.json
   git commit -m "chore(harness): release v<X.Y.Z+1>"
   ```

7. Push to origin:
   ```bash
   git push origin main
   ```

8. Report to caller:
   - Final SHA: `git rev-parse HEAD`
   - New version: `<X.Y.Z+1>`
   - Branch deleted (locally): `git branch -d <branch>`

## Safety

- Never force-push.
- Never skip pre-commit hooks.
- Never run on a non-plugin repo.
- Never merge if `git status` shows uncommitted changes — abort with message.
