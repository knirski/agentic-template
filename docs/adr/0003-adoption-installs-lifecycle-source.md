---
status: accepted
---

# Adoption installs lifecycle source as managed inventory

Adopting a brownfield repository must deliver the same template-managed delivery infrastructure that
greenfield generation paths provide, while respecting explicit adopter ownership over colliding content
and without introducing new transaction machinery.

## Context

The template contract requires the generated-lifecycle source files — `AGENTS.md`, every skill under
`.agents/skills/`, `scripts/bootstrap/*.py`, `.rygor/source-ownership.json`, `copier.yml`, and related
generated-lifecycle inputs — to exist in the installed tree, and no generation path renders them as
bootstrap-managed output. GitHub and Copier targets receive them from template packaging before `apply`
runs, and the expected-target contract gate verifies their presence.

The adoption entry condition is any verified non-bare Git working tree without a project manifest
(empty or populated, dirty or clean). Reusing the expected-target gate without installing the lifecycle
set would refuse every real brownfield adoption, contradicting the settled entry condition. Scoping
the gate to skip lifecycle checks would certify adopted projects that lack the template's own delivery
infrastructure and would diverge from the single-compiler, single-gate architecture.

## Decision

Adoption installs the lifecycle source set itself, compiled through the same conflict-aware
partitioning as profile-managed output:

- **Lifecycle install set:** the template root's declared `lifecycle_paths`, plus the template root's
  `.rygor/source-ownership.json`, plus `CLAUDE.md` as a regular file whose bytes are the template's
  `AGENTS.md` content. The template ships `CLAUDE.md` as a symlink to `AGENTS.md`, but the observation
  and transaction layers reject every symlink in a project tree; an installed symlink would make the
  adopted project permanently unobservable.

- **Collision policy:** the full per-path `keep-existing` / `replace` declaration policy applies to
  lifecycle paths. An undeclared collision between a planned lifecycle file and observed content refuses
  the plan naming every offender; `keep-existing` excludes the path from the install and from the
  manifest inventory; `replace` overwrites and records the prior `FileState` in the receipt. Lifecycle
  files are template-owned, not seed-once legal/provenance, so `replace` is allowed; `replace` on
  seed-once legal/provenance paths remains structurally rejected.

- **Post-install ownership:** installed lifecycle files join the manifest's managed inventory. They are
  restore-able and drift-fatal, diverging deliberately from GitHub/Copier projects where the same files
  stay outside the inventory. The source baseline still records them (lifecycle paths are not excluded
  from source-entries collection), so adopted projects keep snapshot-style repair/regeneration diagnosis.
  Keep-existing lifecycle paths remain absent from the inventory and are never drift-fatal or restored.

- **Recorded render parity:** for adopted projects the recorded-render reconstruction sources installed
  lifecycle bytes from the template root and accepts them only when their identities match the recorded
  inventory, so `restore` reproduces managed drift exactly as for other generation paths.

- **No new transaction machinery:** the journaled transaction machine is plan-driven; the plan already
  carries `generation_path=ADOPTED` and the partitioned operations, so no new decision type or machine
  state is introduced.

## Considered alternatives

- **Scope the expected-target contract gate for adopted plans** to skip required-file/skill checks.
  Declined: would install adopted projects missing required source files and diverge from the reused
  gate that the design requires to stay honest.

- **Symlink-create operation for `CLAUDE.md`** with new journal, rollback, and recovery third states.
  Declined: the observation and transaction layers reject every project-tree symlink (an installed
  symlink makes the adopted project permanently unobservable), and the design froze transaction
  machinery as unchanged. Adopted projects carry a regular `CLAUDE.md` file instead; its content stays
  the template's `AGENTS.md` bytes even when `AGENTS.md` itself is declared `keep-existing`.

- **Exclude installed lifecycle files from the managed inventory** (keep them outside, like
  GitHub/Copier). Declined: would leave adopted projects without drift detection for their own
  lifecycle source and would require a new ownership class; absence from the inventory remains the
  ownership record for keep-existing paths only.

- **Prior-file identities in the manifest** for replaced paths. Declined: violates REQ-009's
  prohibition on claims about current tree bytes; receipts retain the evidence instead.

## Consequences

- Adopted projects behave snapshot-like: `restore` works against the recorded baseline,
  `reconcile` is permanently refused, and source-baseline repair/regeneration rules match snapshots.
- An adopter file replaced by a lifecycle install becomes drift-fatal managed state; an adopter edit
  to an installed lifecycle file is managed drift diagnosed by `status`.
- A `keep-existing` declaration on a contract-required skill whose existing bytes lack valid
  frontmatter fails the reused expected-target gate deterministically.
- Adopted projects package `CLAUDE.md` as a regular file copy of `AGENTS.md`, not a symlink; this is
  the accepted divergence from the template's symlink packaging.
- The installation is fully recoverable through the existing journaled machine; keep-existing paths
  remain untouched byte-for-byte across crash/recovery sequences.

## References

- Design `docs/specs/2026-08-23-adopt-lifecycle-verb/design.md` amendments 2026-08-28 (owner-confirmed).
- REQ-007, REQ-009, REQ-010 amendments and `CONTEXT.md` terminology updates in this feature.
- `scripts/bootstrap/bundles.py:compile_adoption_install` — conflict-aware partitioning with lifecycle set.
