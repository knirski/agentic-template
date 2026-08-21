# GitHub setup

This document is managed by the Agentic Delivery Template. Put project-specific
setup in `README.md`, and put contributor and security process in
`CONTRIBUTING.md`.

The adopter-owned validation hook is `scripts/validate-project`.

## Repository settings

Managed CI calls the adopter-owned Project validation workflow without passing
secrets and with `contents: read`. Keep product checks inside that reusable
workflow. Configure `Project validation` as a required status check in the
default-branch ruleset; bootstrap does not change repository settings.

The release gate is the release workflow's dependency on Project validation
and selected checks. The merge gate is the administrator's ruleset requirement.

## Capability secrets and preflights

Selected integrations may require these repository Actions secrets:

- `GEMINI_API_KEY` for the PR Agent Gemini capability;
- `CACHIX_AUTH_TOKEN` for Cachix publishing.

The workflows use a read-only availability preflight before a privileged job.
It reports exactly two states:

- **Available:** the secret resolves non-empty and the privileged job may
  continue when the event is trusted.
- **Unavailable in this run:** the job is skipped with constant guidance. This
  does not prove that the secret is unconfigured; common causes include a fork
  pull request, a Dependabot run, or restricted Actions policy.

Gemini remains skipped with guidance until the secret is available. Cachix
publishing may be skipped while Nix validation continues uncached; an invalid
configured cache remains an activation failure.

Never commit secret values or place them in the bootstrap bundle or manifest.
