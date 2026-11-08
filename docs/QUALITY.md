# Quality checks

`pyproject.toml`, `prek.toml`, and `scripts/prek_hooks/` own enforced settings.
Use checks appropriate to the change; do not duplicate automated gates with
manual checklists.

## Verification

Use `uv run pytest --no-cov tests/test_relevant_area.py` for targeted tests.
The full gate runs through `new-feature merge` before integration and in CI:

```bash
uv run prek run --all-files --stage manual
```

Commits run file checks. Do not repeat the full gate at commit or after merge.
For coverage alone, use `uv run prek run pytest --stage manual`; missing lines
and branches appear in the terminal and ignored `coverage.json`. Preserve the
100% statement-and-branch floor rather than lowering it to pass.

Tests use temporary caches and a stubbed Ollama probe; they do not validate a
live embedding service. Use `python scripts/cli_smoke_test.py` when live backend
validation is relevant. For manual indexing, isolate the vault and cache as
[described in the architecture](ARCHITECTURE.md#worktree-isolation).

## Important limits

- Strict mypy checks retain configured exceptions; passing does not mean every
  function is annotated. Beartype does not exhaustively validate containers;
  Pydantic owns model fields.
- Complexity and file-size limits retain existing exemptions. Split cohesive
  behavior when changing oversized modules, not as unrelated cleanup.
- Review broad lint, typing, path, and API changes for adapter compatibility.
  Do not enable every lint rule, formatter preview, or unsafe automatic fixes.
- Dependency release delays are not a safety guarantee. Validate configuration
  with the tool that owns it.

## Documentation and agent guidance

Update affected docs with defaults, paths, commands, or behavior changes. Follow
code's `NOTE:` back-pointers and regenerate the Codex copy after hook or skill
edits. Keep architectural boundaries documented when they change.

The session primer owns runtime vault and memory context. The
[obsidian-knowledge skill](https://github.com/crypdick/obsidian-knowledge/blob/main/skills/obsidian-knowledge/SKILL.md)
owns capture, filing, memory limits, changelogs, and papercuts. The
[vault-organizer skill](https://github.com/crypdick/obsidian-knowledge/blob/main/skills/vault-organizer/SKILL.md)
owns maintenance guidance. Keep reminders focused on routing rather than
repeating those procedures.
