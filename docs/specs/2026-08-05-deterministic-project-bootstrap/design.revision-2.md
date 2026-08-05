# Deterministic Project Bootstrap with Capability Profiles

**Status:** Revision 2, assembled for final confirmation
**Date:** 2026-08-05
**Planning mode:** Spec-backed Plan
**Supersedes:** `design.discovery-draft.md` in this directory

## Summary

Add a deterministic, explicit bootstrap compiler that turns either supported generated-repository
shape into a locally ready project from a reviewable input bundle. The compiler expands an explicitly
selected snapshot profile into an exact capability set, writes only declared outputs, persists
normalized mechanical state, and validates the result through the repository's canonical validation
boundary.

The first capability catalog covers the integrations already present in the template:

- semantic-release;
- Nix;
- Cachix publishing, which depends on Nix; and
- Qodo PR Agent with a Gemini backend.

The catalog and composition model are deliberately extensible, but v1 does not accept executable
plugins, secrets, capability removal, or live-profile mutation. GitHub-created repositories remain
one-time snapshots. Copier-created repositories retain update lineage, after which bootstrap
reconciliation recompiles derived artifacts without duplicating Copier's merge behavior.

The work is delivered as five independently releasable slices. Each slice ends at a release gate that
produces a validated generated project, so the feature can stop after any gate without leaving the
template in a partial state.

This design is an explicit product decision that extends `docs/prd.md`. Implementation must update
the PRD and amend ADR 0001 before changing runtime behavior so those authoritative documents describe
the approved compiler and ownership boundary.

## Revision 2 changes

Revision 1 was a complete discovery record. Review identified lifecycle holes that would surface on
first contact with adopters, and an undivided delivery unit. This revision keeps revision 1's scope,
ownership taxonomy, and decisions, and changes the following.

| Change | Reason |
| --- | --- |
| Added delivery slices with per-slice release gates | Revision 1 was one undivided deliverable with a single terminal gate |
| Added `restore` as the drift remedy | Drift blocked every operation and no mechanism could resolve it |
| Split bootstrap-gating validation from the adopter hook | A correct bootstrap was rolled back when the adopter's own toolchain was unavailable |
| Added `scaffold` content mode | Bootstrap was an authoring gate; adopters could not compile a project before writing a full PRD |
| Split the input fingerprint into mechanical and content parts | One conflated value produced diagnostics that pointed at operations which could not resolve the difference |
| Pinned every hashing and canonicalization construction | Byte-for-byte determinism was promised but its primitives were unspecified |
| Removed `compiler_contract_version` from the manifest | It duplicated `template_source_fingerprint` with no distinct behavior |
| Moved `CONTRIBUTING.md` to seed-once ownership | Managed, drift-fatal contributor guidance conflicts with normal project customization |
| Kept `scripts/validate-project.py` as an accepted legacy hook path | Renaming the hook would have broken every project generated from the current template |
| Added `status`, `adopt`, and a maintenance-cleanup escape hatch | Every failure mode was a hard block with no read-only inspection and no supported override |
| Placed transaction state in the git common directory | Revision 1 left the journal and backup location undefined and destructible by `git clean` |
| Added `.gitattributes` to managed output and defined mode comparison | Hash-based drift detection reports false drift on CRLF checkouts and differing umasks |
| Tiered the fixture matrix | The full cross-product cannot run on every pull request |
| Added a template-source CI conformance fixture | Compiled generated CI would drift from the template's own hand-written CI |
| Moved the manifest to `.agentic-template/project.json` | `.agentic-template.json` and `.agentic-template/` are one character apart and both permanent |
| Added a PRD requirement-delta table | Revision 1 said "promote into requirements" without saying which requirements change |

## Context and problem

The current template detects incomplete generated-project setup, but it does not deterministically
perform that setup. A generated repository inherits a fixed integration set and requires manual
replacement of the README, PRD, and project-validation hook. The current CI and release graph also
assume Nix, Cachix, semantic-release, and Gemini PR review whether or not an adopter wants them.

This creates five material problems:

1. There is no reviewable, reproducible transition from scaffold to locally ready project.
2. Optional integrations are coupled to the source tree rather than selected explicitly.
3. GitHub and Copier generation paths can drift into separate setup implementations.
4. Template updates and capability rendering do not have a strict file-ownership boundary.
5. Durable operational guidance disappears into README customization or remains source-specific.

The existing project-readiness design identified deterministic interactive bootstrap as the
highest-value deferred feature. This design fills that gap while preserving the canonical validation
boundary and Copier's ownership of update and conflict mechanics.

## Goals

- Produce a locally ready repository from adopter-supplied product content and explicit mechanical
  choices, without requiring that content to exist before the project can be compiled.
- Make the same normalized input and template inputs produce byte-for-byte identical
  bootstrap-managed output.
- Require explicit intent-based profile selection and freeze its expansion at creation time.
- Support exact custom capability selection and additive post-bootstrap capability changes.
- Keep core validation independent of optional capabilities and external activation.
- Share one bootstrap engine across GitHub-snapshot and Copier generation paths.
- Give Copier and bootstrap non-overlapping update responsibilities.
- Preserve adopter-owned product content, detect drift in bootstrap-managed artifacts, and provide a
  supported remedy for that drift.
- Make missing external secrets safe and actionable instead of causing noisy workflow failures.
- Produce durable adopter-facing delivery, update, capability, and GitHub setup documentation.
- Allow new declarative capabilities without changing the resolver or transaction engine.
- Keep every existing generated project working across the transition.

## Non-goals

- Inventing or judging product requirements, README content, security policy, or legal terms.
- Accepting, storing, discovering, or writing secrets during bootstrap.
- Mutating GitHub repository settings, rulesets, branch protection, or external services.
- Capability removal, replacement, or arbitrary reconfiguration in v1.
- Re-expanding a stored snapshot when a named profile changes later.
- Migrating incompatible capability or manifest schemas.
- Reimplementing Copier's version selection, update merge, or conflict behavior.
- Providing native Windows execution guarantees.
- Providing a general-purpose template language, executable capability plugins, or trusted Copier
  tasks.
- Proving the semantic validity of an arbitrary adopter-owned GitHub Actions workflow with a
  standard-library-only checker.
- Rolling back filesystem artifacts or external side effects created by the adopter validation hook.
- Guaranteeing that a bootstrapped project's own product validation passes; bootstrap owns mechanical
  readiness only.

## Delivery slices and release gates

Each slice is independently releasable and ends at a gate that produces a validated generated
project on both generation paths. No slice depends on a later slice. Slice order is chosen so that
the artifacts adopters need earliest arrive earliest.

### Slice 1: core bootstrap

Delivers `init`, `plan`, `apply`, `status`, `plan-restore`, `restore`, and `recover`; the input
bundle with seed-once and `scaffold` content modes; the project manifest; the ownership classes; the
transaction journal and backups; `.gitattributes`; the maintenance inventory and its cleanup; and the
legacy hook-path bridge. Profile selection is accepted, but only `portable` and an empty `custom`
list resolve; any other selection fails with a diagnostic naming slice 2.

Slice 1 also delivers the renderer, the slot mechanism, core-rendered CI, and the seed-once
project-validation workflow, because a project with no CI is not a working project. Core CI is the
compiled artifact with an empty capability-contribution set: a delivery-contract job and the stable
`Project validation` call. Slice 2 adds contributors to those slots rather than introducing
compilation.

**Gate G1**

- Both generation paths produce a `portable` project that passes the template-contract and
  project-readiness stages.
- A fully supplied bundle produces a project with no remaining required placeholder.
- A `scaffold` bundle produces a compiling project whose readiness output names exactly the
  unreplaced slots.
- Core CI emits the stable `Project validation` check, calling the seeded reusable workflow with no
  secrets and read-only contents access.
- Equivalent reapply is a validated no-op; a mechanical difference and a content-only difference each
  produce their own distinct diagnostic.
- Managed drift blocks mutation and `restore` resolves it.
- Injected interruption at each transaction phase is detected, blocks mutation, and is fully rolled
  back by `recover`.
- Every project generated from the previous template release still passes canonical validation.

### Slice 2: capability catalog and compiled CI

Delivers the capability definition schema, the resolver, dependency closure, the four v1
capabilities, the five profiles, their contributions to slice 1's CI slots, the secret-availability
preflight pattern, and the stable-ID compatibility fixture.

Activation guidance is emitted inline in job summaries in this slice and gains its link to
`docs/github-setup.md` in slice 3.

**Gate G2**

- The full profile matrix passes on both generation paths.
- Unselected capability artifacts and CI jobs are absent.
- `cachix-publish` resolves `nix`; cycles, collisions, unknown settings, and undeclared ownership all
  fail before mutation.
- `actionlint` passes on the template source and on every generated workflow fixture.
- The template source's own CI structurally conforms to the `integrated` render.
- Absent `GEMINI_API_KEY` and `CACHIX_AUTH_TOKEN` produce successful skips with guidance, and no
  privileged job can start when its preflight is false.

### Slice 3: durable adopter documentation

Delivers `docs/delivery-workflow.md`, `docs/template-updates.md`, `docs/capabilities.md`, and
`docs/github-setup.md`, rendered from core and selected capability fragments.

**Gate G3**

