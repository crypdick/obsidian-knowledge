---
name: require-plugin-version-bump
enabled: true
event: bash
action: block
pattern: obsidian-knowledge.*git\s+commit
---

**Version bump required before committing to obsidian-knowledge plugin.**

Before this commit proceeds, verify that version numbers have been bumped. Check staged changes:

```bash
cd /home/ricardo/src/PERSONAL/obsidian-knowledge && git diff --cached --name-only
```

At least these files must be in the staged changes with an updated version:
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

And if any SKILL.md was modified, bump its version too:
- `skills/vault-organizer/SKILL.md`
- `skills/remember-conversations/SKILL.md`

If versions are already bumped, re-run the commit. If not, bump them first, stage, then commit.
