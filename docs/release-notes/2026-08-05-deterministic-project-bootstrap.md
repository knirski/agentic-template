# Deterministic project bootstrap

## Compatibility baseline

The activation release, `v2.0.0`, establishes the first generated-project
compatibility baseline for bootstrap schema 1. It supports recognized GitHub
snapshots and Copier-generated projects with one shared deterministic compiler
and managed output inventory.

## Generated-project lifecycle

Generated projects receive the canonical `scripts/validate-project` hook,
durable managed documentation, typed lifecycle commands, and recoverable
planned-path transactions. The lifecycle includes `status`, previews and
mutations for `apply`, `add`, `restore`, and `reconcile`, plus `recover`.

GitHub snapshots have no template-update lineage and cannot reconcile. Copier
updates source inputs; bootstrap reconciliation refreshes derived managed output
after Copier resolves its own conflicts. Adopter-owned product, legal, README,
PRD, and validation-hook files remain outside managed drift repair.

## Operational requirements

- Run `uv run --python 3.14 scripts/validate_repository.py` as the canonical generated-project
  validation boundary.
- Configure the `Project validation` merge check in the default-branch ruleset.
- Keep credentials in GitHub Actions secrets; bootstrap accepts no secrets.
- Use `recover` for interrupted mutations and `restore` for certified managed
  drift repair.
- Run `uv lock` and `uv sync` after generated dependency metadata changes.