- Each profile renders documents that name exactly its effective capabilities, external
  prerequisites, and activation steps.
- The documents are hashed in the manifest, and editing one is reported as drift and resolved by
  `restore`.

### Slice 4: additive capability lifecycle

Delivers `plan-add` and `add`.

**Gate G4**

- Adding an independent capability, adding a capability that pulls a dependency, and repeating a
  satisfied addition all behave as specified.
- Conflicting settings, removal requests, and existing managed drift are refused.
- The original profile name and profile snapshot are unchanged, and documentation is updated in the
  same transaction as code and workflows.

### Slice 5: Copier reconciliation and adoption

Delivers `plan-reconcile`, `reconcile`, `adopt`, and the final Copier exclude configuration.

**Gate G5**

- A compatible Copier update followed by reconciliation preserves the effective capability set and
  every seed-once and adopter file.
- Copier conflict evidence, managed drift, an incompatible catalog, and an unknown manifest schema
  each produce zero writes.
- A project generated from the pre-bootstrap template is adopted without overwriting any existing
  README, PRD, hook, or licence.

## Users and workflows

Each story names the slice that delivers it.

### US-1: Prepare a reviewable input bundle (slice 1)

As a template adopter, I want an initializer to collect my choices and content into a reviewable
bundle without touching the project so that generation inputs can be inspected, versioned, and
reused.

Acceptance criteria:

- `init` supports interactive collection and a pre-seeded non-interactive input.
- It requires an explicit profile selection; the interactive flow may recommend `portable` but the
  engine has no default profile.
- It requires an explicit decision for every content slot: an adopter file, or `scaffold`.
- It requires an explicit licensing decision, which has no `scaffold` mode.
- It copies referenced content bytes into a self-contained bundle and writes relative references in
  `bootstrap.json`.
- It does not mutate a generated project or perform external operations.
- It refuses a non-empty output location instead of silently replacing a bundle.

### US-2: Bootstrap a generated project deterministically (slice 1)

As an adopter, I want to preview and explicitly apply a bundle so that the result is mechanically
ready without manual placeholder replacement.

Acceptance criteria:

- `plan` reports the exact create, replace, and delete set without mutation.
- `apply` performs initial bootstrap only from recognized generated-project scaffolding.
- Successful apply makes the template-contract and project-readiness stages of
  `python3 scripts/validate-repository.py` succeed locally.
- When every content slot supplies adopter content, the full canonical command succeeds except for
  whatever the adopter's own hook requires; the adopter hook never gates or reverses bootstrap.
- The project-validation hook is installed at the toolchain-neutral path `scripts/validate-project`.
- The result does not depend on Nix unless `nix` is selected.
- The manifest records a mechanical fingerprint and a content fingerprint, without storing prose or
  source paths.
- Reapplying an equivalent bundle validates the current managed state and returns a no-op without
  rewriting seed-once adopter files.
- Reapplying a bundle whose mechanical values differ refuses mutation and names the appropriate
  supported lifecycle operation.
- Reapplying a bundle whose content differs but whose mechanical values match refuses mutation and
  states that seed content is adopter-owned and edited in place.

### US-3: Select an intent-based snapshot profile (slice 1 contract, slice 2 expansion)

As an adopter, I want a named shortcut with stable creation-time meaning so that later template
changes cannot silently add integrations to my project.

Acceptance criteria:

- V1 defines `portable`, `release-automated`, `nix-enabled`, `integrated`, and `custom`.
- A selected named profile expands exactly once and the expanded list is persisted.
- `custom` requires an exact explicit capability list.
- Reconciliation uses the persisted list and never re-expands the stored profile name.
- A profile definition change affects only later bootstraps.

### US-4: Materialize only the effective capabilities (slice 2)

As an adopter, I want selected capabilities and required dependencies to determine the generated
delivery artifacts so that unused integrations are absent.

Acceptance criteria:

- `portable` selects no optional capability.
- `release-automated` selects `semantic-release`.
- `nix-enabled` selects `nix` without Cachix publishing.
- `integrated` selects all four v1 capabilities.
- `cachix-publish` always resolves `nix` as a dependency.
- Unselected capability artifacts and CI jobs are absent after bootstrap.
- Dependency cycles, output collisions, unknown settings, and undeclared ownership fail before
  mutation.

### US-5: Preserve product, licensing, and provenance ownership (slice 1)

As an adopter, I want product prose and legal choices to remain mine while template provenance is
retained so that mechanical regeneration cannot overwrite product decisions.

Acceptance criteria:

- README, PRD, validation hook, SECURITY policy, `CONTRIBUTING.md`, root licence, and the
  project-validation workflow become adopter-owned after their initial installation.
- The manifest contains only normalized mechanical state and hashes.
- Licensing selection is mandatory and explicit, and has no scaffold or default.
- Bootstrap authors no legal terms and makes no legal-validity claim.
- Template Apache-2.0 text and bundled-skill provenance remain available when a different project
  licence or private notice is installed.
- A licensing and provenance audit confirms the final notice layout before implementation fixes it
  and before release.

### US-6: Add capabilities without changing profile provenance (slice 4)

As an adopter, I want to add capabilities after bootstrap so that a project can grow without being
rebased onto a changing profile.

Acceptance criteria:

- `plan-add` previews the exact addition and `add` applies it transactionally.
- Dependencies are resolved and recorded in the effective set.
- The original profile name and profile snapshot remain unchanged.
- Requested additions are recorded separately from dependency-derived effective capabilities.
- Existing capability settings cannot be changed through addition.
- An already-satisfied request is a no-op only when supplied settings do not conflict.
- Removal or replacement requests fail with a diagnostic that identifies the deferred lifecycle.

### US-7: Configure external integrations without secrets (slice 2)

As an adopter, I want locally complete integration files even before external secrets exist so that
readiness is distinct from activation.

Acceptance criteria:

- Bootstrap never accepts or persists secret values.
- The manifest records activation requirements, not live activation status.
- Missing secrets produce successful workflow skips and actionable job summaries.
- A read-only preflight job detects availability before any job with write permissions starts.
- The preflight distinguishes "not configured" from "unavailable in this event context", so that
  pull requests from forks do not read as missing setup.
- Runtime secret values are never emitted through logs or persisted outputs.
- Durable documentation identifies every manual activation step.

### US-8: Reconcile derived artifacts after Copier update (slice 5)

As a Copier adopter, I want updated compatible compiler inputs to re-render derived outputs without
overwriting my project files or duplicating Copier's merge semantics.

Acceptance criteria:

- The documented sequence is `copier update`, bootstrap `reconcile`, then canonical validation.
- Copier selects and merges template inputs; reconciliation only compiles derived outputs.
- Reconciliation preserves the exact effective capability set and normalized settings.
- It updates only managed paths whose bytes match the old manifest hashes, unless the operator
  explicitly opts into overwriting drift.
- It neither adds nor removes capabilities, changes settings, re-expands profiles, nor merges files.
- Copier conflict evidence, managed drift, or an incompatible catalog blocks all writes.
- GitHub-generated projects remain one-time snapshots without Copier update lineage, and their
  documentation states plainly that managed artifacts receive no further template updates.

### US-9: Extend the capability catalog declaratively (slice 2)

As a template maintainer, I want to add a compatible capability through declared data and fixtures so
that the resolver and transaction engine stay stable.

Acceptance criteria:

- A capability declares dependencies, settings, external requirements, owned artifacts,
  contribution slots, and documentation fragments.
- Capability definitions cannot execute commands during bootstrap.
- Settings use a small typed schema and are explicitly declared non-secret.
- New compatible capabilities require no capability-specific branch in the resolver or transaction
  engine.
- Source validation checks every catalog entry, including unselected capabilities.
- Compatibility fixtures reject breaking changes to stable capability IDs.

### US-10: Retain durable adopter documentation (slice 3)

As an adopter, I want operational documentation outside my product README so that delivery and
template knowledge survives normal product customization.

Acceptance criteria:

- Bootstrap produces `docs/delivery-workflow.md`, `docs/template-updates.md`,
  `docs/capabilities.md`, and `docs/github-setup.md`.
- The documents reflect generation path, frozen profile, effective capabilities, external
  prerequisites, validation, update, drift, and recovery behavior.
- Capability additions and reconciliation update affected managed documents in the same transaction
  as code and workflow artifacts.
- Direct edits are treated as managed drift, reported by readiness, and resolved by `restore`.
- Each document's header names itself as managed and points to `CONTRIBUTING.md` and the README for
  project-specific prose.

### US-11: Extend project validation without editing managed CI (slices 1 and 2)

As an adopter, I want a stable reusable-workflow boundary so that I can introduce matrices and
toolchain-specific jobs without taking ownership of compiled CI.

Acceptance criteria:

- Bootstrap seeds `.github/workflows/project-validation.yml` and then treats it as adopter-owned.
- Its initial form exposes `workflow_call` and runs `python3 scripts/validate-repository.py`.
- Bootstrap-managed CI calls it as a stable `Project validation` job.
- The caller passes no secrets, grants read-only contents access, and waits for the complete called
  workflow.
- Selected release automation depends on project validation and all selected managed checks.
- The readiness checker performs bounded structural and security-policy checks but does not claim to
  be a complete YAML semantic validator.

