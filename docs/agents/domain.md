# Domain Documentation

Read this document before changing domain terminology, invariants, or architectural decisions.

`docs/prd.md` remains authoritative for product requirements. Domain documents explain the language
and decisions used to implement those requirements; they must not silently expand product scope.

## Default layout

- `CONTEXT.md`: ubiquitous language, invariants, actors, entities, value objects, and boundaries.
- `docs/adr/NNNN-short-title.md`: durable architecture decisions and their trade-offs.

Create these files lazily, only after terminology or a decision has substantive content. For a real
multi-context system, add `CONTEXT-MAP.md` and give each bounded context its own `CONTEXT.md` and ADR
directory. Do not introduce that structure merely because the repository has multiple packages.

Use `oracle-domain-modelling` to sharpen terminology and ADRs. If a domain document conflicts with
the PRD, update the PRD through an explicit product decision or correct the domain document.
