---
status: accepted
---

# Functional core, domain model, and ownership boundary

The bootstrap compiler uses one functional core for both supported generation paths and a thin
imperative shell for filesystem, Git, process, environment, and terminal effects. The core accepts
explicit immutable values and returns typed results; it does not import shell adapters or observe
ambient state. Shell adapters perform bounded observation, invoke pure decisions and rendering, and
apply the returned operation plan.

## Decision

The domain is divided into four ownership classes:

| Class | Meaning | Update authority |
| --- | --- | --- |
| Generated-lifecycle source | Fingerprinted template-owned compiler inputs, definitions, validators, policy, and durable adopter documentation | Copier may update source; bootstrap reconciles derived output only on the Copier path |
| Bootstrap-managed output | Reproducible derived files represented in the managed inventory | Bootstrap owns rendering, drift detection, restore, and reconciliation |
| Seed-once adopter output | Product, licensing, and legal/provenance files initialized by bootstrap but thereafter owned by the adopter | The adopter owns edits; bootstrap never rewrites or makes them drift-fatal |
| Snapshot-cleanup input | Finite source-only files that a verified GitHub snapshot may remove when content and ownership agree | Bootstrap consumes the cleanup contract once; disagreement authorizes no deletion |

These classes are disjoint. A path may not be both Copier-managed and bootstrap-managed, both
managed output and seed-once output, or both a cleanup target and retained generated-lifecycle
source. The fingerprinted `source-ownership.json` declaration is the authority for the two source
classes; the ephemeral cleanup inventory supplies expected bytes and modes but never expands the
deletion set.

The domain language in `CONTEXT.md` is authoritative for implementation names. In particular,
project readiness is a point-in-time mechanical result plus one adopter-hook result, while bootstrap
installation is the durable transaction outcome. Capability selection, capability activation,
Copier update, and capability reconciliation are separate transitions.

## Consequences

- Pure functions can be tested without filesystem, Git, process, environment, or terminal access.
- Invalid combinations are rejected by constructors and closed sum types before policy evaluation.
- The same resolver, renderer, readiness rules, and transition algebra serve GitHub snapshots and
  Copier-generated projects; their shells differ only in observed provenance and allowed lifecycle.
- Adopter-owned legal text and product files are preserved without making routine edits drift-fatal.
- A source or ownership change is visible through deterministic identities and compatibility rules,
  rather than through hidden mutable state.

## Non-goals and constraints

This decision does not certify legal validity, make the adopter hook safe, or provide atomic
multi-file visibility. Transactions cover only paths declared by the typed operation plan and never
roll back adopter-hook effects. The compiler does not infer a licence, embed secrets, or perform
external capability activation.

The architecture gate is paired with the licensing/provenance audit in
`docs/licensing-provenance-audit.md`. That audit must be accepted before any implementation writes
licence files or renders legal content.
