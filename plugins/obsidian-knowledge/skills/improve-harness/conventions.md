# Conventions

Rules for any agent authoring or editing the harness.

## Caveman authoring

When write or edit any plugin skill body: use `caveman` skill at **full** intensity. Cut anything not load-bearing. Sentence absent → wrong outcome? No → delete.

## Caveman exceptions (use normal prose)

Drop caveman style for:
- Security warnings (hook guards involving destructive operations).
- Irreversible action confirmations.
- Multi-step sequences where fragment order risks misread.

When in doubt, lean normal prose. Auto-clarity beats brevity.

## Token-burn warning

This skill loaded into every Claude Code session that touches obsidian-knowledge plugin. Multiplicative token burn applies. Add sentence → ask "absence cause wrong outcome?" If no → delete.

## Sub-asset discipline

`SKILL.md` stays thin index. New content → goes in right sub-asset file:
- Phase mechanics → `phases.md`
- Templates (incident, proposal, synopsis) → `templates.md`
- Conventions (caveman, token-burn, this) → `conventions.md`

If `SKILL.md` grows past ~100 lines: refactor into new sub-asset.

## Security-sensitive content

When editing hooks that involve safety guards (e.g., `protect-vault.py`, destructive command guards, published-file blocks):

- Use normal prose, full sentences, explicit warnings
- Test thoroughly before merging — these protect user data
- Default to refusing the change if scope is unclear
- Escalate to user if proposed change weakens an existing guard
