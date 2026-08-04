# Pull Request

## Summary

Describe the outcome and why this approach was chosen.

## Tracking

Link relevant issues, PRD requirements, specs, or ADRs. Use `Closes #N` only when this PR fully
satisfies that issue's acceptance criteria. Write `N/A` when no tracking artifact is needed.

## Validation

List the exact commands or checks run and their results.

## Risk and recovery

Describe behavior, data, security, compatibility, filesystem, or operational risks and the recovery
path. Write `N/A` for changes without such risk.

## Review checklist

- [ ] Scope matches `docs/prd.md` and linked tracking artifacts.
- [ ] Tests cover changed behavior, including relevant failure paths.
- [ ] Documentation reflects user-visible or operational changes.
- [ ] Generated-project changes preserve the `Project validation` check and readiness contract.
- [ ] No secrets, local settings, debug artifacts, or generated agent state are included.
- [ ] CI is green for the latest commit.
