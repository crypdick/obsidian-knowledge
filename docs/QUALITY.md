# Quality checks

Measured on 2026-10-03 with Python 3.14.5. Configuration lives in `pyproject.toml`,
`prek.toml`, and `scripts/prek_hooks/`. Re-measure when behavior or tooling changes;
do not treat this snapshot as a live dashboard.

## Enforced gates

The repository enforces these checks and settings:

| Gate | Setting |
|------|---------|
| Hooks | Native prek; `uv run prek install`, `uv run prek run --all-files` |
| Ruff | Core lint plus curated async, logging, security, suppression, docstring, and correctness checks; stable formatter |
| Complexity | Ruff `C901`, ceiling 15; scripts and tests retain their existing exemptions |
| Types | mypy strict on `lib`, `hooks`, and `gardener`; existing untyped-definition/call exceptions remain |
| Runtime types | Beartype on `lib.*`; decoration warnings visible; Pydantic owns model fields |
| Dead code | Vulture, confidence 80 |
| Dependencies | deptry; host imports, PEP 723 scanner dependencies and embedding compatibility pins documented in config |
| Package | check-sdist with injected junk; CI builds and smoke-tests a wheel without dev dependencies |
| Coverage | Branch and subprocess collection; **100% floor**; missing lines in terminal and `coverage.json` |
| Fast tests | xdist up to four workers, failed-first, 30-second per-test timeout |
| Hygiene | Native prek built-ins, detect-secrets with reviewed `.secrets.baseline` |
| Custom checks | Exception handling, 400 logical lines, private first-party test imports, architectural boundaries |
| Distribution mirror | `scripts/sync_codex_plugin.py --check` |

## Per-area grades

Coverage combines statement and branch coverage, including Python subprocesses.
Coverage grade: A ≥90%, B ≥80%, C ≥70%, D below 70%. Type checks pass with the
documented exceptions; that does not mean every function is fully annotated. Production
functions pass the Ruff complexity ceiling. Tests run without an embedding service.

| Area | Coverage | Grade | Type checks, complexity, and test results |
|------|---------:|:-----:|--------------------------------|
| Models, config, filters, primer, registration | 100% | A | Typed boundaries, passing core tests |
| `lib/vault_index/indexer.py` | 100% | A | Offline, vector, SQLite fallback, locking, and recovery paths |
| `lib/vault_index/cli.py` | 100% | A | Command dispatch, deadlines, error mapping, and subprocess coverage |
| `lib/vault_index/vault_files.py` | 100% | A | Boundary and atomic-write regressions pass |
| `hooks/hookslib` | 100% | A | Shared behavior tests; small modules |
| Hook entrypoints | 100% | A | Subprocess coverage included; neutral checker behavior matrix |
| Gardener commands | 100% | A | Installed CLI behavior, conservative recovery, scan exclusions, and protected-write regressions |
| Overall | 100% | A | Every measured statement and branch covered; tests exercise public behavior |

Use `uv run pytest --no-cov` for targeted tests and `uv run prek run pytest`
for coverage. The latter writes missing lines and branches to `coverage.json`,
which Git ignores. Keep the floor at 100%; do not lower it to pass a failing
check.

## Tradeoffs and remaining work

- Split oversized modules when changing cohesive behavior within them; retain
  existing exemptions until then. Ordinary files have a 400-logical-line limit.
- Beartype checks do not exhaustively validate every container element.
- Review broad annotation, pathlib, private-access, and API-style changes against
  adapter compatibility. Do not enable all lint rules, formatter preview, or
  unsafe automatic fixes.
- Tests use local fixtures and a stubbed Ollama probe. Use
  `python scripts/cli_smoke_test.py` for live backend validation.
- Validate configuration with the tool that owns it. `exclude-newer = "3 days"`
  delays fresh dependency releases; it does not guarantee dependency safety.

## Documentation gardening

Update affected docs when changing defaults, paths, commands, or hook behavior.
Follow code's `NOTE:` back-pointers. After hook or skill edits, run
`uv run python scripts/sync_codex_plugin.py`.

Review architecture after package-boundary changes and periodically compare
CLI help and defaults with the docs. Update coverage measurements from
`coverage.json`; keep type-checking limitations explicit.

## Progressive disclosure audit

Audited on 2026-10-05: skill entrypoints, organizer references,
Claude and Codex hook registrations and emitted prompts, the injected profile
index, the MCP tool descriptions, and the generated Codex distribution.
Counts below measure characters, not model tokens.

Access-error recovery now lives in
[`references/access-errors.md`](https://github.com/crypdick/obsidian-knowledge/blob/main/skills/obsidian-knowledge/references/access-errors.md).
Both the vault skill and session primer route there only for permission or
connection failures. The skill shrank from 3,830 to 3,168 characters; the primer's
access paragraph shrank from 367 to 132. Recovery instructions remain intact.

Conversation capture now lives in `obsidian-knowledge` alongside vault access
and papercut logging. The merged skill preserves the rewritten capture guidance,
with goals and rules first and operational notes near the bottom. The primer
and capture reminder defer capture policy to this skill instead of injecting
an independent acceptance gate or note-count limit. Same-session changelog keys
and the no-shared-index rule remain in the reminder.

Remaining opportunities, ordered by recurring context cost:

1. **Session primer: defer write-only rules.**
   [`primer.py`](https://github.com/crypdick/obsidian-knowledge/blob/main/lib/vault_index/primer.py)
   injects capture examples, memory-file size limits, and papercut formatting
   during startup, resume, and compaction when its debounce permits. Keep vault
   paths, recall instructions, reliability, native-memory exclusion, and capture
   routing here. Move file-layout and maintenance details to a reference
   read only before memory writes; move friction details to a reference read
   only when logging a problem. Provide those routes before removing rules.
2. **Vault skill and reflection: share conditional friction guidance.**
   [`obsidian-knowledge`](https://github.com/crypdick/obsidian-knowledge/blob/main/skills/obsidian-knowledge/SKILL.md)
   includes instruction repair and detailed papercut guidance on ordinary note
   reads. Similar prose appears in the primer and every 100th shell call's
   [`reflection reminder`](https://github.com/crypdick/obsidian-knowledge/blob/main/hooks/reflect-nudge.py).
   Link conditional references from those surfaces and retain the distinction
   between task defects requiring fixes and unrelated friction worth logging.
3. **Discovery metadata: shorten repeated trigger lists.** Keep capability and
   trigger descriptions concise while preserving explicit requests, scheduled
   organizer runs, and the capture hook trigger.

Existing boundaries work well: the organizer entrypoint is 3,847 characters and
routes seven task-specific references only when their steps apply. Alternate-vault
selection lives in `skills/vault-organizer/lib/multi-vault.md`; routine examples
use the default vault. Its installed commands carry executable detail outside
the prompt. The doctor and index-sync
nudge emit only when findings exist; secret findings have bounded samples. MCP
tool descriptions and the manual scan command are short. The shared profile
index is capped at 6,000 characters and contains links rather than full notes;
its actual contents are vault-owned. Audit that index separately before changing
which cross-session preferences load at startup.

Keep essential safeguards and routing in entrypoints. A shorter file that
silently loses a constraint or requires loading every reference is not an
improvement. Use the existing sync script to package references for Codex;
CLI hook paths are not skill paths. See [memory and recall](hooks.md#memory-and-recall).
