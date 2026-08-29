# Product Requirements Document

<!-- rygor:placeholder:prd -->

This file is authoritative for the Rygor. In a generated project, replace this
entire template-source contract with the product's own content while retaining the section and
requirement structure demonstrated below.

## Problem

Repositories created from the template need a consistent delivery workflow and an explicit
transition from generic scaffolding to a configured product contract. Without deterministic
readiness evidence, intact placeholder content can be mistaken for a releasable project.

## Goals

- Provide a language-neutral workflow for planning, implementation, validation, review, and release.
- Make incomplete generated-project setup deterministic and actionable.
- Preserve clear ownership between template-maintained contracts and adopter-maintained product
  validation.
- Support both GitHub snapshot generation and update-capable Copier generation.

## Non-goals

- Supplying product code or stack-specific validation presets.
- Judging whether product requirements or validation commands are substantively adequate.
- Reimplementing Copier's update and conflict mechanics.
- Automatically configuring external repository settings.

## Users and workflows

- Template adopters create a repository, replace the marked product scaffolding, configure the
  project-validation hook, run repository validation, and configure merge protection.
- Developers and coding agents use the repository's canonical validation command as completion
  evidence.
- Template maintainers validate both supported generation paths before releasing template updates.

## Requirements

### REQ-001: Detect incomplete generated-project setup

An untouched generated project must fail deterministic readiness checks with stable diagnostics and
concrete next actions for its PRD, README, security policy, contributing guide, and project-validation
hook.

### REQ-002: Provide one generated-project validation command

Generated-project documentation and CI must use one canonical command that checks the template
contract, project readiness, and the adopter-owned project-validation hook in a stable order.

### REQ-003: Gate releases on project validation

The checked-in release workflow must depend on project validation. Documentation must distinguish
that release gate from administrator-configured merge protection.

### REQ-004: Verify generated behavior from the template source

The template source must remain releasable by exercising generated-project failure and success
fixtures instead of bypassing readiness.

### REQ-005: Preserve generation-path ownership

GitHub-generated and Copier-generated projects must share the readiness contract while retaining
their path-specific packaging and update behavior. Copier remains responsible for its update and
conflict semantics.

### REQ-006: Keep template-owned validation portable and least-privileged

Template-owned contract and readiness checks must work without Nix, avoid mutating project files, and
produce reproducible results. The adopter-owned hook may select its own toolchain and create normal
validation artifacts, but CI must execute it on the supported GitHub-hosted runner without secrets,
write-capable permissions, persisted checkout credentials, or a privileged environment.

### REQ-007: Bootstrap and adopt projects deterministically

The template must compile an explicit, self-contained input bundle into one complete project plan.
The same normalized profile/capability closure and template source must produce byte-identical
profile-managed output, modes, and operation ordering regardless of generation path; manifest
generation provenance and, for adopted projects, the additional managed lifecycle inventory
(`lifecycle_paths`, `.rygor/source-ownership.json`, and the regular-file `CLAUDE.md` copy) are
generation-path-specific by design and therefore excluded from the byte-identical guarantee, while
the profile/capability closure remains byte-identical. Initial installation is supported for a
verified non-bare Git working tree that either contains a recognized scaffold produced by one of
the two generation paths (`apply`) or is any manifest-free tree (empty or populated, dirty or
clean) adopted through an explicit per-path collision declaration (`adopt`); collisions between
planned managed output — including the installed template lifecycle source set — and observed
content must be declared `keep-existing` or `replace`, and an undeclared collision or an illegal
`replace` on a seed-once legal/provenance path refuses the plan. A target that is non-Git, bare,
or manifest-bearing remains unsupported outside v1.

### REQ-008: Select and extend capabilities declaratively

Initial bootstrap must require one explicit intent-based profile and freeze its requested capability
set. Capability dependencies, settings, artifacts, and contributions must resolve through declarative
definitions; unselected output must be absent. A later `add` may append capabilities and their complete
normalized settings without changing the frozen profile or existing settings. Removal, replacement,
and reconfiguration are outside v1.

### REQ-009: Preserve explicit ownership and project identity

Bootstrap must distinguish bootstrap-managed output, seed-once adopter output, generated-lifecycle
source, and snapshot-cleanup inputs. The checksummed project manifest records immutable initial
answers, append-only capability additions, generation provenance, maintenance disposition, the exact
managed inventory, and the installed source baseline; it must not contain adopter prose, legal text,
secret values, or a claim about current tree bytes. Adopted projects additionally record the
installed template lifecycle source — the declared lifecycle paths, the template root's
`.rygor/source-ownership.json`, and a regular-file `CLAUDE.md` copy of the template's `AGENTS.md`
bytes — inside the managed inventory, where those entries are restore-able and drift-fatal; the
ownership-separation prohibitions remain unchanged. Adopter-owned files must never become drift-fatal,
while managed drift must be diagnosed before unrelated mutation; keep-existing adoption declarations
exclude paths from the managed inventory permanently.

