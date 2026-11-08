# Design conventions

Keep changes scoped, clear, and easy to maintain. Mechanical rules live in
`pyproject.toml`, `prek.toml`, and `scripts/prek_hooks/`; this document covers
judgment and vault-specific design.

## Ownership and composition

Name modules by purpose, not `utils`, `helpers`, or `common`. Keep single-use
functions with their caller unless they represent a separate concept.
Prefer functions and injected strategies for varying behavior; use protocols
or inheritance when they model a useful interface or genuine subtype.
Avoid registries and abstractions for simple choices.

## Typed boundaries

Parse configuration, paths, and hook payloads into constrained types at the
boundary rather than repeatedly checking raw mappings. Distinguish domain
values whose confusion would cause bugs, especially absolute and vault-relative
paths; ordinary counters and free text need no wrapper.

`NewType` and frozen dataclasses do not validate input. Validate before
construction; use Pydantic for runtime constraints.

## Contracts and documentation

Preserve CLI and hook stdout/stderr protocols. Use structured logging:
`logger.info("message", extra={"key": value})`. Keep suppressions narrow and
explain non-obvious exceptions. Check shared type and path changes against
public behavior.

Update affected documentation with behavior changes. When prose repeats a code
value, keep a `NOTE:` back-pointer at its source so future edits find it.
Keep durable preferences here, not one-task instructions. Automate reliably
detectable rules with existing tooling; reproduce missed violations before
changing their checks.
