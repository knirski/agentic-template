# Agent Instructions

## Authority

- Follow the user's current request and this file.
- Treat `docs/prd.md` as the source of truth for product scope, behavior, and acceptance criteria.
- Surface conflicts instead of silently choosing between requirements.
- Preserve user changes and keep work within the requested scope.

## Delivery workflow

Use `atelier-orchestrator` at the start of development work. It selects an Inline Plan for bounded
changes or a Spec-backed Plan when durable discovery, design, or coordination artifacts are needed.
Do not implement a change before the selected planning workflow reaches its approval gate.

Read `docs/agents/issue-tracker.md` when issue tracking is relevant. Read
`docs/agents/domain.md` before changing domain terminology, invariants, or architecture decisions.
Load only the language, framework, and domain skills relevant to the current task.

Before completion, run repository-defined formatting, linting, tests, builds, and
`verification-before-completion`. Use `code-review` for substantive changes and `code-commit` for
reviewable conventional commits. Creating a PR and merging remain explicit user-authorized actions.

Generated projects use `python3 scripts/validate_repository.py` as their canonical validation
boundary. The template source uses the readiness and generation-path fixture suites.

## Python implementation guidance

- Use the repository's modern Python toolchain: manage dependencies with `uv`, format and lint
  with Ruff, type-check with `ty`, and run tests through `uv run`.
- Prefer current Python features supported by the repository's `requires-python` floor, explicit
  type annotations, small functions, immutable values, and transformations that are easy to test.
- Where practical, structure Python commands as a functional core with an imperative shell: keep
  policy, parsing, validation, and state transitions pure and deterministic; keep filesystem,
  process, environment, clock, network, and terminal effects at thin, explicit boundaries.
- Prefer explicit typed outcomes and returned diagnostics over hidden mutation, ambient global
  state, or exceptions used for ordinary control flow. Keep command entrypoints responsible for
  argument parsing, effect orchestration, presentation, and exit codes.
- Apply these principles pragmatically, not religiously. Do not add wrappers, abstractions,
  functional-programming ceremony, or artificial immutability when a direct standard-library
  implementation is clearer, safer, or materially simpler. Preserve existing contracts and favor
  the smallest design that makes behavior deterministic and testable.
- For standalone dependency-bearing scripts, use PEP 723 inline metadata. For project code, keep
  dependencies in `pyproject.toml` and `uv.lock`, using `uv add`/`uv remove` rather than manual
  environment or requirements-file management.

Use `spec-finish` for completion of Spec-backed Plans. It coordinates the post-implementation
workflow, while `verification-before-completion` remains the universal evidence gate for completion
claims, commits, and PRs, including work that does not use `spec-finish`.

## Pull-request gate

After a PR is created, use this state machine until the PR has green CI and no approved actionable
feedback remains:

1. Run `loop-on-ci` until all PR-attached checks are green.
2. Immediately run `pr-review-loop` and triage all human and automated-review feedback.
3. Present the complete triage and wait for approval.
4. Process approved MUST_FIX items before approved SHOULD_FIX items.
5. After every review-fix push, return to `loop-on-ci`; resume `pr-review-loop` only after CI is green.
6. Re-fetch feedback after CI because automated reviewers may comment on the new commit.

Triage approval authorizes scoped commits, pushes, replies, PR-body corrections, and thread
resolution for MUST_FIX and SHOULD_FIX items; those classifications are auto-approved after triage.
It does not authorize merging, unrelated
changes, or processing PARK and OUT_OF_SCOPE items. Ask one focused question for
NEEDS_CLARIFICATION items and leave those threads open.

## Safety

- Never commit secrets, credentials, local settings, or generated agent state.
- Do not bypass hooks, tests, required checks, or branch protections.
- Avoid destructive operations unless the user explicitly requests them and the exact target has
  been verified.
- Do not weaken tests or validation merely to obtain a green result.
