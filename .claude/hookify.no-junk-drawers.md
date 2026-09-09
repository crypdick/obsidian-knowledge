---
name: no-junk-drawers
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: (^|[/\\])(utils|helpers|misc|common|shared|general)\.py$
action: warn
---

This module's name does not describe its purpose. Name it after the domain and
work it handles:

- `billing/compute.py` not `billing/utils.py`
- `auth/tokens.py` not `auth/helpers.py`
- `parsing/csv_reader.py` not `common/misc.py`

Put shared functions in a clearly named package and keep their invariants
there. If only one module uses the functions, keep them in that module.