### US-12: Recover interrupted mutations (slice 1)

As an adopter, I want an interrupted mutation to be detectable and recoverable so that bootstrap
does not leave managed ownership ambiguous.

Acceptance criteria:

- Every mutation records a durable journal before replacing target paths.
- A gating-validation or write failure automatically restores planned paths when possible.
- An interrupted journal blocks later mutations.
- `recover` explicitly rolls back to the pre-operation state and never resumes a partial plan.
- Recovery evidence survives `git clean` in a git working tree.
- Hook-created artifacts outside the planned path set are permitted by the PRD and are not removed by
  recovery.

### US-13: Resolve managed drift (slice 1)

As an adopter, I want a supported way to return an edited managed artifact to its compiled state so
that an accidental edit does not permanently block every lifecycle operation.

Acceptance criteria:

- `status` reports every drifted managed path without mutation.
- `plan-restore` shows the exact bytes that would be replaced, and `restore` applies the change
  transactionally.
- `restore` recompiles from the persisted effective capability set and the current template inputs;
  it never re-expands a profile, changes settings, or touches seed-once or adopter files.
- `restore --path` restores a named subset, and the operation is refused when a named path is not
  bootstrap-managed.
- When the current template inputs render different bytes than the manifest records, `restore`
  updates the recorded render fingerprint and hashes and reports that it did so.

### US-14: Adopt a project generated before bootstrap existed (slice 5)

As an existing adopter, I want to opt into bootstrap without losing my work so that the template
transition is not a rewrite.

Acceptance criteria:

- Until a project has a manifest, its existing behavior and canonical validation are unchanged.
- `scripts/validate-project.py` remains an accepted hook path for the lifetime of v1, reported as
  deprecated rather than unready; declaring both hook paths is an error.
- `adopt` installs a manifest and bootstrap-managed artifacts while treating every existing
  seed-once file as already installed.
- `adopt` never overwrites an existing README, PRD, hook, SECURITY policy, `CONTRIBUTING.md`, or
  licence, and never invents a licensing decision; the adopter states it explicitly.
- A project that has been adopted is indistinguishable from a bootstrapped project of the same
  effective capability set, apart from its content fingerprint recording `adopted` slots.

## Decision record from discovery

The following table records the approved answer to each material design question and the extension
path retained for viable deferred work. Rows marked **R2** were decided or changed in revision 2.

| Topic | V1 decision | Proposed future change, if viable |
| --- | --- | --- |
| Bootstrap result | Mechanical readiness is guaranteed; product readiness stays with the adopter **R2** | Staged readiness reporting or a separate finalize phase |
| Content completeness | Every slot is an adopter file or an explicit `scaffold` placeholder **R2** | Inline prose fields where review and escaping rules are sufficient |
| Profile semantics | Named profiles are one-time snapshots | Explicit live profiles or profile-plus-override policies |
| Initial catalog | Current integrations only, behind a generic catalog | Broader first-party catalog and stack presets |
| Catalog ecosystem | Repository-local trusted definitions | Third-party registries with provenance and trust policy |
| Profile names | Intent-based names | More intent-specific profiles when justified by real usage |
| Selection default | No engine default; initializer may recommend `portable` | Guided recommendations based on declared project characteristics |
| Persisted ownership | Mechanical state in the manifest; prose in adopter files | Richer persisted initialization answers for documentation regeneration |
| Content input | Referenced ordinary files in a self-contained bundle | Inline prose fields with explicit escaping |
| Interaction | Initialize a bundle, then explicitly plan/apply | One-command interactive convenience layered on the same engine |
| Lifecycle | Initial bootstrap, additive capability changes, and drift restore **R2** | Removal, replacement, rebasing, and full reconfiguration |
| Drift remedy | `restore` recompiles managed paths from persisted state **R2** | Interactive per-path merge |
| Gating validation | Template contract and readiness gate; the adopter hook is reported **R2** | Opt-in strict mode that gates on the hook |
| External activation | Locally configured, externally unverified, safe skips | GitHub doctor, then explicitly authorized configuration writes |
| Licensing | Explicit adopter-supplied decision; preserve provenance | SPDX, SBOM, and richer licence automation after legal review |
| Validation hook | Arbitrary directly runnable adopter executable at an extensionless path, with the legacy `.py` path accepted **R2** | Declarative command hooks, interpreter adapters, native Windows support |
| Documentation | Four managed durable operational documents; `CONTRIBUTING.md` is seed-once **R2** | Managed regions or adopter-supplied documentation fragments |
| GitHub diagnosis | Documentation only in this feature | Read-only GitHub configuration doctor |
| Maintenance | Manual Copier update and reconcile | Dependency and template maintenance automation |
| Renderer | Shared declarative Python standard-library compiler | Signed or sandboxed plugins if declarative contributions prove insufficient |
| Copier integration | Copier updates inputs; bootstrap reconciles derived output | Explicit GitHub-snapshot adoption into Copier lineage |
| Pre-bootstrap projects | `adopt` installs a manifest without overwriting existing files **R2** | Automated adoption during `copier update` |
| Secret-gated jobs | Read-only availability preflight before privileged job | Live activation diagnostics through the GitHub doctor |
| Project validation | Seed-once reusable workflow called by managed CI | Richer machine-readable validation metadata if needed |
| Capability evolution | Stable IDs with backward-compatible definitions | Versioned IDs and explicit migrations |
| Target selection | Current directory by default; optional `--target` | Authenticated repository-identity verification |
| Workflow validation | Bounded standard-library checks plus source `actionlint` | A portable structured workflow parser or GitHub-backed validation |
| Transaction scope | Journal and rollback only for planned paths | Hook sandboxing where supported by a selected toolchain |
| Transaction state | Git common directory when available, else in-tree **R2** | Configurable state location |
| Repository identity | Read live at runtime; no persisted owner/repository slug | Doctor-managed rename and transfer diagnostics |
| Template identity | Content fingerprints; Copier retains its own revision metadata | Signed release provenance |
| Seed ownership | Install once, then adopter-owned | Explicit opt-in reset or regeneration workflow |
| Schema evolution | Schema 1 remains backward-compatible throughout v1 | Explicit schema migrator in a later major version |
| Maintenance cleanup | Hash-checked declarative inventory, with a recorded opt-out **R2** | Authenticated source identity and richer provenance policy |
| Repeated apply | Equivalent mechanical and content fingerprints yield a validated no-op **R2** | Explicit full re-bootstrap after an ownership-aware migration design |
| Delivery | Five gated slices in one design **R2** | Independent designs per lifecycle once the catalog stabilizes |

## Approaches considered

### Approach A: Shared declarative Python compiler — selected

One Python 3.11 standard-library engine validates inputs, resolves capabilities, renders typed
artifacts, plans changes, and performs journaled mutations for both generation paths.

Benefits:

- one behavior and fixture matrix for GitHub and Copier outputs;
- portable local readiness without Nix or a package installation;
- explicit ownership, drift, and recovery semantics;
- capabilities can be data-driven without granting execution authority; and
- Copier remains the only version-aware update and merge tool.

Costs:

- the repository owns a deliberately small renderer and filesystem transaction layer;
- shared artifacts require declared composition slots; and
- arbitrary YAML semantics cannot be fully checked without another dependency.

### Approach B: Mirror conditionals in Copier and Python — rejected

Copier would render its generation path while a separate Python implementation would mutate GitHub
snapshots. This creates two sources of truth for profiles, capability dependencies, documentation,
and output ownership. Even strong fixtures would turn every extension into duplicated design work.

### Approach C: Run bootstrap as a trusted Copier task — rejected

Copier tasks require an explicit trust decision and do not apply to GitHub repository-template
creation. Making task execution mandatory would weaken the no-surprise generation contract and still
leave a separate GitHub path.

## Architecture

### Compiler pipeline

```text
input bundle + catalog + current manifest
                    |
                    v
       validate -> resolve -> render -> plan
                    |
                    v
        journaled planned-path mutation
                    |
                    v
      gating validation (contract + readiness)
                    |
                    v
        reported adopter project validation
```

The functional core returns immutable normalized models, diagnostics, and a complete filesystem plan.
The effectful edge reads source bytes, examines the target, writes the transaction journal, installs
the plan, invokes validation, and performs recovery.

Every mutating command is one instance of the same pipeline. `apply`, `add`, `restore`, `reconcile`,
and `adopt` differ only in their preconditions and in which parts of the persisted state they are
permitted to change. There is no second write path.

### Proposed source layout

```text
scripts/bootstrap-project.py

scripts/bootstrap/
  __init__.py
  cli.py            # argument parsing, exit codes, human-readable output
  inputs.py         # bundle loading, path confinement, normalization
  model.py          # immutable normalized models and fingerprints
  catalog.py        # capability and profile definition loading
  resolver.py       # profile expansion, dependency closure, collision checks
  renderer.py       # typed substitution, sections, slots, encoders
  planner.py        # target inspection, ownership classification, plan construction
  transaction.py    # journal, staging, backups, install, rollback
  diagnostics.py    # stable identifiers and rendering

.agentic-template/
  project.json                        # the manifest; bootstrap-managed output
  schemas/
  profiles.json
  core/
  capabilities/
    semantic-release/
    nix/
    cachix-publish/
    pr-agent-gemini/
  compatibility/capabilities-v1.json
  maintenance-artifacts.json
```

