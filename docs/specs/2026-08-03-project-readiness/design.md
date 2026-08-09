# Project Readiness Contract

Status: Approved on 2026-08-04
Supersession: upon approval of `docs/specs/2026-08-05-deterministic-project-bootstrap/design.md`
(revision 15), this spec is superseded and this directory is archived at bootstrap activation; its
v1 rules move verbatim into that design's frozen readiness-rule baseline v1. This note is
informational until then; this spec remains the approved authority for the validator contract.

## Problem

The template supplies a delivery workflow, but it does not enforce the transition from template
scaffolding to a configured product repository. An untouched generated project can retain the
template PRD and README, omit product-specific validation, and still satisfy the generic template
contract.

This conflicts with the repository's intended authority and completion model:

- `docs/prd.md` owns product scope and acceptance criteria.
- `AGENTS.md` requires repository-defined formatting, linting, tests, and builds before completion.
- CI and release need one stable product-validation boundary.

Generated projects need a deterministic, actionable indication that configuration is incomplete.
They also need one command that developers, coding agents, and CI can run. The contract can prove
that project validation is configured and succeeds; it cannot prove that the adopter selected
adequate validation commands.

## Scope

### In scope

- A deterministic readiness contract for generated projects.
- A dual-role authoritative PRD that describes the template source and is marked for replacement in
  generated projects.
- Explicit scaffold markers and known-boilerplate checks.
- A canonical generated-project repository-validation command.
- An adopter-owned hook for stack-specific validation.
- Source-template fixtures that exercise generated-project failure and success paths.
- A release gate and documented manual merge-gate setup.
- GitHub-generated and Copier-generated project coverage.
- Stable diagnostics, compatibility expectations, onboarding, and recovery guidance.

### Out of scope

- Judging whether requirements or validation commands are substantively adequate.
- Automatically authoring or approving a project's requirements.
- Stack detection or stack-specific presets.
- Remotely configuring GitHub rulesets or branch protection.
- A mutating or interactive bootstrap command.

## User stories

### US-1: An adopter establishes a project contract

Supports: `REQ-001`.

As a template adopter, I want an untouched generated repository to identify every independent
readiness problem, so that I cannot mistake intact scaffolding for a configured project.

Acceptance criteria:

- `docs/prd.md` rejects the retained marker and known template-source boilerplate.
- The PRD contains each required level-two heading exactly once and in this relative order:
  `Problem`, `Goals`, `Non-goals`, `Users and workflows`, `Requirements`, `Quality attributes`,
  `Release criteria`, and `Open questions`. Additional level-two sections are allowed.
- A product requirement is declared under `## Requirements` as an exact level-three heading in the
  form `### REQ-001: Non-empty title` and has non-empty body content.
- At least one requirement is declared. Identifiers are unique, use exactly three digits from
  `001` through `999`, and need not be contiguous.
- Requirement references outside declarations may repeat. Declaration-like text in fenced code
  blocks does not count.
- `README.md` rejects the retained marker, template title, and known introductory boilerplate.
- The README contains exactly one non-template level-one project title plus non-empty `## Setup` and
  `## Validation` sections. The Validation section names `scripts/validate_repository.py`.
- The project-validation hook exists, is executable, and no longer contains the template's
  unconfigured sentinel.
- Every failure includes a stable diagnostic identifier, the affected path, and a concrete next
  action.

### US-2: A developer or coding agent validates a generated repository

Supports: `REQ-002`.

As a developer or coding agent, I want one documented command, so that local completion evidence and
CI exercise the same generated-project contract.

Acceptance criteria:

- `scripts/validate_repository.py` runs the template contract, readiness inspection, and the
  adopter-owned project hook in that order.
- The aggregate command prints stage boundaries, stops after the first failing stage, and preserves
  that stage's exact non-zero status.
- Readiness inspection reports all independent readiness failures before returning.
- The project hook's success proves only that the configured hook ran successfully; reviewers remain
  responsible for assessing its coverage.
- Generated-project documentation, pull-request guidance, and CI name the same command.

### US-3: A template maintainer verifies both generation paths

Supports: `REQ-004`, `REQ-005`.

As a template maintainer, I want the template source to remain releasable while generated projects
start unready, so that template releases exercise onboarding without bypassing it.

Acceptance criteria:

- Source CI selects fixture mode only when `github.repository` matches the explicit source identity
  configured in the workflow.
- Source maintainers use readiness fixtures locally; `scripts/validate_repository.py` remains a
  generated-project command.
- A GitHub-style snapshot fixture and a Copier-generated fixture both fail while untouched and pass
  after minimal valid configuration.
- Both generation paths share the generated-project contract but may contain different
  template-maintenance artifacts.
