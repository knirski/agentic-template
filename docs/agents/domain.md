# Domain Documentation

## Layout

- **Mode:** single-context
- **Context map:** not used
- **System ADRs:** `docs/adr/`
- **Context ADRs:** not used; use `docs/adr/` for repository-wide decisions

## Before Domain Work

1. Read `CONTEXT.md` when it exists.
2. Read ADRs relevant to the work.
3. Proceed silently when these documents do not yet exist.

## Ownership

- `CONTEXT.md` records domain language, distinctions, and business invariants.
- `CONTEXT-MAP.md` maps genuinely separate bounded contexts and is not used here.
- ADRs record architectural decisions and trade-offs.
- This file only tells agents how to locate and consume those documents.

Create or update `CONTEXT.md` and ADRs lazily, only when terminology or an architectural decision has
substantive content. Domain documents must not silently expand `docs/prd.md` product scope.