The exact module split may be refined in the implementation plan, but the dependency direction is
fixed: CLI and filesystem effects depend on the functional model; the model never imports CLI or
filesystem mutation code.

Consolidating the manifest into `.agentic-template/project.json` removes the near-identical
`.agentic-template.json` and `.agentic-template/` pair and gives the feature one namespace. Copier
excludes that one path rather than the directory.

### Transaction state directory

Transient recovery state is not project content and is never committed.

- When the target is a git working tree, state lives in `<git common dir>/agentic-template/`, located
  by invoking `git rev-parse --git-common-dir` in the target. Git already ignores this location, and
  `git clean -fdx` cannot destroy recovery evidence.
- Otherwise, state lives in `.agentic-template/state/`, and bootstrap requires that path to be
  ignored before it will mutate.

The directory holds `journal.json` and a `backups/` tree. The journal is created with `O_CREAT |
O_EXCL`; a pre-existing journal is both the interrupted-transaction signal and the mutual-exclusion
lock, so two concurrent mutations cannot interleave.

Recovery evidence for tracked files also exists in git itself. When backups are missing or their
hashes do not match the journal, `recover` fails with `BOOTSTRAP_RECOVERY_EVIDENCE_MISSING` and
directs the operator to `git status` and `git restore` for tracked paths rather than guessing.

### File ownership

| Class | Owner and behavior |
| --- | --- |
| Copier/template inputs | Engine, catalog, render sources, validators, skills, static contracts, and `NOTICE.md`; Copier updates and merges these on its path |
| Bootstrap-managed output | Manifest, compiled CI, selected capability artifacts, `.gitattributes`, and durable operational documents; exact hashes are enforced and `restore` recompiles them |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, `CONTRIBUTING.md`, root licence, and project-validation workflow; installed once and never regenerated in v1 |
| Adopter files | Product code, product documentation, unrelated workflows, and all files outside declared template ownership |
| Template-maintenance artifacts | Source tests, source workflow fixtures, historical source specs, and other paths in the maintenance inventory; excluded by Copier and conditionally removed from GitHub snapshots |

No path may belong to more than one class. Source validation rejects duplicate, nested, or
case-colliding ownership declarations.

`CONTRIBUTING.md` is seed-once rather than managed because contributor guidance is customized by
almost every project, and a managed, drift-fatal file that adopters are expected to edit converts a
normal action into a blocked repository. The four `docs/*.md` operational documents remain managed
because they describe template mechanics that the adopter does not author.

### Generation-path behavior

Copier configuration excludes bootstrap-managed output, seed-once adopter output, and declared
template-maintenance artifacts. Copier copies the engine, catalog, static contracts, and update
metadata. Initial bootstrap installs derived and seed-once files.

Because seed-once output is excluded rather than conditionally copied, the current
`_skip_if_exists: scripts/validate-project.py` entry is removed: seed-once ownership subsumes it, and
leaving both mechanisms in place would give one path two owners.

GitHub's repository-template operation copies the source tree unchanged. Initial bootstrap therefore
uses the maintenance inventory and known scaffold hashes to:

- replace seed placeholders with bundle content or reinstall them as scaffold;
- remove unselected capability artifacts;
- replace source CI with compiled project CI; and
- remove recognized template-maintenance artifacts.

Because the two paths start from different packaging, "recognized scaffold" is defined per path and
checked explicitly:

- **Copier path:** `.copier-answers.yml` exists, no manifest exists, and every seed-once path is
  either absent or byte-identical to the template's scaffold content.
- **GitHub path:** no `.copier-answers.yml` and no manifest exist, and every seed-once path is
  byte-identical to a known scaffold hash for a released template version.

Anything else is neither a scaffold nor a bootstrapped project; `apply` refuses it and names `adopt`.

Any unexpected bytes at a path proposed for replacement or deletion block the whole mutation.
Bootstrap never treats "looks like a template file" as sufficient evidence.

GitHub snapshots retain their one-time semantics. The presence of `.copier-answers.yml` identifies
the update-capable path, but bootstrap does not synthesize Copier lineage for a GitHub snapshot. A
consequence stated plainly in `docs/template-updates.md`: a GitHub-generated project receives no
further template updates to its managed artifacts, and adopting Copier lineage is deferred work.

### Source-target protection

Every command accepts optional `--target PATH` and otherwise uses the current directory. Every
command displays the normalized target.

Mutation refuses a Git remote that normalizes to the canonical template repository. Initial apply
also requires either a recognized scaffold or an equivalent-input manifest. Existing managed drift,
unsafe symlinks, Copier conflict evidence, or an unresolved transaction journal blocks mutation.

This is defense in depth rather than proof of repository identity. Template forks and repositories
without a remote remain the operator's responsibility. An authenticated identity check is a proposed
future change.

## Profile and capability model

### Profiles

| Profile | Snapshot expansion |
| --- | --- |
| `portable` | Core only |
| `release-automated` | `semantic-release` |
| `nix-enabled` | `nix` |
| `integrated` | `semantic-release`, `nix`, `cachix-publish`, `pr-agent-gemini` |
| `custom` | Exact list supplied in `bootstrap.json` |

Dependencies are resolved after profile expansion. The manifest stores both the profile expansion and
the final effective closure. Profiles never mutate existing projects.

### Capability definition

A capability definition declares:

- stable ID and human-facing description;
- dependency IDs;
- setting definitions using `string`, `boolean`, or `enum` types;
- validation constraints for every string used in a structured output context;
- external activation requirements;
- exclusively owned output paths;
- contributions to named typed slots in shared artifacts;
- documentation contributions; and
- fixture cases.

Definitions are data, not executable hooks. They may reference trusted static artifact and fragment
files shipped by the template. A definition cannot choose arbitrary target paths, execute a command,
load a Python object, access the network, or read environment variables.

Settings must be declared non-secret. Unknown capabilities, unknown settings, missing required
settings, settings for unselected capabilities, and values outside their declared constraints fail
validation.

### Stable-ID compatibility contract

Within v1, an existing capability ID may update implementation artifacts and documentation but may
not silently:

- add or remove a dependency;
- remove a setting;
- change a setting's type or meaning;
- make an optional setting required;
- change external-prerequisite semantics incompatibly; or
- transfer ownership of an existing path incompatibly.

Adding an optional setting with a deterministic default is compatible. A frozen compatibility fixture
records the v1 public surface. `validate-template.py` compares the live catalog with that fixture.
Incompatible evolution requires a new capability ID or a future explicit migration design.

`pr-agent-gemini` intentionally encodes the backend in the ID. A `backend` setting would be more
elegant, but changing a setting is reconfiguration, which v1 does not support; a separate ID per
backend keeps the only supported transition — add a new capability — available.

### V1 capability-to-artifact mapping

| Capability | Principal managed output and contributions | External activation |
| --- | --- | --- |
| `semantic-release` | `.releaserc`, reusable semantic-release workflow, and gated release job contribution | None beyond normal GitHub token permissions |
| `nix` | `flake.nix`, `flake.lock`, Nix setup action, and Nix CI check contribution | None |
| `cachix-publish` | Cachix configuration and publish contributions to Nix setup and CI; depends on `nix` and requires a non-secret cache-name setting | Existing Cachix cache plus `CACHIX_AUTH_TOKEN`; all Cachix-specific work skips when activation is unavailable while Nix continues uncached |
| `pr-agent-gemini` | `.pr_agent.toml`, review and trusted-command workflows, activation preflights, and setup documentation | `GEMINI_API_KEY` |

The source catalog owns the final exact path list. The table specifies the functional boundary rather
than permitting undeclared additional files.

## Input contracts

### Bootstrap input bundle

The bundle contains `bootstrap.json` and referenced ordinary files. Conceptually:

```json
{
  "schema_version": 1,
  "project": {
    "name": "example",
    "default_branch": "main"
  },
  "profile": {
    "id": "integrated"
  },
  "content": {
    "prd": {"mode": "file", "path": "content/prd.md"},
    "readme": {"mode": "file", "path": "content/readme.md"},
    "validation_hook": {"mode": "scaffold"},
    "security_policy": {"mode": "scaffold"},
    "contributing": {"mode": "scaffold"}
  },
  "licensing": {
    "mode": "provided-project-license",
    "path": "content/license.txt"
  },
  "capability_settings": {
    "cachix-publish": {
      "cache_name": "example"
    }
  }
}
```

For `custom`, `profile.capabilities` is mandatory. Other profiles reject that field so profile
semantics cannot be silently overridden.

The project name and default branch are mechanical settings, constrained to explicit ASCII character
classes so that no Unicode normalization enters fingerprinting. Repository owner/name is
intentionally absent because GitHub exposes current repository identity at runtime and persisted
slugs become stale after forks, transfers, and renames.

#### Content modes

Every content slot takes one of:

- `{"mode": "file", "path": "..."}` — adopter-authored bytes, copied verbatim;
- `{"mode": "scaffold"}` — the template's marked placeholder for that slot; or
- `{"mode": "adopted"}` — the file already exists and is left untouched. Valid only for `adopt`.

