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
