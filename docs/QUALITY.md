# Quality checks

Measured on 2026-09-09 with Python 3.14.7. Config lives in `pyproject.toml`,
`prek.toml`, and `scripts/prek_hooks/`. Re-measure when behavior or tooling changes;
do not treat this snapshot as a live dashboard.

## Enforced gates

| Gate | Setting |
|------|---------|
| Hooks | Native prek; `uv run prek install`, `uv run prek run --all-files` |
| Ruff | Core lint plus curated async, logging, security, suppression, docstring, and correctness checks; stable formatter |
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
documented exceptions; that does not mean every function is fully annotated. Production
functions pass the Ruff complexity ceiling. Tests run without an embedding service.

| Area | Coverage | Grade | Type / complexity / test health |
|------|---------:|:-----:|--------------------------------|
| Models, config, filters, primer, registration | 90–100% | A | Typed boundaries, passing core tests |
| `lib/vault_index/indexer.py` | 76% | C | External embedding paths remain partly untested |
| `lib/vault_index/cli.py` | 72% | C | Subprocess coverage; oversized module |
| `lib/vault_index/vault_files.py` | 85% | B | Boundary and atomic-write regressions pass |
| `hooks/hookslib` | 85–100% | B | Shared behavior tests; small modules |
| Hook entrypoints | 74–100% | C | Subprocess coverage included; protection guard oversized |
| `hermes_plugin/__init__.py` | 77% | C | Stubbed host and subprocess tests; oversized module |
| Overall | 80.47% | B | 422 tests pass, including 13 architecture regressions |

Use `uv run pytest --no-cov` for targeted tests and `uv run prek run pytest`
for coverage. The latter writes missing lines and branches to `coverage.json`,
which Git ignores. Raise the coverage floor as gaps close; do not lower it to
pass a failing check.

## Fit decisions and remaining debt

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
