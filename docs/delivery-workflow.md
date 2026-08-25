# Delivery workflow

This document is managed by the Rygor. Put product-specific
setup and validation details in `README.md`, and put contributor process in
`CONTRIBUTING.md`.

The adopter-owned executable hook is `scripts/validate-project`.

## Canonical validation

Run the single project boundary from the repository root:

```console
uv run --python 3.14 scripts/validate_repository.py
```

It checks the template contract, mechanical project readiness, and the
adopter-owned project validation hook in that order. A bootstrap installation
can still need project content or can report a hook failure.

The lifecycle is inspectable and recoverable:

```console
uv run --python 3.14 scripts/bootstrap_project.py status --target .
uv run --python 3.14 scripts/bootstrap_project.py plan apply --bundle ./bundle --target . --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py apply --bundle ./bundle --target .
uv run --python 3.14 scripts/bootstrap_project.py recover --target .
```

Recovery never re-runs the project validation hook. Hook-created files and
external effects are outside the bootstrap transaction.

## CI, release, and merge gates

Managed CI calls the adopter-owned project-validation workflow with read-only
repository access and no caller secrets. Extend that reusable workflow for
product checks without editing managed CI.

When the `semantic-release` capability is selected, including through the
`release-automated` or `integrated` profile, its release job waits for Project
validation and every selected managed check. The release gate is a workflow
dependency; the merge gate is the administrator-configured required status check
in the default-branch ruleset. Configure both deliberately.

Projects that need stable line endings may add this adopter-owned rule:

```text
* text=auto eol=lf
```

## Review flow

Preview a mutating lifecycle command, inspect its receipt and planned paths, then
apply only the reviewed plan. Keep product checks in the adopter-owned workflow;
the managed workflow remains the template-owned delivery gate.
