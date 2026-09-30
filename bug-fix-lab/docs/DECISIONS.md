# DECISIONS

This file records architectural and design decisions for the bug-fix-lab project.

Entries follow the ADR (Architecture Decision Record) format.

---

<!-- Add new ADRs below this line -->

# ADR-002 — Legacy system path resolution

## Status

Accepted

## Context

ADR-001 dictates the use of absolute paths derived from `__file__` for resource loading. However, `legacy_loader.py` strictly prohibits absolute paths, creating a conflict for modules like `module_c.py`.

## Decision

When interfacing with legacy systems that require relative paths, compute the relative path from the current working directory (`os.getcwd()`) to the absolute path derived from `__file__` (using `os.path.relpath`).

## Alternatives

- Modify `legacy_loader.py` to allow absolute paths (rejected to respect legacy security constraints).
- Hardcode the current working directory (rejected as it fails when executed from different locations).

## Consequences

Modules using legacy loaders can reliably locate resources regardless of CWD while satisfying legacy constraints.

## Related Bug

BUG-003

# ADR-001 — Config file path resolution

## Status

Accepted

## Context

Modules were loading `config.json` using relative path `open("config.json")`. This caused `FileNotFoundError` when tests or scripts were executed from outside the `src/` directory (e.g. from project root).

## Decision

Use absolute paths derived from `__file__` to construct file paths for module-specific resources or configurations. Specifically, use `os.path.join(os.path.dirname(__file__), 'config.json')`.

## Alternatives

- Using an environment variable to specify the project root.
- Relying on the caller to change the current working directory.

## Consequences

All future resource loading inside modules must resolve paths relative to `__file__` rather than assuming CWD.

## Related Bug

BUG-002
