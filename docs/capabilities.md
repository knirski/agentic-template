# Capabilities

This document is managed by the Rygor. Put product-specific
architecture and operating guidance in `README.md`, and put contribution
process in `CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`.

## Recorded selection

The creation-time profile is frozen in the project manifest. Later additions
are append-only and do not replace the original profile. The manifest records
the frozen profile, explicit additions, effective dependency closure, and
normalized non-secret settings.

## Selected capability details

Capability definitions declare dependencies, artifacts, workflow contributions,
documentation fragments, runtime metadata, and external activation guidance.
Unselected capability artifacts and jobs are absent. The same profile/capability
matrix installs identically through `apply` on a recognized scaffold and through
`adopt` on a brownfield tree; the collision declaration is the only
brownfield-specific input. Bootstrap does not install packages, create credentials, or
certify external activation.

After generated dependency metadata changes, the adopter owns the follow-up
`uv lock` and `uv sync` steps. When the append-only capability-addition
transition is available, prepare an `additions.json` input using the additions
schema and preview it with:

```console
uv run --python 3.14 scripts/bootstrap_project.py plan add --target . --input additions.json --out receipt.json
```

Apply only the reviewed plan. Capability removal, replacement, and
reconfiguration are not available in this lifecycle.
