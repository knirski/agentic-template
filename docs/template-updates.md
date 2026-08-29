# Template updates

This document is managed by the Rygor. Put product-specific
project information in `README.md`, and put contribution policy in
`CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`; bootstrap does
not replace it during template updates.

## Generation paths

A Copier-generated project retains update lineage in `.copier-answers.yml`.
Run `copier update`, resolve Copier conflicts, then preview and apply bootstrap
reconciliation:

```console
copier update
uv run --python 3.14 scripts/bootstrap_project.py plan reconcile --target . --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py reconcile --target .
```

A GitHub-generated project is a snapshot. It receives no later template updates
to generated-lifecycle source or bootstrap-managed output and cannot use
`reconcile`. Regeneration obtains a later snapshot.

An adopted project records `ADOPTED` provenance and behaves snapshot-like:
`restore` works against the recorded baseline (installed lifecycle entries are
sourced from the template root and verified against the recorded inventory) and
`reconcile` is permanently refused with `OPERATION_UNAVAILABLE`; source-baseline
repair/regeneration rules match snapshots, and adopted projects cannot gain
Copier reconcile lineage. The managed inventory includes the installed lifecycle
source files (declared lifecycle paths, `.rygor/source-ownership.json`, and the
regular-file `CLAUDE.md` copy), which are drift-fatal; `keep-existing` paths
remain absent from the inventory.

## Managed drift and restore

`status` reports drift in bootstrap-managed files before a mutation. Direct
edits to managed CI, generated dependency metadata, selected capability output,
or these documents are drift. Restore only recorded managed identities:

```console
uv run --python 3.14 scripts/bootstrap_project.py plan restore --target . --path docs/capabilities.md --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py restore --target . --path docs/capabilities.md
```

Restore does not change manifest identity or rewrite adopter-owned files. An
interrupted mutation must be handled with `recover` while its journal remains.

## Cleanup ownership

The manifest records the maintenance status and exact retained paths from the
initial cleanup decision. Retained paths become adopter-owned and remain
outside future template cleanup.

## Scope and unsupported targets

The initial `apply` accepts only an exact scaffold produced through GitHub or
Copier; `adopt` accepts any verified non-bare Git working tree without a project
manifest (empty or populated, dirty or clean) with an explicit `collisions`
declaration (`keep-existing` or `replace` for every collision, including the
lifecycle source set). A manifest-free target that is non-Git, bare,
manifest-bearing, or whose adoption declaration violates the collision policy
(undeclared collisions, declarations naming non-colliding paths, or illegal
`replace` on seed-once legal/provenance paths) is unsupported. Adopted
projects cannot gain Copier reconcile lineage, and seed-once legal/provenance
paths accept only `keep-existing` in v1. Snapshot cleanup is authorized only
when declared paths and recorded identities agree;
`--leave-maintenance-artifacts` retains those paths when cleanup is
intentionally skipped.
