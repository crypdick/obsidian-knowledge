# Design conventions

Use these principles in code review. Enforce mechanical rules through
`pyproject.toml`, `prek.toml`, and `scripts/prek_hooks/`.
For design reviews or convention changes, use the shared `coding-conventions`
skill and load only the relevant reference. This document owns vault-specific
choices.

## Name modules by their purpose

Keep shared functions in specifically named owner modules rather than broad
`utils.py`, `helpers.py`, or `common.py` modules. If only one module uses a
function, keep it there unless a separate concept warrants its own owner.

## Semantic types for domain concepts

Give commonly confused domain values distinct types, especially absolute and
vault-relative paths. Apply types at boundaries first:

```python
from typing import NewType

RelPath = NewType("RelPath", str)
AbsPath = NewType("AbsPath", str)
```

Keep ordinary counters, limits, and free text as primitives. Use semantic types
where a mix-up would be a bug, not for every scalar.

## Parse, don't validate

Parse configuration, paths, and hook payloads into constrained types at the
boundary. Pass those values inward instead of repeatedly checking raw mappings.

`NewType` and frozen dataclasses do not validate input. Check values before
constructing them; use Pydantic for runtime constraints. Add semantic types when
static checking must distinguish otherwise identical fields.

## Composition over inheritance

Prefer small functions and injected strategies for behavior that varies, such
as filters or memory backends. Use a `Protocol` when a shared interface helps.
Framework base classes, enums, exceptions, and genuine subtype relationships
can use inheritance. Do not build a registry for a simple two-case switch.

## Keep code and its documentation coupled

When prose repeats a code value, add a `NOTE:` comment at the code site naming
the document and section. Update both in the same change. Follow existing
back-pointers when changing defaults, paths, limits, or behavior.

## Review and enforcement

Use `logger.info("message", extra={"key": value})` for structured events.
CLI and hook stdout/stderr are protocol boundaries; keep lint suppressions
narrow and explain them. Verify annotation and path changes against public
behavior tests.

Retain coding preferences when the user intends them to apply to future work.
Keep judgment-based guidance here. Prefer an existing tool setting or repair an
existing prek check when reliable detection is possible. Reproduce a missed
violation before changing its check. A one-task instruction does not establish
permanent policy.
