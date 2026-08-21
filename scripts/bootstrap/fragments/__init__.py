"""Static durable-adopter documentation fragment bodies.

The fragments are source-owned compiler inputs.  They contain only declarative
Markdown and render markers; the rendering boundary supplies all project-
specific values explicitly.
"""

from typing import Final

PROJECT_VALIDATION_WORKFLOW: Final[bytes] = b"""\
name: Project validation

on:
  workflow_call:

permissions:
  contents: read

jobs:
  validate:
    name: Project validation
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Set up uv and Python 3.14
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.12.1"
          python-version: "3.14"
          enable-cache: true
      - name: Validate repository
        if: github.repository != 'knirski/agentic-template'
        run: uv run --python 3.14 scripts/validate_repository.py
"""

DELIVERY_WORKFLOW: Final[bytes] = b"""\
# Delivery workflow

This document is managed by the Agentic Delivery Template. Put product-specific
setup and validation details in `README.md`, and put contributor process in
`CONTRIBUTING.md`.

## Canonical validation

Run the single project boundary from the repository root:

```console
python3 scripts/validate_repository.py
```

It checks the template contract, mechanical project readiness, and the
adopter-owned project validation hook in that order. Mechanical installation
success and project readiness are different outcomes: a bootstrap installation
can still need project content or can report a hook failure.

The adopter-owned executable hook is `scripts/validate-project`.

The bootstrap lifecycle is inspectable and recoverable:

```console
python3 scripts/bootstrap_project.py status --target .
python3 scripts/bootstrap_project.py plan apply --bundle ./bundle --target . --out receipt.json
python3 scripts/bootstrap_project.py apply --bundle ./bundle --target .
python3 scripts/bootstrap_project.py recover --target .
```

Recovery never re-runs the project validation hook. Hook-created files and
external effects are outside the bootstrap transaction.

## CI, release, and merge gates

The managed CI workflow calls the adopter-owned project-validation workflow
with read-only repository access and no caller secrets. Extend that reusable
workflow for product checks without editing managed CI.

When automated release capability is selected, its release job waits for
Project validation and every selected managed check. The release gate is a
workflow dependency; the merge gate is the administrator-configured required
status check in the default-branch ruleset. Configure both deliberately.

Projects that need stable line endings may add this adopter-owned `.gitattributes`
rule:

```text
* text=auto eol=lf
```

## Review flow

Preview a mutating lifecycle command, inspect its receipt and planned paths, then
apply only the reviewed plan. Keep product checks in the adopter-owned workflow;
the managed workflow remains the template-owned delivery gate.
"""

TEMPLATE_UPDATES: Final[bytes] = b"""\
# Template updates

This document is managed by the Agentic Delivery Template. Put product-specific
project information in `README.md`, and put contribution policy in
`CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`; bootstrap does
not replace it during template updates.

## Generation paths

A Copier-generated project retains update lineage in `.copier-answers.yml`.
Run `copier update` to receive a new generated-lifecycle source, resolve any
Copier conflicts, then run the bootstrap reconciliation preview and apply it:

```console
copier update
python3 scripts/bootstrap_project.py plan reconcile --target . --out receipt.json
python3 scripts/bootstrap_project.py reconcile --target .
```

A GitHub-generated project is a snapshot. It receives no later template updates
to generated-lifecycle source or bootstrap-managed output and cannot use
`reconcile`. Regeneration is the supported way to obtain a later snapshot.

This project uses the `agentic-template:value:generation-path` generation path.

## Managed drift and restore

`status` reports drift in bootstrap-managed files before a mutation. Direct
edits to managed CI, generated dependency metadata, selected capability output,
or these documents are drift. Restore only recorded managed identities:

```console
python3 scripts/bootstrap_project.py plan restore --target . --path docs/capabilities.md --out receipt.json
python3 scripts/bootstrap_project.py restore --target . --path docs/capabilities.md
```

Restore does not change the manifest identity or rewrite adopter-owned files.
An interrupted mutation must be handled with `recover`; do not delete its
transaction evidence while a journal is pending.

## Scope and unsupported targets

The initial operation accepts only an exact scaffold produced through GitHub or
Copier. A manifest-free target that is not such a scaffold is unsupported.
Snapshot cleanup is authorized only when its declared paths and recorded
identities agree; `--leave-maintenance-artifacts` retains those paths when
cleanup is intentionally skipped.

## Cleanup ownership

- Maintenance status: `agentic-template:value:maintenance-status`
- Retained maintenance paths:

  ```text
  agentic-template:value:retained-paths
  ```

Retained paths become adopter-owned and remain outside future template cleanup.
"""

CAPABILITIES: Final[bytes] = b"""\
# Capabilities

This document is managed by the Agentic Delivery Template. Put product-specific
architecture and operating guidance in `README.md`, and put contribution
process in `CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`.

## Recorded selection

The creation-time profile is frozen in the project manifest. Later additions
are append-only and do not re-expand or replace the original profile.

- Profile: `agentic-template:value:profile-id`
- Frozen profile selection: `agentic-template:value:profile-frozen`
- Explicit additions: `agentic-template:value:additions`
- Effective dependency closure: `agentic-template:value:effective`

## Selected capability details

The following details are derived from the selected declarative definitions.
Unselected capability artifacts and jobs are absent.

agentic-template:value:capability-summary

Capability settings are normalized, displayable, and non-secret. Bootstrap does
not install packages, create credentials, or certify external activation.
After generated dependency metadata changes, the adopter owns the follow-up
`uv lock` and `uv sync` steps.

When the append-only capability-addition transition is available, prepare an
`additions.json` input using the additions schema and preview the change:

```console
python3 scripts/bootstrap_project.py plan add --target . --input additions.json --out receipt.json
```

Apply only the reviewed plan. Capability removal, replacement, and
reconfiguration are not available in this lifecycle.
"""

GITHUB_SETUP: Final[bytes] = b"""\
# GitHub setup

This document is managed by the Agentic Delivery Template. Put project-specific
setup in `README.md`, and put contributor and security process in
`CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`.

## Repository settings

The managed CI workflow calls the adopter-owned Project validation workflow
without passing secrets and with `contents: read`. Keep product checks inside
that reusable workflow. Configure `Project validation` as a required status
check in the default-branch ruleset; bootstrap does not change repository
settings for you.

The release gate is the release workflow's `needs` dependency on Project
validation and selected checks. The merge gate is the administrator's ruleset
requirement. A successful release gate does not configure merge protection.

## Capability secrets and preflights

Selected integrations append their required secret and preflight guidance
below. Each selected capability uses a read-only availability preflight before
any privileged job. It reports **Available** or **Unavailable in this run**;
the latter can result from a fork pull request, a Dependabot run, or restricted
Actions policy and does not prove that the secret is unconfigured.

Never commit secret values or place them in the bootstrap bundle or manifest.
"""

CACHIX_GITHUB_SETUP: Final[bytes] = b"""\

### Cachix publishing

The `cachix-publish` capability requires the repository Actions secret
`CACHIX_AUTH_TOKEN`. When **Available**, the publish job may continue for a
trusted event. When **Unavailable in this run**, Cachix publishing is skipped
while Nix validation continues uncached; an invalid configured cache remains
an activation failure.
"""

PR_AGENT_GITHUB_SETUP: Final[bytes] = b"""\

### PR Agent Gemini

The `pr-agent-gemini` capability requires the repository Actions secret
`GEMINI_API_KEY`. When **Available**, the review jobs may continue for a trusted
event. When **Unavailable in this run**, the jobs are skipped with guidance.
"""