- Copier update coverage proves that adopter-owned hook changes are preserved or produce an explicit
  conflict. Silent overwrite fails the test.
- GitHub-generated projects are documented as one-time snapshots. Copier-generated projects retain
  update lineage and can select semantic-release tags.

### US-4: A maintainer protects release and merge boundaries

Supports: `REQ-003`, `REQ-006`.

As a project maintainer, I want validation to gate releases and clear instructions for gating merges,
so that the repository does not imply protection it has not configured.

Acceptance criteria:

- The checked-in release graph depends on the `project-validation` job and cannot tolerate or ignore
  its failure.
- The project-validation job invokes the canonical generated-project command outside source mode.
- The job runs on the included GitHub-hosted runner for the workflow's ordinary `pull_request`,
  `push`, and manual events. It does not execute pull-request code through `pull_request_target`,
  attach a privileged environment, or override checkout to an untrusted revision from a privileged
  event.
- The job uses read-only contents permission, persists no checkout credentials, receives no secrets,
  and uses no failure-tolerant job or command step.
- Every pull request emits the stable `Project validation` check name. Onboarding tells an
  administrator to require that exact check for the default branch.
- Local readiness does not query GitHub or claim that merge protection was configured automatically.

## Domain language

Repository-wide terminology is defined in [`CONTEXT.md`](../../../CONTEXT.md). In particular:

- a **generated-project contract** is shared behavior, not identical file packaging;
- **project readiness** is deterministic configuration evidence, not product correctness;
- a **release gate** is checked-in workflow behavior, while a **merge gate** is administrator-owned
  repository configuration; and
- only a **Copier-generated project** has Copier update lineage.

## Constraints

- `docs/prd.md` remains authoritative for product scope and acceptance criteria.
- The repository remains language-neutral.
- Template-owned deterministic validation works without Nix and does not require Ripgrep.
- The required validation job uses no secrets or write-capable permissions.
- The checker is read-only and offers no bypass or automatic rewriting.
- Copier owns update, preservation, and conflict mechanics; the template does not reimplement them.

## Architecture

### Document contracts

The template source PRD describes this template's product requirements while retaining an explicit
replacement marker and stable introductory boilerplate. A generated project replaces that content
with its own contract while keeping the required section and requirement-declaration structure.
Deleting only the marker cannot make the copied template PRD ready.

The source README likewise receives an explicit marker. Generated-project readiness requires a
project title and predictable Setup and Validation sections while leaving all other README structure
to the adopter.

### Validation boundaries

Four scripts have separate ownership:

- `scripts/validate_template.py` is template-owned. It checks required template files and active CI
  topology, including the validation job, command invocation, permissions, and release dependency.
- `scripts/check_project_readiness.py` is template-owned. It inspects the PRD, README, and hook
  configuration without executing the hook.
- `scripts/validate_project.py` is adopter-owned. The initial executable stub explains that setup is
  incomplete; the adopter replaces it with product-specific commands.
- `scripts/validate_repository.py` is template-owned. It composes the preceding three checks for a
  generated project.

The readiness checker returns `0` when ready, `1` for one or more observable readiness failures, and
`2` for usage or internal evaluation errors. The aggregate preserves the first failing stage's exact
status. The adopter-owned hook may use any non-zero failure status; the aggregate's stage label makes
its origin clear. Template-owned inspection is read-only; the aggregate makes no non-mutation or
toolchain guarantee for adopter-owned hook commands.

Stable diagnostic identifiers form the machine-facing error vocabulary. Human-readable explanations
and next actions may improve without breaking consumers that rely on identifiers. Each diagnostic
also names the affected path and contains an actionable remediation. Identifier removal, reuse for a
different condition, or semantic reassignment is breaking; adding a new identifier for a new
condition is compatible when it does not reject a previously conforming project.

### Source and generated-project behavior

The workflow-level source identity is explicitly set to
`AGENTIC_TEMPLATE_SOURCE_REPOSITORY=knirski/agentic-template` and compared with
`github.repository`. It is never derived from the current repository.

- In the template source, `project-validation` runs generated-project fixtures.
- In every other repository, it runs `python3 scripts/validate_repository.py`.

There is no local source-mode bypass in the aggregate command. This makes an untouched GitHub
snapshot fail automatically while keeping source CI green through evidence about generated
projects.

GitHub's repository-template operation copies the source tree and does not interpret Copier
exclusions. Copier may exclude template-maintenance artifacts. These packaging differences are
acceptable because both outputs implement the same generated-project contract.

### CI and security boundary

The template contract owns workflow topology checks; the readiness checker does not duplicate them.
Contract tests inspect the active `project-validation` and `release` job structures rather than
accepting matching comments or unrelated jobs.

