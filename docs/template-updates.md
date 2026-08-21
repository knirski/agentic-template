# Template updates

This document is managed by the Agentic Delivery Template. Put product-specific
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
python3 scripts/bootstrap_project.py plan reconcile --target . --out receipt.json
python3 scripts/bootstrap_project.py reconcile --target .
```

A GitHub-generated project is a snapshot. It receives no later template updates
to generated-lifecycle source or bootstrap-managed output and cannot use
`reconcile`. Regeneration obtains a later snapshot.

## Managed drift and restore

`status` reports drift in bootstrap-managed files before a mutation. Direct
edits to managed CI, generated dependency metadata, selected capability output,
or these documents are drift. Restore only recorded managed identities:

```console
python3 scripts/bootstrap_project.py plan restore --target . --path docs/capabilities.md --out receipt.json
python3 scripts/bootstrap_project.py restore --target . --path docs/capabilities.md
```

Restore does not change manifest identity or rewrite adopter-owned files. An
interrupted mutation must be handled with `recover` while its journal remains.

## Cleanup ownership

The manifest records the maintenance status and exact retained paths from the
initial cleanup decision. Retained paths become adopter-owned and remain
outside future template cleanup.

## Scope and unsupported targets

The initial operation accepts only an exact scaffold produced through GitHub or
Copier. A manifest-free target that is not such a scaffold is unsupported.
Snapshot cleanup is authorized only when declared paths and recorded identities
agree; `--leave-maintenance-artifacts` retains those paths when cleanup is
intentionally skipped.
