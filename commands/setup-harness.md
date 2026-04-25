---
description: Migrate Claude Code's per-project memory into the Obsidian vault and replace with a symlink. One-time setup.
---

# Setup Harness

Run the one-time migration that puts Claude Code's per-project memory directly inside the Obsidian vault via a top-level symlink.

## What this does

1. Reads vault root from `~/.config/obsidian-knowledge/vaults.yaml`. Errors if multi-vault.
2. Rsyncs existing `~/.claude/projects/*` → `<vault>/wiki/systems/repos/`.
3. Surfaces collisions (same encoded-cwd dir exists in source and target with divergent content) for manual merge.
4. Replaces `~/.claude/projects/` with a symlink to `<vault>/wiki/systems/repos/`.

## Steps to execute

1. Read `~/.config/obsidian-knowledge/vaults.yaml`. Use `python3 -c "import yaml; print([v for v in yaml.safe_load(open('/home/$USER/.config/obsidian-knowledge/vaults.yaml'))['vaults']])"`. If the file lists more than one vault, stop and tell the user: "Multi-vault config not supported. Configure exactly one vault." Exit.

2. Set `VAULT_ROOT` to the single vault path. Set `TARGET=<VAULT_ROOT>/wiki/systems/repos`.

3. Check current state of `~/.claude/projects/`:
   - If it's already a symlink to `$TARGET`: report "Already configured." Exit.
   - If it's a real directory: proceed to step 4.
   - If it doesn't exist: create `$TARGET` and create the symlink directly (skip rsync). Exit with "Created empty symlink."

4. Ensure target exists: `mkdir -p "$TARGET"`.

5. Rsync with `--ignore-existing` first to find clean copies:
   ```bash
   rsync -av --ignore-existing ~/.claude/projects/ "$TARGET"/
   ```

6. Identify collisions — files that exist in both source and target with different content:
   ```bash
   rsync -avn --existing --checksum ~/.claude/projects/ "$TARGET"/ | grep -v '^$\|sending\|sent\|total'
   ```
   This dry-run lists files that WOULD be transferred (i.e., differ).

7. If collisions exist:
   - List each collision pair to the user.
   - For each, read both versions, present a merged version, ask user to confirm or refine.
   - Write merged version to the target. Leave source as-is for now.
   - Repeat until all collisions resolved.

8. After all conflicts resolved, run a final rsync to mirror everything:
   ```bash
   rsync -av ~/.claude/projects/ "$TARGET"/
   ```

9. Verify all source content has been mirrored to target. Diff to confirm.

10. Replace projects dir with symlink:
    ```bash
    rm -rf ~/.claude/projects
    ln -s "$TARGET" ~/.claude/projects
    ```

11. Verify the symlink resolves correctly:
    ```bash
    readlink -f ~/.claude/projects
    ```
    Should print `$TARGET`.

12. Report success: "Setup complete. Restart Claude Code or open a new session for the harness primer to load."
