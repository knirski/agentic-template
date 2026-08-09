# Issue Tracker

## Tracker

- **Provider:** GitHub Issues
- **Location:** `knirski/agentic-template`
- **Tool or procedure:** GitHub web workflow or `gh issue`
- **Mirror Spec-backed tasks:** no

## Authority

- `docs/prd.md` owns product scope and acceptance criteria.
- GitHub Issues own backlog intent, discussion, and cross-PR status.
- For Spec-backed work, `plan.json` owns task decomposition and dependencies. Each task's `execution`
  field either stores inline task state or points that task to the configured tracker issue.
- Pull requests own the reviewable implementation and validation evidence.

Do not duplicate a Spec-backed task graph in issue checklists. Link the issue to the spec and PR, and
summarize externally meaningful progress instead.

## Operations

- **Create:** Create an issue with `gh issue create` or through GitHub.
- **Read:** Use `gh issue view` or the GitHub web interface.
- **Update:** Add comments or change status through GitHub.
- **Complete:** Close the issue through GitHub, usually with a PR closing keyword when acceptance
  criteria are fully satisfied.
- **Dependencies:** Describe blockers and link related issues or PRs.

## Status Mapping

| Plan state | Tracker state |
|------------|---------------|
| Ready | Open |
| In progress | Open |
| Blocked | Open, with a blocker comment |
| Complete | Closed |

## Constraints

- Issues must state the problem or outcome, relevant constraints, acceptance criteria, and links to
  affected PRD requirements or decisions.
- Use labels only when they already exist and improve queries; the workflow must not depend on an
  undeclared label taxonomy.
- Keep follow-up work as separate issues rather than silently expanding a PR.
- Do not store credentials, tokens, or other secrets in this document.
