# Project readiness

Generated projects are initially unready by design. Complete these steps before treating the
repository as configured:

1. Replace the marked `docs/prd.md` contract while retaining its required headings and at least one
   `### REQ-###: Title` declaration with a body.
2. Replace the marked README with one project title and non-empty `Setup` and `Validation` sections.
3. Replace `scripts/validate-project.py` with the project's own validation commands.
4. Run `python3 scripts/validate-repository.py` locally and fix every diagnostic.
5. Confirm CI emits the `Project validation` check and the release job depends on it.
6. Configure `Project validation` as a required status check in the default-branch ruleset.

Readiness inspection is structural evidence only. It does not judge requirement quality or the
coverage of adopter-owned validation. It never executes or rewrites the hook. The aggregate command
returns the first failing stage's status; readiness returns 1 for an unready project and 2 for usage
or internal errors.

GitHub template repositories are one-time snapshots. Copier-generated projects retain update lineage;
Copier owns update and conflict behavior.
