# Project readiness

Generated projects are initially unready by design. Complete these steps before treating the
repository as configured:

1. Replace the marked `docs/prd.md` contract while retaining its required headings and at least one
   `### REQ-001: Title` declaration with a body.
2. Replace the marked README with one project title and non-empty `Setup` and `Validation` sections.
3. Replace the marked `SECURITY.md` and `CONTRIBUTING.md` with the project's policies and guidance.
4. Replace `scripts/validate-project` with the project's own validation commands.
5. Run `uv run --python 3.14 scripts/validate_repository.py` locally and fix every diagnostic.
6. Confirm CI emits the `Project validation` check and the release job depends on it when the
   `semantic-release` capability is selected, including through the `release-automated` or
   `integrated` profile.
7. Configure `Project validation` as a required status check in the default-branch ruleset.

Readiness inspection is structural evidence only. It does not judge requirement quality or the
coverage of adopter-owned validation. It never executes or rewrites the hook. The aggregate command
returns the first failing stage's status; readiness returns 1 for an unready project and 2 for usage
or internal errors.

The bootstrap CLI reports the same findings without running the hook:
`uv run --python 3.14 scripts/bootstrap_project.py status --target .` describes the generation path, scaffold
or installed-project state, cleanup contract, source and managed drift, and any pending journal, and
for unmanaged trees it describes adoptability and names `init` plus `plan adopt` as the next action.
It never executes or rewrites the hook and never exits 1; run `uv run --python 3.14 scripts/validate_repository.py`
for the executed check.

GitHub-generated projects are one-time snapshots. Copier-generated projects retain update lineage;
Copier owns update and conflict behavior. Adopted projects behave like snapshots: `restore` works
against the recorded baseline (installed lifecycle entries are sourced from the template root and
verified against the recorded inventory) and `reconcile` is permanently refused with
`OPERATION_UNAVAILABLE`; source-baseline repair/regeneration rules match snapshots and adopted
projects cannot gain Copier reconcile lineage. An `adopt` install may be performed from any verified
non-bare manifest-free Git working tree (empty or populated, dirty or clean) with an explicit
`collisions` declaration; `keep-existing` paths remain permanently adopter-owned and outside the
managed inventory, while `replace` overwrites only declared paths with the prior `FileState` recorded
in the receipt and seed-once legal/provenance paths accept only `keep-existing`.

Bootstrap-managed operational guidance is installed in `docs/delivery-workflow.md`,
`docs/template-updates.md`, `docs/capabilities.md`, and `docs/github-setup.md`. Keep
product-specific prose in `README.md`, `docs/prd.md`, and other adopter-owned files.
