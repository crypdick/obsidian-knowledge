# Design Conventions

Judgment-based design principles for obsidian-knowledge — not mechanically-checkable
rules. A linter can't decide whether a given `str` is "really" a domain concept or
whether some inheritance is genuinely the right call; that takes reading the code and
applying taste. This doc is where those principles live so both humans and coding agents
apply them consistently. Enforce them with judgment; the caveats matter.

---

## Semantic types for domain concepts

Give domain values a distinct type instead of a bare primitive. `NewType` is zero-cost
at runtime and catches category errors at type-check time.

This repo's most dangerous ambiguity is **relative-vs-absolute paths**. `vault_index`
juggles both — `indexer._abs_to_rel(abs_path: str) -> str`, `filters.score_path(path:
str, ...)`, `hermes_plugin._resolve_tool_path(raw_path, workdir)` — and every one is a
bare `str`. Passing an absolute path where a vault-relative one is expected is a silent
bug today; with distinct types it's a type error:

```python
from typing import NewType

RelPath = NewType("RelPath", str)   # vault-relative, e.g. "wiki/systems/index.md"
AbsPath = NewType("AbsPath", str)   # filesystem-absolute

def score_path(path: RelPath, config: VaultIndexConfig) -> float: ...
def _abs_to_rel(self, abs_path: AbsPath) -> RelPath: ...
```

Also consider `Query`, and `VaultRoot`/`PluginRoot` (both threaded as bare `str` through
`hermes_plugin`). Apply this at boundaries first, where a mix-up is most costly.
**Caveat:** a genuinely raw primitive (a loop counter, a `top_k` limit, free-text
content) doesn't need wrapping. This is about intent, not blanket wrapping of every
scalar.

---

## Parse, don't validate

Coerce unstructured data into constrained types at the boundary, so downstream code never
re-validates. Don't check a condition and then discard the proof.

The boundaries here are the config layer (`VaultIndexConfig`, `IndexFilter`,
`DigestFilter`), path resolution (`_resolve_tool_path` returns `Path | None` — good: it
parses into an optional typed result), and hook payloads read from the harness. Parse the
raw hook JSON / config dict into a typed structure once at the edge, then pass the typed
value inward — don't re-check `"key" in payload` deep in the call stack.

```python
# AVOID: validate and throw the evidence away
def handle(payload: dict) -> None:
    if "tool_input" not in payload:
        return                              # checked, then discarded

# PREFER: parse into a type that carries the proof
@dataclass(frozen=True)
class HookEvent:
    path: RelPath                           # if it constructed, it's valid
```

**Caveat on Pydantic field validators:** a `@field_validator` runs at runtime but does
*not* change the static type — a validator confirming a `str` is well-formed still leaves
it typed `str`. To make Pydantic validation *real parsing*, bind the proven value to a
`NewType` via `Annotated[str, AfterValidator(...)]`, or wrap the model's output at the
boundary. A plain validator is a check-and-discard, not a parse.

---

## Composition over inheritance

Build behavior out of small, focused parts plus a combiner, rather than a class hierarchy
that knows about every variant. For swappable behavior (index filters, memory backends,
digest strategies), inject a strategy that satisfies a `Protocol` instead of subclassing:

```python
from typing import Protocol

class PathFilter(Protocol):
    def keep(self, path: RelPath) -> bool: ...
```

The `filters.py` split (`score_path`, `path_passes` taking a config/filter object) is
already function-composition in this spirit — prefer extending it with new small
functions over a growing `if kind == ...` ladder.

**Caveat:** inheritance is sometimes right — framework base classes, `Enum`, `Exception`,
and genuine is-a relationships with no combinatorial variants. Reach for composition when
a hierarchy starts to multiply or a constructor sprouts flags. This repo is small; don't
over-abstract a two-case switch into a plugin registry.

---

## Keep code and its documentation coupled

When a concrete value in code is *also* stated in prose, the two drift out of sync unless
they reference each other. This repo has real instances: the memory-index char cap (the
knowledge-base index is "capped at 6000 chars"), the `AGENTS.md` command lists, and the
vault-path allowlists in `hermes_plugin`.

```python
# NOTE: keep in sync with AGENTS.md § "capped at 6000 chars" if you change this.
INDEX_CHAR_CAP = 6000
```

- **Introducing a documented value:** add a `NOTE:` comment at the code site naming the
  doc file and section.
- **Changing a value that has a `NOTE:`:** read the referenced doc and update it in the
  same change. Don't merge code that silently contradicts its own docs.
