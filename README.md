# Agentic Delivery Template

<!-- agentic-template:placeholder:readme -->

A language-neutral GitHub repository template for planning, implementing, validating, and reviewing
software changes with coding agents.

## Start a project

1. Select **Use this template** on GitHub.
2. Replace the marked contract in `docs/prd.md` with the project's product requirements.
3. Replace this marked README with the project title, setup, and validation instructions.
4. Replace `scripts/validate_project.py` with the project's formatting, linting, tests, and build checks.
5. Run `python3.14 scripts/validate_repository.py` and address every readiness diagnostic.
6. Require the `Project validation` check in the default-branch ruleset.

The template is maintained with [Copier](https://copier.readthedocs.io/):

```console
uv tool install copier
copier copy https://github.com/knirski/agentic-template.git ./my-project
cd ./my-project
copier update
```

The generated project records its template source and answers in `.copier-answers.yml`. Copier
uses semantic-release Git tags to identify template versions, preserves project changes during
updates, and reports conflicts for manual review. Run `copier update --vcs-ref <tag>` to select a
specific release.

Copier requires Python and Git. Template-owned readiness validation requires Python 3.14+ and the
standard library. The template itself does not bundle or distribute a custom updater.

`docs/prd.md` is the product source of truth. `docs/agents/issue-tracker.md` defines the relationship
between GitHub Issues and Atelier plans, while `docs/agents/domain.md` defines lazy domain and ADR
documentation.

## Included delivery flow

Atelier chooses an Inline or Spec-backed Plan. Once implementation is validated and a PR is created,
agents alternate between `loop-on-ci` and `pr-review-loop`: CI must be green before review work, and
every pushed review fix must become green before review processing resumes. Approved MUST_FIX items
precede SHOULD_FIX items.

## Setup

Install Python 3.14+, Git, and uv. uv is a developer prerequisite for the repository's source
checks and locked dependency environment. Copier is optional for one-time GitHub snapshots and
required only when the project needs update lineage.

## Validation

Generated projects use one validation boundary:

```console
python3.14 scripts/validate_repository.py
```

It runs the template contract, readiness inspection, and adopter-owned project validation in that
order. The template source uses its fixture suites instead; it does not bypass readiness locally.

The bundled CI validates the template contract itself. Generated projects must add their own tests,
linting, builds, security checks, and required-check configuration.

## Automated PR reviews

PR Agent automatically describes, reviews, and suggests improvements when a same-repository pull
request is opened, reopened, or marked ready for review. Fork and bot pull requests are skipped
because GitHub withholds ordinary Actions secrets and restricts their workflow token to read-only,
while PR Agent requires the secret and write access. Repository owners, members, and collaborators
may also run `/review`, `/describe`, and `/improve` commands in pull-request comments.

Add a `GEMINI_API_KEY` Actions repository secret before opening a pull request; create the key in
Google AI Studio and store it in the generated repository under **Settings → Secrets and variables →
Actions**. Never commit the key.

### Required repository secrets

Configure these user-provided secrets under **Settings → Secrets and variables → Actions**:

- `GEMINI_API_KEY` — required by both PR Agent workflows. Create it in Google AI Studio.

`GITHUB_TOKEN` and `GH_TOKEN` are supplied automatically by GitHub Actions for the PR Agent and
semantic-release workflows; do not create or commit them manually.

The default model and review behavior are configured in `.pr_agent.toml`. Projects may adapt those
settings while retaining the workflow's least-privilege permissions and secret-based credential
wiring.

## Releases

After Python source, delivery-contract, project-validation, and workflow-lint checks succeed, the template runs
semantic-release for pushes to `main` and manual CI dispatches from `main`. Releases are serialized,
and Conventional Commit messages determine the next version, release notes, Git tag, and GitHub
Release. Generated projects own their product-specific commands through `scripts/validate_project.py`;
every release-critical validation job must be added to the `release` job's `needs`.

## Scope

This template intentionally contains generic instructions, documentation scaffolds, GitHub delivery
files, and reusable skills. Product code and language-specific skills belong in generated projects.

See `NOTICE.md` for bundled skill provenance.

## License

This repository is licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for the
full text. Third-party bundled skill provenance and licensing notes are listed in `NOTICE.md`.

CI uses Astral's pinned `setup-uv` action to provide Python 3.14 and uv, with uv caching enabled.
The source checks run from the locked environment:

```console
uv sync --all-groups --locked
uv run python scripts/validate_template.py
uv run ruff check
uv run ruff format --check
uv run basedpyright
```

Focused mutation testing runs against the deterministic bootstrap and validation cores. It is
available locally with `uv run mutmut run` and runs weekly or on demand through the separate
Mutation testing GitHub Actions workflow; it is intentionally not part of the fast required PR
checks.

GitHub Actions workflows are checked independently with actionlint. Nix is not required for local
development, CI, release gating, or template generation, but remains available as an optional
maintainer toolchain for users who prefer it:

```console
nix develop
nix flake check
nix fmt
```

The optional Nix shell provides the pinned workflow and Nix lint tools alongside Python 3.14 and uv.
Cachix publishing is also optional and requires the configured authentication token.
