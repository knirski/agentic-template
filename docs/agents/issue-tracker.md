# Issue Tracker

GitHub Issues is the default tracker for user-visible work, defects, and follow-up decisions.

## Authority

- `docs/prd.md` owns product scope and acceptance criteria.
- GitHub Issues own backlog intent, discussion, and cross-PR status.
- For Spec-backed work, `plan.json` owns task decomposition, dependencies, and execution state.
- Pull requests own the reviewable implementation and validation evidence.

Do not duplicate a Spec-backed task graph in issue checklists. Link the issue to the spec and PR, and
summarize externally meaningful progress instead.

## Issue quality

An actionable issue states the problem or outcome, relevant constraints, acceptance criteria, and
links to affected PRD requirements or decisions. Use labels only when they already exist and improve
queries; the workflow must not depend on an undeclared label taxonomy.

Close issues through PR keywords only when the PR fully satisfies their acceptance criteria. Keep
follow-up work as separate issues rather than silently expanding a PR.