`scaffold` is what keeps bootstrap from becoming an authoring gate. An adopter can select a profile,
compile real CI, and start working within minutes, while readiness continues to fail loudly and name
exactly which slots remain unreplaced. This preserves REQ-001: an untouched generated project is
still deterministically unready.

Licensing has no scaffold mode. A repository whose licence file was invented by a tool is worse than
a repository with no licence at all.

README, PRD, SECURITY, `CONTRIBUTING.md`, and supplied legal text must be valid UTF-8 text. The
validation hook may be any regular executable file and is copied byte-for-byte to
`scripts/validate-project` with mode `0755`. Referenced paths are relative to the JSON file, must
remain inside the bundle after normalization, and may not traverse a symlink. Inline Markdown is not
supported in v1.

Licensing modes are:

- `retain-apache-2.0`, with no adopter licence path;
- `provided-project-license`, with required adopter legal text; and
- `private`, with a required adopter private notice.

### Additive capability input

```json
{
  "schema_version": 1,
  "add_capabilities": ["nix", "cachix-publish"],
  "capability_settings": {}
}
```

Settings may be supplied only for newly requested capabilities and newly resolved dependencies. A
setting for an existing capability must match the persisted value or the operation fails. Additions
never rewrite seed-once adopter files.

## Determinism contract

Byte-for-byte reproducibility is the feature's central promise, so its primitives are fixed here
rather than left to implementation. Changing any of them is a breaking template-contract change.

### Primitives

```text
sha256_hex(b)          = lowercase hexadecimal SHA-256 of the byte string b

canonical_json(v)      = json.dumps(v, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")

tagged(kind, payload)  = sha256_hex(b"agentic-template/1/" + kind + b"\n" + payload)

file_entry(path, b, m) = mode_token(m) + " " + sha256_hex(b) + " " + path + "\n"
                         encoded UTF-8, where mode_token is "100755" when the owner
                         execute bit is set and "100644" otherwise, and path is the
                         repository-relative POSIX path

tree_hash(kind, files) = tagged(kind, concatenation of file_entry(...) for every file,
                                sorted by the UTF-8 bytes of its path)
```

Domain tags prevent a value computed for one purpose from ever colliding with another.

### The four fingerprints

| Fingerprint | Construction | Covers |
| --- | --- | --- |
| `mechanical_fingerprint` | `tagged(b"mechanical", canonical_json(model))` | Project name, default branch, profile ID, explicit capability list, normalized settings, licensing mode |
| `content_fingerprint` | `tagged(b"content", canonical_json(slot_map))` | Each content slot's mode and, for `file`, its content hash |
| `template_source_fingerprint` | `tree_hash(b"template-source", inputs)` | Engine modules, catalog, core definitions, schemas, compatibility fixture, maintenance inventory |
| `selected_render_fingerprint` | `tagged(b"selected-render", canonical_json(selection))` | Core definitions, the tree hash of each effective capability definition, and normalized settings |

The selected render fingerprint excludes unselected capabilities so that unrelated catalog additions
do not create false project drift.

### Apply against an existing manifest

| Mechanical | Content | Managed state | Result |
| --- | --- | --- | --- |
| Equal | Equal | Healthy | Validated no-op, exit 0 |
| Equal | Equal | Drifted | `BOOTSTRAP_DRIFT_MANAGED`, next action `restore`, exit 1 |
| Equal | Differs | Any | `BOOTSTRAP_INPUT_CONTENT_CHANGED`: seed content is adopter-owned; edit the installed files in place, exit 1 |
| Differs | Any | Any | `BOOTSTRAP_INPUT_MECHANICAL_CHANGED`, next action `add` or the deferred reconfiguration lifecycle, exit 1 |

Splitting the fingerprint is what makes the third row expressible. With one conflated value, fixing a
typo in a README and re-running `apply` produced a diagnostic pointing at `add` or `reconcile`,
neither of which can install corrected seed content.

Neither fingerprint authorizes re-copying adopter-owned files.

### Byte-level output rules

For the same template-source fingerprint, normalized input model, referenced content bytes, profile
snapshot, and effective capability set, output is byte-for-byte identical:

- generated JSON uses `canonical_json` ordering and separators, with one trailing newline;
- generated text uses UTF-8 and LF endings;
- generated file modes are declared and installed as exactly `0644` or `0755`, independent of umask;
- adopter content bytes are preserved exactly;
- timestamps, random identifiers, working directories, hostnames, locale, and environment variables
  do not enter final output; and
- output path enumeration is sorted by path bytes.

Transaction journals may use unique temporary identifiers because they are transient recovery state,
not accepted generated output.

### Checkout portability

Hash comparison is only meaningful if git hands back the bytes bootstrap wrote. Bootstrap therefore
manages `.gitattributes`, declaring `* text=auto eol=lf` plus explicit `-text` entries for any binary
managed artifact. Without this, a `core.autocrlf=true` checkout reports every managed text file as
drift, which under the ownership rules would block every lifecycle operation.

Mode comparison uses only the owner execute bit, matching git's own index model, so differing umasks
and filesystems that do not preserve group and other bits do not produce false drift.

## Project manifest

`.agentic-template/project.json` is canonical mechanical state. Conceptually it records:

```text
schema_version
generation_path
template_source_fingerprint
project name and default branch
mechanical_fingerprint and content_fingerprint
content slot modes
profile ID and frozen profile capability list
explicit capability additions
effective dependency closure
normalized non-secret settings
licensing decision
external activation requirements
selected_render_fingerprint
maintenance_cleanup status
managed artifact paths, POSIX modes, and SHA-256 hashes
```

It does not contain:

- product prose or legal text;
- input source paths;
- repository owner/name;
- timestamps or machine-specific absolute paths;
- secrets or secret-presence claims;
- live GitHub configuration state; or
- hashes that make seed-once adopter content bootstrap-managed.

Revision 1's `compiler_contract_version` is removed. Engine and catalog identity is exactly what
`template_source_fingerprint` covers, and a second version field with no distinct behavior would have
been one more thing to keep consistent and nothing more.

On Copier projects, source version and update lineage remain in `.copier-answers.yml`; the manifest
does not duplicate or reinterpret Copier metadata. GitHub snapshots record content identity only and
do not invent a tag or source commit.

### Manifest schema lifetime

Every v1 engine must continue reading every valid schema-version-1 manifest. Compatible updates may
add optional fields with deterministic defaults but may not reinterpret existing fields or require a
new field from an old manifest. An unknown newer schema fails before any write. Schema migration is a
proposed future change requiring an explicit lifecycle and recovery design.

## CLI contract

```text
python3 scripts/bootstrap-project.py init --output PATH [--init-answers FILE]

python3 scripts/bootstrap-project.py status [--target PATH]

python3 scripts/bootstrap-project.py plan    --answers PATH/bootstrap.json [--target PATH]
python3 scripts/bootstrap-project.py apply   --answers PATH/bootstrap.json [--target PATH]
                                             [--leave-maintenance-artifacts]

python3 scripts/bootstrap-project.py plan-restore [--path PATH]... [--target PATH]
python3 scripts/bootstrap-project.py restore      [--path PATH]... [--target PATH]

python3 scripts/bootstrap-project.py plan-add --answers addition.json [--target PATH]
python3 scripts/bootstrap-project.py add      --answers addition.json [--target PATH]

python3 scripts/bootstrap-project.py plan-reconcile [--target PATH]
python3 scripts/bootstrap-project.py reconcile      [--target PATH] [--overwrite-drift]

python3 scripts/bootstrap-project.py adopt --answers PATH/bootstrap.json [--target PATH]

python3 scripts/bootstrap-project.py recover [--target PATH]
```

`init` creates a complete reviewable bundle only. With `--init-answers`, referenced source paths are
resolved relative to that seed document and copied into the output bundle. The initializer uses a
temporary sibling and installs the complete bundle only after validation.

`status` is read-only and always exits 0 unless it cannot read the target. It reports generation
path, frozen profile, explicit additions, effective capability set, unreplaced scaffold slots, every
drifted managed path, declared external activation requirements, and any pending transaction journal.
It is the command an adopter or agent runs first, and the one a diagnostic points at.

`restore` is the drift remedy. It recompiles bootstrap-managed paths from the persisted effective
capability set and the current template inputs. It never re-expands a profile, changes settings, or
touches seed-once or adopter files.

`reconcile` is `restore` plus Copier preconditions and a refuse-on-drift default;
`--overwrite-drift` gives it restore's overwriting behavior after `plan-reconcile` has displayed the
exact bytes at stake. Sharing one recompile implementation is what prevents the deadlock in which
drift blocks reconcile while a changed template blocks restore.

`--leave-maintenance-artifacts` is the single supported override for a maintenance inventory that no
longer matches. It skips cleanup, records `maintenance_cleanup: "skipped"` in the manifest, and is
reported by `status` and readiness. Without it, an adopter who committed one change before
bootstrapping a GitHub snapshot has no path forward at all.

All plan commands run every preflight possible without installing the target plan and report stable,
ordered path operations with old and new hashes. They do not invoke the adopter hook against a
partially rendered target. Mutating commands repeat preflight to avoid time-of-check/time-of-use
assumptions.

Exit codes are stable and match the existing readiness contract:

