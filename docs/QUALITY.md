# Quality Scorecard

Measured on 2026-09-09 with Python 3.14.7. Config lives in `pyproject.toml`,
`prek.toml`, and `scripts/prek_hooks/`. Re-measure when behavior or tooling changes;
do not treat this snapshot as a live dashboard.

## Enforced gates

| Gate | Setting |
|------|---------|
| Hooks | Native prek; `uv run prek install`, `uv run prek run --all-files` |
| Ruff | Core lint plus curated async, logging, security, suppression, docstring and correctness checks; stable formatter |
| Complexity | Ruff `C901`, ceiling 15; scripts and tests retain their existing exemptions |
| Types | mypy strict on `lib`, `hooks`, `hermes_plugin`; existing untyped-definition/call exceptions remain |
| Runtime types | Beartype on `lib.*`; decoration warnings visible; Pydantic owns model fields |
| Dead code | Vulture, confidence 80 |
| Dependencies | deptry; host imports, PEP 723 scanner dependencies and embedding compatibility pins documented in config |
| Package | check-sdist with injected junk; CI builds and smoke-tests a wheel without dev dependencies |
| Coverage | Branch + subprocess collection; **80% floor**, target 100%; missing lines in terminal and `coverage.json` |
| Fast tests | xdist up to four workers, failed-first, 30-second per-test timeout |
| Hygiene | Native prek built-ins, detect-secrets with reviewed `.secrets.baseline` |
| Custom checks | Exception handling, 400 logical lines, private first-party test imports, architectural boundaries |
| Distribution mirror | `scripts/sync_codex_plugin.py --check` |

## Per-area grades

Coverage is combined statement/branch coverage, including Python subprocesses.
Coverage grade: A ≥90%, B ≥80%, C ≥70%, D below 70%. Type checks pass with the
exceptions above; that does not mean every function is fully annotated. Production
functions pass the Ruff complexity ceiling. Tests run without an embedding service.

| Area | Coverage | Grade | Type / complexity / test health |
|------|---------:|:-----:|--------------------------------|
| Models, config, filters, primer, registration | 90–100% | A | Typed boundaries, passing core tests |
| `lib/vault_index/indexer.py` | 76% | C | External embedding paths remain partly untested |
| `lib/vault_index/cli.py` | 72% | C | Subprocess cases now counted; oversized module |
| `lib/vault_index/vault_files.py` | 85% | B | Boundary and atomic-write regressions pass |
| `hooks/hookslib` | 85–100% | B | Shared behavior tests; small modules |
| Hook entrypoints | 74–100% | C | Subprocess coverage included; protection guard oversized |
| `hermes_plugin/__init__.py` | 77% | C | Stubbed host and subprocess tests; oversized module |
| Overall | 80.47% | B | 422 tests pass, including 13 architecture regressions |

Before subprocess collection, branch coverage measured 66.48%; the earlier 55%
line-coverage floor understated exercised hook behavior. The 80% floor counts
real executed branches without removing hard-to-test code from the denominator.
Use `uv run pytest --no-cov` for a targeted run and `uv run prek run pytest` for
coverage. The latter writes a machine-readable missing-line/branch todo list to
`coverage.json`. Coverage artifacts are ignored by Git.

## Fit decisions and remaining debt

- Keep existing oversized-module exemptions while requiring 400 logical lines
  for ordinary files. Split cohesive behavior when working on those modules.
- Runtime model checks are enabled without suppressing decoration warnings.
  They are not exhaustive deep validation of every container element.
- Broad annotation, pathlib, private-access and API-style rules remain review
  conventions: the adapters use dynamic host APIs and compatibility-sensitive
  path semantics. Current curated lint enforces bug-shaped patterns. Do not
  enable all rules, formatter preview, or unsafe automatic fixes.
- Ruff replaces pyupgrade, Xenon, print/logging detection and the future-import
  rewriting hook. Flynt remains for f-string conversion.
- The keyword-based timeless-comments hook is available but unwired: words such
  as “old” and “new” describe legitimate state transitions in this codebase.
- Network recordings are unnecessary: tests stub the Ollama probe and use local
  fixtures. Live backend validation remains `python scripts/cli_smoke_test.py`.
- Tool-owned configuration validation, TOML parsing, package builds and actual
  tool runs are authoritative; no stale third-party schema overrides them.
- `exclude-newer = "3 days"` delays fresh dependency releases, including dev
  tools. This cooldown is not a dependency safety guarantee.

## Documentation gardening

On changes to defaults, paths, CLI commands or hook behavior, review README,
`CONVENTIONS.md`, and affected docs in the same change. Follow `NOTE:` back-pointers
at code sites. Run `uv run python scripts/sync_codex_plugin.py` after hook/skill
edits. Revisit `docs/ARCHITECTURE.md` twice a year or after package-boundary changes;
verify import claims against the AST gate and dynamic loaders. A recurring review
should run the documented CLI help, compare defaults with code, and propose focused
fixes for drift. No recurring external task is installed by strictify.

Raise the coverage floor when gaps close; never lower it to make a failing gate
pass. Update the table from `coverage.json` and keep type limitations explicit.
