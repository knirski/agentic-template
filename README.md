# Rygor

<!-- rygor:placeholder:readme -->

A language-neutral GitHub repository template for planning, implementing, validating, and reviewing
software changes with coding agents.

## Start a project

1. Select **Use this template** on GitHub.
2. Replace the marked contract in `docs/prd.md` with the project's product requirements.
3. Replace this marked README with the project title, setup, and validation instructions.
4. Replace the marked `SECURITY.md` and `CONTRIBUTING.md` with the project's policies and guidance.
5. Replace `scripts/validate-project` with the project's formatting, linting, tests, and build checks.
6. Run `uv run --python 3.14 scripts/validate_repository.py` and address every readiness diagnostic.
7. Require the `Project validation` check in the default-branch ruleset.

Adopt an existing repository without recreating it via `plan adopt`/`adopt` — see the deterministic bootstrap CLI below and `docs/template-updates.md` for the `collisions` declaration and lifecycle-source ownership.

The template is maintained with [Copier](https://copier.readthedocs.io/):

```console
uv tool install copier
copier copy https://github.com/knirski/rygor.git ./my-project
cd ./my-project
copier update
```

The generated project records its template source and answers in `.copier-answers.yml`. Copier
uses semantic-release Git tags to identify template versions, preserves project changes during
updates, and reports conflicts for manual review. Run `copier update --vcs-ref <tag>` to select a
specific release.

Copier requires Python and Git. Template-owned readiness validation and bootstrap commands require
Python 3.14+ and use the standard library. The template itself does not bundle or distribute a
custom updater.

### Deterministic bootstrap CLI

The repository ships `scripts/bootstrap_project.py`, the deterministic bootstrap compiler. It turns a
reviewable input bundle into one complete typed installation plan and applies it through a
recoverable transaction:

```console
uv run --python 3.14 scripts/bootstrap_project.py init --from ./bootstrap.json --output ./bundle
uv run --python 3.14 scripts/bootstrap_project.py status --target ./my-project
uv run --python 3.14 scripts/bootstrap_project.py plan apply --bundle ./bundle --target ./my-project --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py apply --bundle ./bundle --target ./my-project
uv run --python 3.14 scripts/bootstrap_project.py plan adopt --bundle ./bundle --target ./my-project --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py adopt --bundle ./bundle --target ./my-project
uv run --python 3.14 scripts/bootstrap_project.py recover --target ./my-project
```

`init` writes a complete reviewable bundle from an input file; there is no interactive mode. `status`
describes the generation path and mechanical readiness in one observation pass and never runs the
adopter hook. `plan apply` compiles the plan and writes a canonical receipt without mutating the
target; only `apply` installs. `plan adopt` and `adopt` install the same profile-managed output plus
the template lifecycle source set into any verified non-bare Git working tree without a project
manifest (empty or populated, dirty or clean) through an explicit `collisions` map in the bundle
that declares each collision as `keep-existing` (exclude from the plan and inventory) or `replace`
(overwrite, prior `FileState` recorded in the receipt); undeclared collisions, declarations naming
non-colliding paths, and `replace` on seed-once legal/provenance paths refuse the plan. Adopted
projects record `ADOPTED` provenance and behave snapshot-like: `restore` works against the recorded
baseline and `reconcile` is permanently refused; installed lifecycle files (the declared `lifecycle_paths` — e.g. `AGENTS.md`, skills,
`scripts/bootstrap/*.py`, `copier.yml` — plus `.rygor/source-ownership.json` and the regular-file
`CLAUDE.md` copy) are
drift-fatal managed inventory, while `keep-existing` paths remain absent and never drift-fatal.

An install whose adopter hook succeeds exits 0. User-correctable
refusals, unmet preconditions, expected scaffolds, and installed-but-unready hook results exit 1.
Usage, input, contract, manifest, render-contract, transaction, and internal failures exit 2.
`apply` on an already-installed project refuses and names `status` or
`uv run --python 3.14 scripts/validate_repository.py` as the next action. `recover` finishes or discards an
interrupted transaction; a target mismatch or third state can block automatic recovery, retain
evidence, and exit 1. `recover` never re-runs the adopter hook.
`--format json` emits exactly one canonical command envelope on stdout.

`docs/prd.md` is the product source of truth. `docs/agents/issue-tracker.md` defines the relationship
between GitHub Issues and Atelier plans, while `docs/agents/domain.md` defines lazy domain and ADR
documentation.

Generated projects also receive managed operational guidance in
[`docs/delivery-workflow.md`](docs/delivery-workflow.md),
[`docs/template-updates.md`](docs/template-updates.md),
[`docs/capabilities.md`](docs/capabilities.md), and
[`docs/github-setup.md`](docs/github-setup.md).

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
uv run --python 3.14 scripts/validate_repository.py
```

It runs the template contract, readiness inspection, and adopter-owned project validation in that
order. The template source uses its fixture suites instead; it does not bypass readiness locally.

The bundled CI validates the template contract itself. Generated projects must add their own tests,
linting, builds, security checks, and required-check configuration.

### Regenerating the source cleanup inventory

The template source carries a fingerprinted cleanup inventory
(`.rygor/maintenance-artifacts.json`) that authorizes GitHub-snapshot cleanup of
source-only paths. When tracked files under those paths change, regenerate it from the tracked
source before committing:

```console
uv run python scripts/regenerate_cleanup_inventory.py
```

Stage the rewritten inventory together with the intended source changes; avoid staging unrelated
files while regenerating it.

`test_cleanup_inventory_matches_the_tracked_source` fails on a stale inventory, so the fixture
suites catch a forgotten regeneration.

## Optional automated PR reviews

Projects selecting the `pr-agent-gemini` capability automatically receive workflows that describe,
review, and suggest improvements when a same-repository pull request is opened, reopened, or marked
ready for review. The `integrated` profile includes this capability; other profiles do not receive
these workflows unless the capability is explicitly added. Fork and bot pull requests are skipped
because GitHub withholds ordinary Actions secrets and restricts their workflow token to read-only,
while PR Agent requires the secret and write access. Repository owners, members, and collaborators
may also run `/review`, `/describe`, and `/improve` commands in pull-request comments when the
capability is installed.

When `pr-agent-gemini` is selected, add a `GEMINI_API_KEY` Actions repository secret before opening a
pull request; create the key in Google AI Studio and store it in the generated repository under
**Settings → Secrets and variables → Actions**. Never commit the key.

### Required secret for PR Agent

Configure this user-provided secret under **Settings → Secrets and variables → Actions** when the
capability is selected:

- `GEMINI_API_KEY` — required by both PR Agent workflows; create it in Google AI Studio.

`GITHUB_TOKEN` and `GH_TOKEN` are supplied automatically by GitHub Actions for installed PR Agent
and semantic-release workflows; do not create or commit them manually.

The default model and review behavior are configured in `.pr_agent.toml` when the capability is
installed. Projects may adapt those settings while retaining the workflow's least-privilege
permissions and secret-based credential wiring.

## Optional automated releases

Generated projects run semantic-release only when the `semantic-release` capability is selected,
for example through the `release-automated` or `integrated` profile. Its release job waits for the
project-validation and selected managed checks before running on pushes to `main` or manual CI
dispatches from `main`. The template source releases through the maintainer workflow only after its
locked source checks, source fixtures, and workflow lint pass. Releases are serialized, and
Conventional Commit messages determine the next version, release notes, Git tag, and GitHub Release.
Generated projects own their product-specific commands through `scripts/validate-project`; every
release-critical validation job must be added to the `release` job's `needs`. Maintainer-only source
checks (locked uv sync, Python source checks, and actionlint) run in the separate source-maintainer
workflow that Copier excludes and GitHub snapshots clean up, so generated projects do not require the
template's source toolchain.

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