- `0`: success or deterministic no-op;
- `1`: user-correctable input, readiness, activation declaration, validation, or drift problem; and
- `2`: usage error, invalid catalog/engine contract, internal error, active recovery requirement, or
  recovery failure.

Human-readable diagnostics have stable identifiers, name the affected path or capability, and state
the next action. JSON diagnostics and GitHub annotations are proposed future changes.

## Rendering and composition

The renderer supports only:

- validated scalar substitution into declared typed contexts;
- whole optional sections controlled by normalized booleans;
- deterministic iteration over sorted declared values; and
- contributions to named slots with declared ordering and cardinality.

It does not evaluate expressions, import code, run shell commands, or allow capability data to choose
an arbitrary output path. Settings inserted into YAML, TOML, JSON, shell, or Markdown use a declared
context encoder or a value constraint that makes direct scalar insertion safe. A contribution that
does not match its slot type fails source validation.

Shared CI is assembled from core and selected capability contributions. The ordering key is part of
the slot contract and cannot depend on filesystem enumeration order. Contributions may declare job
dependencies only through symbolic job IDs resolved after all selected contributions are known.

## Transaction, drift, and recovery semantics

Mutation is transactional only for the exact planned filesystem paths.

1. Validate inputs, source definitions, target topology, old hashes, and rendered bytes.
2. Stage every new file without changing accepted target paths.
3. Create the journal with `O_CREAT | O_EXCL`, containing the operation list, expected hashes, backup
   locations, and transaction phase. A pre-existing journal aborts here and is both the
   interrupted-transaction signal and the concurrency lock.
4. Back up every replaced or deleted planned path.
5. Install operations in deterministic order using same-filesystem atomic replacements where
   available.
6. Run gating validation: `python3 scripts/validate-template.py` and
   `python3 scripts/check-project-readiness.py`.
7. On success, remove backups and the journal, then run the adopter hook and report its result.
8. On gating failure, restore all planned paths and retain clear diagnostics if restoration is not
   complete.

### Why the adopter hook does not gate

Revision 1 gated the transaction on the full `validate-repository.py`, whose third stage is the
adopter's own executable. That stage can fail because a dependency is not installed, a container is
not running, or a toolchain is absent — none of which say anything about whether bootstrap compiled
the project correctly. Rolling back a correct bootstrap for those reasons is both surprising and
contrary to the PRD's separation between template-owned and adopter-owned validation.

Bootstrap therefore gates on the deterministic, portable, standard-library stages it actually owns,
and runs the adopter hook afterwards as reported output with its own exit status shown. A future
`--strict` flag can restore gating for adopters who want it; it is not needed in v1.

Consequently a mutating command exits 0 when its transaction and gating validation succeed, even if
the reported adopter hook fails. The hook's status is printed as a labelled result and its failure is
reported as the adopter's next action. `python3 scripts/validate-repository.py` remains the command
whose exit status reflects the hook, and it is the one CI runs.

### Drift

A bootstrap-managed path whose bytes or execute bit differ from the manifest is drift. Drift is
reported by `status` and readiness, blocks `apply`, `add`, and `reconcile`, and is resolved by
`restore`. Drift is never silently overwritten or merged.

Seed-once and adopter files are never drift. They are expected to change.

### Recovery

An interrupted journal blocks `apply`, `add`, `restore`, `reconcile`, and `adopt`. `recover`
validates the journal and backups, restores the pre-operation state, and removes recovery state only
after verifying restored hashes. It never resumes forward.

The adopter-owned validation hook may create normal validation artifacts as allowed by the PRD.
Bootstrap does not attempt to enumerate or remove those artifacts, terminate external effects, or
claim whole-repository atomicity.

Planned target paths may not traverse a symlink. Existing symlinks at owned paths, parent/child path
ownership collisions, and non-regular files where a file is expected fail preflight.

## Reconciliation and adoption contract

### Reconciliation

The update-capable lifecycle is:

```text
copier update --vcs-ref <tag>
python3 scripts/bootstrap-project.py plan-reconcile
python3 scripts/bootstrap-project.py reconcile
python3 scripts/validate-repository.py
```

Copier owns source selection, version metadata, three-way merging, and conflict reporting for the
files it copies. Reconciliation reads the updated compatible compiler inputs and the existing
manifest, then recompiles only bootstrap-managed outputs.

Reconciliation requires:

- a schema understood by the new engine;
- a compatible capability catalog;
- no unresolved Copier conflicts;
- current managed bytes equal to old manifest hashes, unless `--overwrite-drift` is given; and
- the exact persisted effective capability set to remain resolvable without adding or removing an ID.

It may update implementations, selected documentation, render fingerprints, and managed hashes. It
may not re-expand a profile, modify seed-once or adopter files, select a template version, merge
drift, or invoke an implicit migration.

### Adoption

Projects generated before bootstrap existed have no manifest. They keep working unchanged: the
template-contract and readiness checks continue to accept them, and `scripts/validate-project.py`
remains an accepted hook path for the lifetime of v1, reported as deprecated rather than unready.
Declaring both hook paths is an error, `READINESS_HOOK_AMBIGUOUS`.

Keeping the legacy path accepted is what turns a breaking rename into a compatible transition.
`adopt` then becomes opt-in rather than forced:

- every seed-once slot must be declared `{"mode": "adopted"}` or supply content for a slot that is
  genuinely absent;
- the adopter states the licensing decision explicitly, because a tool cannot infer it from a file;
- the profile and capability selection describe what the project already has, and `plan-add` reports
  any resulting difference in managed artifacts before `adopt` writes them; and
- adoption installs the manifest and bootstrap-managed artifacts and nothing else.

Because Copier does not delete files it stops copying, an existing adopter who runs `copier update`
across the slice-2 release keeps their current CI until they choose to adopt.

## GitHub workflow architecture

### Stable project-validation boundary

Bootstrap-managed CI contains a direct reusable-workflow job named `Project validation` that calls:

```text
.github/workflows/project-validation.yml
```

The caller declares `contents: read`, passes no named or inherited secrets, and has no privileged
environment. The seeded adopter workflow:

- declares `on.workflow_call`;
- checks out without persisted credentials;
- runs on the supported GitHub-hosted runner;
- invokes `python3 scripts/validate-repository.py`; and
- uses no repository/environment secret and no write-capable permission.

Adopters may add jobs, matrices, and toolchain setup inside that workflow while preserving the
security and canonical-validation contract. GitHub constrains reusable-workflow permissions so they
can be maintained or reduced through the call chain, not elevated. The complete reusable workflow is
the release dependency.

The standard-library readiness checker performs bounded checks for the file's presence, recognizable
`workflow_call`, canonical command, absence of secret passing/references and privileged environment
declarations, and the managed caller's exact hash. It does not claim general YAML parsing. Source
fixtures run `actionlint` against the seeded workflow and every managed workflow. GitHub remains the
runtime syntax authority for adopter modifications; the proposed GitHub doctor adds live diagnosis.

### Secret-dependent capability jobs

Secret-dependent workflows separate authority into two jobs:

1. A read-only activation preflight reads the relevant secret only to derive a literal availability
   result and emits setup guidance when absent.
2. A job with the minimum required write permissions starts only when preflight returned available
   and normal event trust conditions pass.

The preflight distinguishes three states, because they need three different next actions:

| State | Condition | Guidance |
| --- | --- | --- |
| Available | Secret is non-empty | Proceed |
| Not configured | Secret is empty and the event can read repository secrets | Link the setup step in `docs/github-setup.md` |
| Unavailable in context | The event is a pull request from a fork | Explain that GitHub withholds secrets here and that this is expected, not missing setup |

Without the third state, every fork contribution reports as missing setup and adopters chase a
configuration problem that does not exist.

The PR Agent review and trusted-comment workflows apply this pattern to `GEMINI_API_KEY`. The Cachix
path skips all Cachix-specific setup and publishing when `CACHIX_AUTH_TOKEN` is absent, allowing Nix
validation to continue uncached. When the token is available, publishing is additionally gated on the
default branch event and successful Nix/project validation; an invalid or unavailable configured
cache then fails as an activation error rather than silently disabling Nix validation.

The preflight never exposes the secret value, copies it to a persisted artifact, or grants write
permissions merely to test availability. Missing activation is not project unreadiness.

### Release graph

When `semantic-release` is selected, release runs only on the configured default branch after:

- the complete adopter project-validation workflow;
- every selected managed capability check; and
- any core delivery-contract job required by the generated CI graph.

The release job retains its existing last-moment branch-tip eligibility check. If semantic-release is
not selected, no release workflow or release job is emitted.

### Template-source CI conformance

Compiled generated CI and the template's own hand-written `.github/workflows/ci.yml` are two
descriptions of the same delivery graph, and they will drift. The template source is effectively an
`integrated`-profile project, so a source fixture renders the `integrated` CI and asserts that the
source workflow declares the same job IDs, `needs` graph, and permissions, permitting only the
source's declared extra fixture steps.

This keeps the template dogfooding its own compiler output without forcing the source repository to
be a bootstrapped project.

## Validation boundaries

### `scripts/validate-template.py`

Validates reusable template machinery without assuming a bootstrapped adopter instance:

