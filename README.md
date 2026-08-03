# Agentic Delivery Template

A language-neutral GitHub repository template for planning, implementing, validating, and reviewing
software changes with coding agents.

## Start a project

1. Select **Use this template** on GitHub.
2. Replace the prompts in `docs/prd.md` with the project's product requirements.
3. Adapt `README.md` for the product and add stack-specific build and test commands.
4. Extend `AGENTS.md` only with durable project conventions; keep detailed procedures in skills.
5. Add project CI jobs alongside the included delivery-contract job.
6. Install only the language and domain skills the project actually needs.

`docs/prd.md` is the product source of truth. `docs/agents/issue-tracker.md` defines the relationship
between GitHub Issues and Atelier plans, while `docs/agents/domain.md` defines lazy domain and ADR
documentation.

## Included delivery flow

Atelier chooses an Inline or Spec-backed Plan. Once implementation is validated and a PR is created,
agents alternate between `loop-on-ci` and `pr-review-loop`: CI must be green before review work, and
every pushed review fix must become green before review processing resumes. Approved MUST_FIX items
precede SHOULD_FIX items.

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

The default model and review behavior are configured in `.pr_agent.toml`. Projects may adapt those
settings while retaining the workflow's least-privilege permissions and secret-based credential
wiring.

## Releases

After delivery-contract validation succeeds, the template runs semantic-release for pushes to
`main` and manual CI dispatches from `main`. Releases are serialized, and Conventional Commit
messages determine the next version, release notes, Git tag, and GitHub Release. Product-specific
validation, artifact builds, and uploads are not included; generated projects should add validation
to CI and artifact publication to the reusable semantic-release workflow when needed. Every
release-critical validation job must also be added to the `release` job's `needs`; unrelated CI jobs
do not delay publication.

## Scope

This template intentionally contains generic instructions, documentation scaffolds, GitHub delivery
files, and reusable skills. Product code and language-specific skills belong in generated projects.

See `NOTICE.md` for bundled skill provenance.
