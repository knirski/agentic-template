# Capabilities

This document is managed by the Agentic Delivery Template. Put product-specific
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
Unselected capability artifacts and jobs are absent. Bootstrap does not install
packages, create credentials, or certify external activation.

After generated dependency metadata changes, the adopter owns the follow-up
`uv lock` and `uv sync` steps. When the append-only capability-addition
transition is available, prepare an `additions.json` input using the additions
schema and preview it with:

```console
python3 scripts/bootstrap_project.py plan add --target . --input additions.json --out receipt.json
```

Apply only the reviewed plan. Capability removal, replacement, and
reconfiguration are not available in this lifecycle.