### REQ-010: Provide a closed project lifecycle

The public lifecycle consists of `status`; preview commands for `apply`, `plan adopt`, `add`,
`restore`, and `reconcile`; the corresponding mutating commands `apply`, `adopt`, `add`, `restore`,
and `reconcile`; and `recover`. `restore` may reproduce only recorded managed identities and never
advance manifest identity, and for adopted projects it sources installed lifecycle entries from the
template root verified against the recorded inventory. `reconcile` is the only operation that may
advance the installed source baseline and is available only for Copier projects after Copier resolves
its own update conflicts; snapshot and adopted projects diagnose source changes and offer targeted
baseline repair or regeneration, never reconciliation, and adopted projects permanently refuse
`reconcile` with `OPERATION_UNAVAILABLE`. Destructive reconciliation must require a freshly
re-derived plan receipt bound to the target.

### REQ-011: Make every mutation recoverable and fail closed

Every mutation must execute one complete typed operation plan under the target's canonical lock and a
write-ahead journal. Before sealing, failure must restore the exact planned pre-state or retain evidence
for explicit recovery; after sealing, recovery must preserve the verified installed state and finish
cleanup forward. A completely restored pre-state must be durably distinguished from partial mutation
before rollback evidence is removed. Recovery must be idempotent, preserve unrecognized third states, survive
`git clean -fdx`, and never claim atomic multi-file visibility or roll back adopter-hook effects.

### REQ-012: Separate installation, mechanical readiness, and project readiness

A successful transaction means the planned bootstrap installation passed template-owned mechanical
gates. Project readiness is a point-in-time result that additionally requires the adopter-owned hook to
succeed. Declared scaffold findings and hook failure must be retained and reported with exit 1 rather
than rolling back a valid installation. Hook evidence must not be persisted, inferred, or replayed by
recovery.

### REQ-013: Bound compatible template evolution

Publication of the first bootstrap release freezes schema-v1 capability, ownership, and readiness-rule
identities and their compatibility corpus. A compatible update must not add a required seed-once path,
tighten or add a blocking obligation over adopter-owned state, reinterpret a stable identifier, or make
an existing normalized project state impossible to satisfy through its supported lifecycle. Breaking
changes require an explicit future lifecycle and schema decision.

### REQ-014: Expose deterministic, typed command outcomes

Template-owned commands must decode into closed intent and state types, permit only legal transitions,
and return explicit success, action-required, invalid-request, contract, recovery, or internal-failure
outcomes. Text and JSON presentation must carry the same diagnostics, next actions, plans, and
point-in-time evidence. Inspection never mutates, planning never prompts, and destructive commands have
no interactive confirmation path.

### REQ-015: Keep generated operations durable and extensible

Bootstrap must install durable adopter documentation for delivery, template updates, capabilities, and
GitHub setup. Generated CI must call one adopter-owned reusable project-validation workflow while
keeping selected template checks managed. Capability and readiness definitions must be extensible
without adding capability-specific branches to the resolver, renderer, transaction shell, or CLI.

## Quality attributes

- **Reliability:** Conforming fixtures produce stable results and diagnostic identifiers.
- **Security:** Project validation runs on the supported GitHub-hosted runner without secrets, write
  permissions, persisted checkout credentials, or a privileged environment.
- **Compatibility:** Publication of the first bootstrap-capable release establishes the compatibility
  baseline identified by that release and manifest schema. From that point, a change that makes a
  conforming released project unready is a breaking template-contract change with an explicit
  lifecycle. Before that publication no generated-project population or legacy compatibility contract
  exists.
- **Portability:** Template-owned deterministic validation runs with Python 3.14+. Selected generated
  capabilities may declare uv-managed runtime dependencies; adopter-owned commands define their own
  additional toolchain requirements.
- **Maintainability:** Template, readiness, project, and aggregate validation keep separate ownership.
- **Analyzability:** Template-owned Python commands keep immutable policy and state transitions in a
  shared functional core; filesystem, Git, process, environment, and terminal effects remain in thin
  imperative shells with explicit typed failures.

## Release criteria

- Repository-defined formatting, linting, tests, and builds pass.
- GitHub-style and Copier-generated fixtures demonstrate initial failure and configured success.
- Copier update coverage rejects silent overwrite of adopter-owned validation.
- Python syntax, workflow contracts, Markdown, and the source-maintainer validation suites
  pass.
- Static exhaustiveness and generated state-transition tests cover the template-owned command cores.
- Every leaf decision has a reachable preimage fixture, every supported intent/state combination has a
  specified outcome, and transaction crash sequences preserve or recover exactly the planned paths.
- Both generation paths pass the complete profile/capability matrix, ownership checks, source-evolution
  compatibility corpus, and deterministic text/JSON CLI fixtures.
- The release graph includes project validation and the final diff contains no secrets or generated
  agent state.

## Open questions

No current product decision is unresolved. Deferred ideas remain recorded in approved feature
designs until promoted through a separate planning workflow.