- bootstrap and manifest schemas;
- profiles and the complete capability catalog;
- dependency topology;
- setting declarations and defaults;
- output ownership and composition slots;
- renderer inputs and path safety;
- template-maintenance inventory; and
- stable capability compatibility fixtures.

It remains Python 3.11 standard-library-only and does not execute capability content or the adopter
hook.

### `scripts/check-project-readiness.py`

Validates one project instance. For a project with no manifest it behaves exactly as it does today,
plus the legacy hook-path allowance. For a bootstrapped project it additionally checks:

- manifest schema and internal topology;
- profile snapshot, explicit additions, and effective capability set;
- mechanical, content, template-source, and selected-render fingerprint structure;
- managed artifact modes and hashes;
- licensing decision and required preserved provenance;
- required durable documentation;
- validation hook presence and mode at either accepted path, but not both;
- seed-once project-validation workflow's bounded contract;
- external requirement declarations;
- `maintenance_cleanup` status; and
- absence of unreplaced required placeholders.

It reports a managed fingerprint mismatch as "reconcile required" only when individual managed hashes
still match. Individual hash mismatch is managed drift, reported with `restore` as the next action.

### `scripts/validate-project`

This is the canonical target path for the adopter-supplied arbitrary executable, with
`scripts/validate-project.py` accepted as the deprecated legacy path. It owns product-specific
validation, chooses its own toolchain, and may create normal validation artifacts. The aggregate
invokes it directly rather than through Python. Native Windows execution is not a v1 guarantee.

### `scripts/validate-repository.py`

Remains the canonical ordered boundary:

1. template contract;
2. project readiness; and
3. adopter project validation.

Stages 1 and 2 are what bootstrap gates on. Stage 3 is the adopter's. Source-only GitHub/Copier
fixtures and profile/capability matrix suites are not added to this portable generated-project
boundary.

## Licensing and provenance

Bootstrap requires one explicit licensing choice and accepts no licence default and no scaffold.

For `retain-apache-2.0`, the source Apache-2.0 text remains the root `LICENSE`. For
`provided-project-license` and `private`, the adopter-supplied legal text becomes root `LICENSE`. The
conservative minimum preservation design keeps `NOTICE.md` and retains the template Apache-2.0 text
under `LICENSES/Apache-2.0.txt` when it is no longer the root licence.

Before implementation fixes these paths, a licensing/provenance audit must:

- inspect every bundled skill's upstream licence and notice requirements;
- confirm whether the proposed Apache and notice locations satisfy redistribution obligations;
- identify any notice that must remain verbatim;
- define how adopter additions to notices are preserved; and
- update this design and an ADR if the required layout differs.

The audit blocks slice 1 only for the two modes that move the root licence. `retain-apache-2.0`
requires no relocation and no new notice layout, so slice 1 may ship with the other two modes gated
behind the audit if it is not yet complete. This keeps a legal review from blocking a mechanical
milestone.

The audit may strengthen preservation requirements but may not authorize bootstrap to invent project
legal terms or declare the resulting project legally valid. Bootstrap reports the selected mode and
preserved provenance as mechanical facts only.

## Durable adopter documentation

The following bootstrap-managed documents are rendered from core and selected capability fragments:

- `docs/delivery-workflow.md`: canonical validation, CI/release gates, review flow, and recovery;
- `docs/template-updates.md`: GitHub snapshot or Copier lineage, compatible reconciliation, drift,
  `restore`, and the plain statement that GitHub snapshots receive no further managed updates;
- `docs/capabilities.md`: frozen profile, additions, effective set, settings safe to display, and
  dependencies; and
- `docs/github-setup.md`: required secrets, the three preflight states including fork pull requests,
  Actions/ruleset steps, and the distinction between release and merge gates.

Each begins with a header naming it as bootstrap-managed and directing project-specific prose to
`CONTRIBUTING.md`, the README, or product documentation.

Capability addition and reconciliation update these documents atomically with their related
artifacts. The manifest hashes them. Direct edits are drift, reported by `status` and resolved by
`restore`. Managed regions and adopter fragments are proposed future changes.

## Template-maintenance inventory

`.agentic-template/maintenance-artifacts.json` declares paths that exist only to develop and release
the template source, such as source fixture suites, the Copier smoke workflow, and historical
template-source specs and plans.

The inventory records each path, expected source hash or tree hash, and whether the path is a regular
file or directory tree. It may not overlap a static, seed-once, adopter, or bootstrap-managed path.

- Copier excludes the declared inventory from generated projects. The current `copier.yml` exclude
  list is replaced by the generated inventory; its stale `tools` entry, which matches no existing
  path, is removed.
- GitHub snapshot bootstrap removes only entries whose complete bytes match the declared source
  shape.
- A modified, missing-with-children, unsafe, or partially matching entry blocks initial cleanup,
  reports the exact path, and names `--leave-maintenance-artifacts` as the supported override.
- Later `add`, `restore`, and `reconcile` operations never use the inventory to delete adopter files.

Source fixtures verify that both generation paths converge on the same generated-project contract
despite their different initial packaging.

## Diagnostics and failure semantics

Diagnostic identifiers are stable API-like strings grouped by subsystem, for example:

```text
BOOTSTRAP_INPUT_*
BOOTSTRAP_PROFILE_*
BOOTSTRAP_CAPABILITY_*
BOOTSTRAP_TARGET_*
BOOTSTRAP_DRIFT_*
BOOTSTRAP_TRANSACTION_*
BOOTSTRAP_RECOVERY_*
BOOTSTRAP_ACTIVATION_*
BOOTSTRAP_LICENSE_*
BOOTSTRAP_INTERNAL_*
```

Every user-correctable diagnostic includes the affected input, capability, or repository-relative
path and one next action. Every next action names a command that can actually resolve the condition;
a diagnostic whose only advice is "do not do that" is a defect. Diagnostics never include secret
values. Multiple independent preflight errors are returned in stable sorted order; mutation and
recovery failures stop at the first point where continuing could destroy evidence.

## Verification strategy

### Unit coverage

- Schema normalization and canonical serialization.
- Input path confinement, symlink rejection, and UTF-8 requirements.
- Content-mode handling for `file`, `scaffold`, and `adopted`.
- Profile expansion and exact dependency closure.
- Cycle, collision, type, slot, and compatibility detection.
- The four fingerprint constructions, including domain-tag separation and mode-token normalization.
- Deterministic renderers and typed setting encoders.
- Plan ordering, no-op classification, and the four-row apply matrix.
- Journal state transitions, `O_EXCL` mutual exclusion, and recovery validation.

### Tiered fixture matrix

The full cross-product is too slow for every pull request, so it is tiered.

**Pull-request tier**, targeting a few minutes: both generation paths across `portable` and
`integrated`; `retain-apache-2.0` and `provided-project-license`; one all-`scaffold` bundle and one
fully supplied bundle; the drift/restore cycle; one injected interruption and recovery; and
`actionlint` on the source and on generated workflows.

**Pre-release tier**, run at the release gate: both generation paths across all five profiles;
representative custom empty, single, dependent, and multi-capability sets; all three licensing modes;
every required capability setting variation; and missing/present external-activation structures
without real secrets.

Each case proves untouched failure where applicable, successful bootstrap, gating validation,
identical-input no-op, exact artifact presence/absence, stable manifest, and absence of source-only
maintenance files.

### Lifecycle coverage

- Add an independent capability.
- Add `cachix-publish` and resolve `nix`.
- Repeat a satisfied addition.
- Reject conflicting existing settings and removal.
- Modify one managed artifact and prove `add` and `reconcile` refuse it and `restore` resolves it.
- Restore a named subset and prove untouched managed paths are unchanged.
- Restore against updated template inputs and prove the render fingerprint is updated and reported.
- Perform a compatible Copier update, then reconcile.
- Change an unselected capability and prove no selected render drift.
- Present an incompatible capability fixture or unknown manifest schema and prove zero writes.
- Inject failure before the journal, during each mutation phase, during gating validation, and during
  rollback.
- Prove a failing adopter hook does not roll back a successful bootstrap.
- Recover an interrupted transaction and verify exact pre-operation planned-path hashes.
- Prove a second concurrent mutation is refused by the existing journal.
- Let the adopter hook create an unrelated validation artifact and prove rollback leaves it alone.
- Adopt a project built from the previous template release and prove no seed-once file changes.
- Check out a managed project with `core.autocrlf=true` and prove no false drift.

### Workflow and security coverage

- Run `actionlint` on source and every generated workflow fixture.
- Assert the managed caller passes no secrets and has read-only permissions.
- Assert the seeded project-validation workflow invokes the canonical boundary and has no privileged
  environment.
- Assert release depends on the full project-validation call and selected checks.
- Assert missing Gemini/Cachix secrets create successful skip guidance, and that a fork pull request
  reports the third preflight state rather than missing configuration.
- Assert privileged PR Agent or Cachix publishing jobs cannot start when preflight is false.
- Assert the source CI conforms structurally to the `integrated` render.
- Assert persisted checkout credentials and real credential-looking values are absent.

### Release gates

Each slice's gate is listed in "Delivery slices and release gates". Every gate additionally requires:

- repository formatting, linting, tests, builds, and template-source fixtures pass;
- the PRD and Copier ADR reflect the boundary delivered by that slice;
- security/workflow validation passes; and
- verification-before-completion and substantive code review find no unresolved required issue.

