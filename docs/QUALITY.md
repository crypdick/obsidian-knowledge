# Quality Scorecard

A snapshot of code-health per area, plus the enforcement that keeps it there.
Update the grades when a number moves materially; treat the floors as ratchets
(raise, never lower). Enforcement config lives in `pyproject.toml`,
`.pre-commit-config.yaml`, and `scripts/pre_commit_hooks/`.

## Baseline gates (all green, enforced in pre-commit + CI)

| Gate | Setting |
|------|---------|
| ruff lint | `E,W,F,I,B,UP,C4,SIM,RUF` (+ format), via the project's pinned ruff |
| mypy | `--strict` on `lib` / `hooks` / `hermes_plugin` |
| beartype | runtime type checks across `lib.*` |
| complexity (xenon) | grade C: `--max-average C --max-modules C --max-absolute C` |
| dead code (vulture) | `min_confidence = 80` |
| coverage floor | `fail_under = 55` (see caveat below) |
| secrets | `detect-secrets` against `.secrets.baseline` |
| custom taste hooks | exception-handling, print, file-length, private-test-imports, future-annotations |

## Per-area grades

Coverage is the in-process number from `pytest --cov`. Types = clean under
mypy --strict + beartype. Complexity = xenon rank.

| Area | Coverage | Types | Complexity | Notes |
|------|:--------:|:-----:|:----------:|-------|
| `lib/vault_index` (models, config, filters, primer) | 94–100% | ✅ | A/B | Well-tested pure core. |
| `lib/vault_index/indexer.py` | 76% | ✅ | ≤C | memweave/Ollama paths partly need a live backend. |
| `lib/vault_index/cli.py` | 47% | ✅ | ≤C | Large surface; subcommands run via subprocess. **>400 lines** (grandfathered). |
| `hooks/hookslib/*` | 61–96% | ✅ | ≤C | Shared hook logic; the tested core of the hook layer. |
| `hooks/*` entrypoints | 0–36% | ✅ | ≤C | Thin; **tested via subprocess** so in-process cov reads low (see caveat). |
| `hooks/protect-vault.py` | 36% | ✅ | ≤C (was E) | `destructive_vault_ops` decomposed into per-op checks. **>400 lines** (grandfathered). |
| `hermes_plugin/__init__.py` | 80% | ✅ | ≤C | Subprocess bridge to `lib`. **>400 lines** (grandfathered). |

### Coverage caveat

Total in-process coverage is ~56%, but that understates reality: the hook
entrypoints (`doctor.py`, `recall-init.py`, `enforce-conventions.py`, …) are
exercised by tests that spawn them as **subprocesses**, whose lines the parent
coverage run cannot see. The retrieval core (`lib/`, `hookslib/`) sits at
76–100%. Raising the floor meaningfully means either adding in-process tests for
the entrypoints or wiring subprocess coverage (`COVERAGE_PROCESS_START`).

## Tracked debt (deliberate, not accidental)

- **Oversized modules** (`# allow: file-length`): `hermes_plugin/__init__.py` (~764
  lines), `lib/vault_index/cli.py` (~487), `hooks/protect-vault.py` (~460),
  `tests/test_hermes_provider.py` (~470). Decompose when next touched
  (e.g. split `cli.py` subcommands into a `cli/` package).
- **Coverage floor at 55%**, held down by subprocess-tested entrypoints — see above.

## Deliberately not enforced (fit-before-force)

- **`check-timeless-comments`** — set aside: on this codebase it fires mostly on
  ordinary words ("new", "old", "switch") in prose comments (~35 hits, mostly
  false positives). Not wired.
- **pyupgrade** — omitted as redundant; ruff's `UP` rules already modernize syntax.
- **RUF067 / RUF003** — ignored: `hermes_plugin/__init__.py` is an entrypoint
  module by design, and em-dashes in prose comments are intentional.

## Maintaining this file

When you close coverage gaps, raise `fail_under` in `pyproject.toml` to the new
floor. When you split an oversized module, drop its `# allow: file-length`. When a
new area lands, add a row. Keep grades honest — this scorecard is only useful if it
reflects reality.
