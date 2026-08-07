# Skill Maintenance

The repository-root `AGENTS.md` still applies. These rules govern `.agents/`.

- During scheduled maintenance and before template releases, run
  `npx skills update -p`. Do not update skills automatically during ordinary
  skill use.
- Review every update before accepting it. Preserve local adaptations, and use
  `NOTICE.md` to check upstream sources, licenses, and attribution; update it
  when those facts change.
- For skills not managed by the CLI, reconcile updates directly with the
  upstream source recorded in `NOTICE.md`.
- When reviewing upstream updates to `loop-on-ci` or `pr-review-loop`, first
  compare each repository copy with its upstream copy (`diff -u`) and review
  every hunk before applying it. Treat the repository-root `AGENTS.md` pull-
  request gate as a local contract: preserve substantive feedback from
  automated reviewers, invoke `loop-on-ci` after every pushed review fix and
  before replying to or resolving that feedback, require green PR-attached
  checks before stopping or resuming review work, and re-fetch feedback after
  each CI cycle. If upstream removes or weakens any of these behaviors,
  manually patch around the upstream change while accepting unrelated updates.
  Re-check `NOTICE.md`, `skills-lock.json`, callers, and the path-scoped diff
  after reconciliation; change provenance or lock metadata only when the
  accepted upstream source or version changed.
- Before editing, read the complete `SKILL.md`, required references, callers,
  and current diff.
- Keep frontmatter valid: `name` matches the directory, and `description`
  states concrete triggers rather than summarizing the workflow. Keep paths
  and cross-references current.
- Test changes to triggers, decisions, required steps, safety rules, or output
  with the same fresh-context scenario before and after editing. Use focused
  checks for mechanical-only changes.
- Validate changed examples and Python scripts with the repository's uv-managed checks. The
  repository does not support Bash scripts or ShellCheck.
- Before completion, run `python3.14 tests/test_template_contract.py` and inspect the
  path-scoped diff.
- Never add credentials, local settings, generated agent state, or unrelated
  upstream changes.