The licensing/provenance audit blocks the two licence-relocating modes, not slice 1 as a whole.

## Compatibility and migration

### Requirement delta

| Requirement | Change |
| --- | --- |
| REQ-001 detect incomplete setup | Retained and extended: readiness must name unreplaced `scaffold` slots specifically, so a scaffolded project is still deterministically unready |
| REQ-002 one validation command | Retained; the aggregate gains the extensionless hook path with the legacy path accepted |
| REQ-003 gate releases on project validation | Retained; the gate becomes a compiled contribution present only when `semantic-release` is selected |
| REQ-004 verify generated behavior from source | Extended to the tiered fixture matrix and both generation paths across profiles |
| REQ-005 preserve generation-path ownership | Extended with the five ownership classes and the drift contract |
| REQ-006 portable, least-privileged template validation | Retained unchanged; bootstrap remains standard-library-only |
| New: deterministic bootstrap | The compiler, its input contract, and byte-for-byte output guarantees |
| New: capability selection | Profiles, catalog, and the absence of unselected artifacts |
| New: managed-artifact ownership and drift | Manifest, hashes, `restore`, and the refusal to merge |
| New: activation is not readiness | Secret preflight, safe skips, and the manifest recording requirements only |

The PRD's compatibility quality attribute requires that a change making a conforming project unready
ship as a breaking template-contract change with migration notes. This design deliberately avoids
triggering it: no existing project becomes unready, because the legacy hook path stays accepted and
projects without a manifest keep their current behavior.

### What existing adopters experience

| Situation | Behavior |
| --- | --- |
| Existing project, no action taken | Unchanged; canonical validation still passes |
| Existing Copier project runs `copier update` | Receives engine and catalog inputs; keeps its current CI and hook because Copier does not delete files it stops copying |
| Existing project runs `status` | Reports "not bootstrapped" and names `adopt` |
| Existing project runs `adopt` | Gains a manifest and managed artifacts; no seed-once file is touched |
| New project | Uses `init`, `plan`, `apply` from the start |

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A catalog change silently changes an old snapshot | Persist exact sets, freeze compatibility fixtures, and block incompatible reconciliation |
| Copier and bootstrap both modify one output | Exclude derived/seed-once paths from Copier and validate ownership collisions |
| GitHub bootstrap deletes adopter work | Delete only declared exact-hash scaffold or maintenance paths; otherwise fail the whole plan |
| A managed file is edited directly | Detect via manifest hashes and resolve with `restore` |
| Drift leaves the project permanently blocked | `restore` shares the recompile path with `reconcile`, so no combination of drift and template change is unresolvable |
| A crash leaves mixed output | Durable journal in the git common directory, backups, blocked mutation, and explicit rollback-only `recover` |
| Two mutations run at once | `O_EXCL` journal creation is the lock |
| A correct bootstrap is discarded | Gate only on template-owned deterministic validation; report the adopter hook |
| The adopter hook creates side effects | Limit the transaction claim to planned paths and never delete unknown hook artifacts |
| False drift from line endings or umask | Managed `.gitattributes` and execute-bit-only mode comparison |
| Bootstrap becomes an authoring gate | `scaffold` content mode compiles a real project before prose exists |
| Fixing a typo appears impossible | Split fingerprints so content-only differences get their own diagnostic |
| Missing secrets fail every PR | Read-only activation preflight and successful skip guidance |
| Fork PRs look like broken setup | Third preflight state distinguishing context from configuration |
| A privileged job starts merely to check a secret | Separate preflight and privileged jobs with dependency-gated start conditions |
| Manifest records stale external state | Persist requirements only; inspect live state in workflows or the future doctor |
| Repository slug becomes stale | Read live GitHub context and omit owner/repository from the manifest |
| GitHub snapshot lacks source commit lineage | Record content fingerprints without inventing release metadata |
| Compiled CI drifts from the template's own CI | Source conformance fixture against the `integrated` render |
| A handwritten YAML checker overclaims correctness | Bounded policy checks, source `actionlint`, GitHub runtime validation, and explicit documentation |
| Managed documentation blocks customization | `CONTRIBUTING.md` is seed-once; managed documents point to adopter-owned prose |
| Licence replacement loses obligations | Mandatory conservative preservation plus an audit that blocks only the relocating modes |
| Existing adopters are stranded | Legacy hook path accepted, manifest-free projects unchanged, opt-in `adopt` |
| The feature never ships | Five gated slices, each producing a validated generated project |
| Declarative rendering becomes too restrictive | Add typed slots first; consider signed/sandboxed plugins only through a future design |

## Proposed future changes

These options were discussed and intentionally deferred. They are viable extension proposals, not
rejected alternatives.

### Bootstrap experience and product guidance

- One-command interactive initialize-and-apply convenience over the same plan/apply engine.
- Inline prose fields with explicit escaping and review behavior.
- Guided PRD authoring without treating generated prose as authoritative until adopted.
- Stack presets and recommendation logic without adding an implicit engine default.
- Persisting richer initialization answers to regenerate selected documentation.
- Opt-in reset or regeneration of seed-once files after an ownership-aware migration design.
- `apply --strict` gating the transaction on the adopter hook.

### Capability and profile lifecycle

- A broader first-party catalog.
- Third-party capability registries with signing, provenance, compatibility, and trust policy.
- Live profiles or profile-plus-override policies explicitly distinct from snapshots.
- Capability removal, replacement, rebasing, and full reconfiguration.
- Versioned capability IDs and explicit capability/manifest migrations.
- Managed document regions or adopter-provided documentation fragments.
- A signed or sandboxed plugin model if declarative fragments and typed slots prove insufficient.

### Validation and portability

- Declarative validation-command lists and generated hook adapters.
- Interpreter adapters and native Windows support.
- A portable structured GitHub workflow parser.
- Structured JSON diagnostics and GitHub Actions annotations.
- Hook sandboxing for selected environments.

### GitHub and external activation

- A read-only GitHub configuration doctor covering Actions availability, current default branch,
  required secrets, workflow activation, rulesets, and required checks.
- Authenticated repository-identity and rename/transfer diagnostics.
- Explicitly authorized secret, ruleset, or branch-protection writes in a separate operator tool.
- Rich live activation status without persisting secret values.

### Distribution and maintenance

- Dependency and template maintenance automation that opens reviewable update PRs with reconciliation
  previews and compatibility evidence.
- Explicit adoption of GitHub snapshots into Copier update lineage.
- Signed template-release provenance.
- SPDX, SBOM, and richer licence/provenance automation.
- Copier-native conditional rendering for a future simpler template shape where one generation path
  is sufficient.
- Explicit opt-in trusted Copier tasks for workflows where users knowingly accept task execution.

The recommended follow-up order is deterministic bootstrap, then the read-only GitHub configuration
doctor, then dependency and template maintenance automation.

## Rejected alternatives

These choices conflict with approved v1 invariants or duplicate selected responsibilities. They are
not implied roadmap items merely because they are absent from v1.

- Ordinal profiles such as minimal/default/full, because their meaning is unclear and changes over
  time.
- An implicit mutation-engine profile default.
- Re-expanding a stored snapshot profile during update or reconciliation.
- Accepting, persisting, logging, or inferring secret values in bootstrap.
- Letting bootstrap itself perform unapproved external configuration writes.
- Persisting live activation status as repository truth.
- Persisting repository owner/name when it can be read at runtime.
- Silently overwriting or merging bootstrap-managed drift.
- Leaving drift with no supported remedy.
- Gating the bootstrap transaction on the adopter-owned validation hook.
- Requiring complete product prose before a project can be compiled.
- Renaming the validation hook without accepting the legacy path.
- A second manifest version field that duplicates the template-source fingerprint.
- Treating capability removal as reconciliation.
- A custom version-aware updater that competes with Copier.
- Parallel Copier and Python rendering implementations.
- Mandatory trusted Copier task execution.
- Restricting the adopter validation hook to Python.
- Requiring `--target` solely as an operator-attention mechanism.
- A handwritten general-purpose YAML parser presented as complete semantic validation.
- Legal boilerplate authored by bootstrap or a claim that a selected licence is legally sufficient.
- Delivering the whole compiler, lifecycle, and documentation set as one undivided release.

## Required follow-up documents

Implementation must update or add:

- `docs/prd.md`, promoting the approved bootstrap behavior into authoritative requirements per the
  requirement-delta table;
- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs;
- an ADR for the capability compiler and ownership model if the implementation plan confirms the
  boundary is architectural;
- the licensing/provenance audit record and any resulting ADR;
- `docs/project-readiness.md`, reflecting the extensionless hook path, scaffold slots, and `status`;
- generated adopter documentation described above; and
- source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open for v1.

The licensing/provenance audit is a blocking implementation gate for `provided-project-license` and
`private`. If it changes the proposed `LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design
must be amended and reconfirmed before licence-writing implementation proceeds. `retain-apache-2.0`
is not blocked, so slice 1 can proceed while the audit is in progress.

## References

- `docs/prd.md`
- `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md`
- `docs/specs/2026-08-05-deterministic-project-bootstrap/design.discovery-draft.md`
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/)
- [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