The release job depends on successful project validation. Contract tests reject failure-tolerant
validation and release conditions that run after a failed dependency. Merge protection remains an
explicit administrator step because the repository cannot enforce external settings without
authenticated writes.

The project-validation job runs on the included GitHub-hosted runner under ordinary workflow events,
has read-only contents permission, does not persist checkout credentials, attaches no environment,
and receives no secrets. It never uses `pull_request_target` to execute contributor code or overrides
checkout to an untrusted revision from a privileged event. The adopter-owned hook is treated as
project code and runs within that least-privilege boundary. Custom or self-hosted runners require an
equivalent isolation decision by the adopter and fall outside the template's guarantee.

## Testing strategy

Readiness fixtures exercise document and hook inspection without executing adopter commands. They
cover untouched scaffolding, marker-only deletion, known boilerplate, heading order and duplication,
requirement declarations and references, README structure, hook configuration, simultaneous
readiness failures, and internal errors. Assertions cover the diagnostic identifier, affected path,
and presence of a remediation. A hostile hook canary and before/after filesystem snapshot prove that
inspection neither executes the hook nor mutates the fixture.

Aggregate-command fixtures separately exercise stage ordering, short-circuiting, stage labels, and
exact status propagation, including project-hook failures.

Workflow contract tests cover active command invocation, source-identity handling, supported events,
runner and checkout trust, lack of an attached environment, read-only permissions, non-persisted
credentials, stable check name, and effective failure propagation through the release dependency.
Python compilation/tests and Actionlint cover implementation and workflow syntax.

A GitHub-style fixture copies a deterministic release-tree manifest: paths already tracked by Git
plus the plan's explicit new generated-project paths, using current working-tree content and
preserving executable modes. It excludes Git metadata, ignored files, and unrelated untracked files,
then asserts that every required validation script is present before exercising behavior.

Copier smoke coverage creates and updates a Copier-generated project with its pinned Copier version.
The update scenario changes the same adopter-owned hook in both the project and the newer template.
Preservation requires a successful update, retained adopter content, and applied non-conflicting
template content. A conflict is accepted only when the pinned Copier behavior emits its expected
conflict status or diagnostic, leaves explicit conflict evidence, and keeps the adopter content
recoverable. Any other failure or loss of adopter content fails closed.

## Onboarding and recovery

Readiness guidance uses this fixed sequence:

1. Replace the marked `docs/prd.md` contract with the project's requirements.
2. Replace the marked README with the project title, setup, and validation instructions.
3. Replace `scripts/validate_project.py` with the project's validation commands.
4. Run `python3 scripts/validate_repository.py` locally and address its diagnostic identifiers.
5. Confirm CI invokes the command and release depends on `project-validation`.
6. Configure `Project validation` as a required status check in the default-branch ruleset.

If a configured project is rejected incorrectly, maintainers correct the template-owned checker;
bypassing validation is not the recovery path. Copier conflicts remain Copier-owned and are resolved
through its documented update workflow.

## Compatibility policy

A checker change that makes a previously conforming generated project unready is a breaking template
contract change. It requires a semantic major release and migration notes. Diagnostic wording and bug
fixes may ship normally when they do not invalidate conforming projects. Removing or semantically
reassigning a diagnostic identifier is also breaking. V1 does not add a separate readiness-version
file or support multiple checker versions at runtime.

## Trade-offs and known limitations

- Strict Markdown structure favors deterministic tool behavior over flexible authoring.
- Structural checks cannot determine whether requirements or validation commands are good.
- Python 3.11+ is an explicit prerequisite for all template-owned and initial adopter validation
  scripts. Adopters may replace the hook with another executable if they retain its contract.
- The source-mode comparison contains one canonical repository slug that must change if the template
  moves.
- GitHub-generated projects have no automatic update lineage; update-capable adopters must start with
  Copier.
- Merge protection is documented but cannot be verified locally.

## Deferred follow-ups

These items are recorded for later and are not part of the implementation plan:

1. **Deterministic interactive bootstrap** — the highest-value follow-up once readiness v1 defines
   the output contract and supplies conformance fixtures.
2. **Optional authenticated GitHub ruleset setup** — consider when adopters request automated merge
   protection and can grant explicit external-write authority.
3. **Machine-readable JSON diagnostics** — add only when a concrete consumer needs structured output;
   stable diagnostic identifiers are sufficient for v1.
4. **Optional stack-specific presets** — keep outside the language-neutral core and add only for
   demonstrated stacks with maintainers and tests.
5. **Guided PRD authoring** — design as a separate feature if adopters need help producing the PRD,
   without coupling authoring to deterministic readiness.

## Open questions

No product decision remains unresolved.

## References

- [Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template), accessed 2026-08-04.
- [Configuring a Copier template](https://copier.readthedocs.io/en/latest/configuring/), accessed
  2026-08-04.
