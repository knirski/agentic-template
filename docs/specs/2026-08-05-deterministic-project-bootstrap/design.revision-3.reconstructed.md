# Deterministic Project Bootstrap with Capability Profiles

**Status:** Revision 3, assembled for final confirmation
**Date:** 2026-08-05
**Planning mode:** Spec-backed Plan
**Supersedes:** `design.discovery-draft.md` and `design.revision-2.md` in this directory

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

V1 ships as one release, built in five reviewable implementation batches. It is a breaking
template-contract change, released with migration instructions.

This design is an explicit product decision that extends `docs/prd.md`. Implementation must update
the PRD, `CONTEXT.md`, and ADR 0001 before changing runtime behavior so those authoritative documents
describe the approved compiler and ownership boundary.

## Revision history

Revision 1 (`design.discovery-draft.md`) was a complete discovery record. Revision 2
(`design.revision-2.md`) closed ten lifecycle gaps and introduced delivery phasing, but introduced
defects of its own. Revision 3 corrects those defects.

### Decisions this design reverses from revision 1

These are deliberate reversals of approved revision 1 decisions, not clarifications. Each is listed
here so that approving this design is an explicit act.

| Revision 1 decision | Revision 3 decision | Why |
| --- | --- | --- |
| A bundle must supply complete content for every slot | Every slot is an adopter file or an explicit `scaffold` placeholder | Requiring a finished PRD before a project can compile made bootstrap an authoring gate and regressed today's first-run experience |
| Successful `apply` makes the full canonical validator pass | `apply` installs, then reports; a failing adopter hook means exit 1 and "not locally ready", never rollback | The hook can fail because a toolchain is absent, which says nothing about whether bootstrap compiled correctly, and rolling back after the hook may have created artifacts is unsafe |
| Reconciliation writes only paths whose bytes match old manifest hashes | `reconcile --overwrite-drift` may overwrite drift after an explicit preview | Without an escape, drift plus a changed template is unresolvable |
| The lifecycle is initial bootstrap plus additive capability changes | Adds `restore`, a same-contract drift repair | Revision 1 detected drift, blocked on it, and provided no mechanism to resolve it |
| Partial bundles and a finalize phase are future work | `scaffold` is in v1; no finalize phase is needed | Slot completion is derived from the files, so there is no state to transition |

### Corrections revision 3 makes to revision 2

| Revision 2 defect | Correction |
| --- | --- |
| `restore` recompiled from current template inputs and advanced fingerprints, bypassing reconciliation's preconditions; `restore --path` could bless a mixed old/new render | `restore` operates strictly within the recorded contract and writes only bytes the manifest already certifies; `reconcile` is the only operation that advances template or render identity |
| `plan-reconcile` could not preview `--overwrite-drift` | Both commands accept the flag |
| US-8 permitted drift overwrite and forbade it four lines apart | Resolved in favor of the explicit, previewed override |
| A mutating command exited 0 when the adopter hook failed, contradicting `CONTEXT.md`'s definition of project readiness | Exit 0 means the full canonical command succeeded; hook failure is exit 1 with the installation retained |
| `scaffold` slot completion had no defined derivation, so the manifest's recorded mode read as current state | Slot completion is derived from placeholder markers in the files; the manifest's content record is bootstrap-time input identity only |
| A legacy `.py` hook path was accepted for the lifetime of v1, and `adopt` was added half-specified | Single canonical hook path, released as a documented breaking change; `adopt` removed |
| Slices claimed to be independently releasable, but later slices added artifacts that readiness required, making earlier manifests unready | Five implementation batches inside one release; no per-slice public release, no manifest feature levels |
| The apply matrix compared only mechanical input, content input, and managed state, so an `apply` after `copier update` reported a validated no-op | Replaced by an ordered decision procedure that also compares template-source and render identity |
| `selected_render_fingerprint` covered a hand-maintained subset that omitted `default_branch`, which appears in generated CI | Derived from the complete normalized render IR |
| `.gitattributes` was bootstrap-managed and therefore drift-fatal, recreating the ownership trap that moved `CONTRIBUTING.md` to seed-once | Not installed at all; hash comparison normalizes declared text artifacts to LF internally |
| Transaction state used the git common directory, which linked worktrees share, so one journal serialized unrelated worktrees and `recover` could target the wrong checkout | Worktree-specific administrative path, with the target's identity recorded in the journal |
| The non-git state fallback was justified by being ignored, but `git clean -x` removes ignored files | No implicit fallback; an explicit `--state-dir` outside the target is required when the target is not a git worktree |
| The licensing audit was scoped to block only the two licence-relocating modes | The audit blocks every distribution mode, because bundled-skill obligations apply to all redistribution regardless of root licence |
| Determinism primitives left path encoding, JSON value domain, symlinks, and empty directories unspecified | All specified below |
| The secret preflight claimed to distinguish "not configured" from "unavailable", which an empty secret cannot prove | Two states, with event-specific likely causes; authoritative diagnosis deferred to the GitHub doctor |
| `maintenance_cleanup: "skipped"` recorded no paths and defined no follow-up | Records retained paths and transfers them to adopter ownership |
| `status` always exited 0 | Exit 2 for a corrupt manifest or invalid internal state |
| Source-CI conformance had no normalizer or allowlist | Both specified |
| A `scaffold` bundle deliberately fails readiness, and readiness gated the transaction, so every scaffold apply would have rolled itself back — and every `add`, `restore`, or `reconcile` on a project with any unreplaced slot would have done the same | Gating validation is scoped to findings the operation introduced, plus a narrow declared-scaffold exemption for initial apply |

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
- Keep exactly one operation able to change a project's template or render identity.
- Make missing external secrets safe and actionable instead of causing noisy workflow failures.
- Produce durable adopter-facing delivery, update, capability, and GitHub setup documentation.
- Allow new declarative capabilities without changing the resolver or transaction engine.

## Non-goals

- Inventing or judging product requirements, README content, security policy, or legal terms.
- Judging whether the adopter's validation hook is substantively adequate for the product.
- Rolling back a completed, mechanically valid installation because the adopter hook failed.
- Accepting, storing, discovering, or writing secrets during bootstrap.
- Authoritatively diagnosing whether a repository secret is configured.
- Mutating GitHub repository settings, rulesets, branch protection, or external services.
- Capability removal, replacement, or arbitrary reconfiguration in v1.
- Re-expanding a stored snapshot when a named profile changes later.
- Migrating incompatible capability or manifest schemas.
- Adopting a project that was generated before bootstrap existed.
- Reimplementing Copier's version selection, update merge, or conflict behavior.
- Providing native Windows execution guarantees.
- Providing a general-purpose template language, executable capability plugins, or trusted Copier
  tasks.
- Proving the semantic validity of an arbitrary adopter-owned GitHub Actions workflow with a
  standard-library-only checker.
- Rolling back filesystem artifacts or external side effects created by the adopter validation hook.

## Implementation batches

V1 is one release with one release gate. The work is divided into five reviewable implementation
batches so that no single change contains the whole system. A batch is a review boundary, not a
public version: intermediate batches are not released, do not define their own manifest
compatibility level, and are not expected to satisfy the full readiness contract on their own.

Revision 2 treated these as independently releasable slices. That is unworkable, because a later
slice adds artifacts that readiness requires, which would make manifests written by an earlier slice
unready — a violation of the schema-1 compatibility rule that no compatible update may require a new
field from an old manifest. Honoring that rule per slice would require explicit manifest feature
levels, which costs more than the phasing buys.

| Batch | Contents | Evidence before merge |
| --- | --- | --- |
| 1 | Schemas, pure normalized models, the four fingerprints, ownership declarations, profile and capability definition schemas, and their fixtures | Unit coverage for normalization, canonical serialization, fingerprint construction, and ownership collision detection |
| 2 | The deterministic compiler: resolver, renderer, typed slots, and planner. No filesystem mutation | Byte-identical renders across repeated runs, profile expansion and dependency closure, cycle/collision/type/slot detection, plan ordering |
| 3 | Transaction engine, journal, backups, `recover`, `status`, and same-contract `restore` | Injected failure at every phase, interrupted-journal blocking, concurrent-mutation refusal, drift detection and repair |
| 4 | Generation-path integration, `init`/`plan`/`apply`, validation-boundary changes, Copier exclude configuration, core-rendered CI, seed-once installation | Both generation paths produce a `portable` project that passes canonical validation from a fully supplied bundle, and one that installs and exits 1 naming remaining slots from a `scaffold` bundle; the apply decision procedure; maintenance cleanup |
| 5 | Capability catalog, the four capabilities, all five profiles, their slot contributions, secret preflights, durable documentation, `add`, and `reconcile` | Full profile matrix, `actionlint`, source-CI conformance, activation skips, additive lifecycle, Copier update then reconcile |

The whole slot contract — ordering, contribution types, cardinality, collision rules, and symbolic
job dependencies — is designed in batch 2 even though its only consumer until batch 5 is
core-rendered CI with an empty contribution set. Batch 5 adds contributors, not a second
compilation mechanism.

### Release gate

Before the single v1 release:

- both generation paths pass the full profile matrix;
- Copier update coverage proves seed-once preservation and derived reconciliation;
- the drift, recovery, and concurrency suites pass;
- `actionlint` passes on the source and every generated workflow fixture;
- the template source's own CI structurally conforms to the `integrated` render;
- the licensing and provenance audit is complete;
- the PRD, `CONTEXT.md`, and ADR 0001 reflect the approved boundary, including the breaking hook-path
  change and its migration instructions;
- repository formatting, linting, tests, builds, and template-source fixtures pass; and
- verification-before-completion and substantive code review find no unresolved required issue.

## Users and workflows

### US-1: Prepare a reviewable input bundle

As a template adopter, I want an initializer to collect my choices and content into a reviewable
bundle without touching the project so that generation inputs can be inspected, versioned, and
reused.

Acceptance criteria:

- `init` supports interactive collection and a pre-seeded non-interactive input.
- It requires an explicit profile selection; the interactive flow may recommend `portable` but the
  engine has no default profile.
- It requires an explicit decision for every content slot: an adopter file, or `scaffold`.
- It requires an explicit licensing decision, which has no `scaffold` mode and no default.
- It copies referenced content bytes into a self-contained bundle and writes relative references in
  `bootstrap.json`.
- It does not mutate a generated project or perform external operations.
- It refuses a non-empty output location instead of silently replacing a bundle.

### US-2: Bootstrap a generated project deterministically

As an adopter, I want to preview and explicitly apply a bundle so that the result is ready without
manual placeholder replacement.

Acceptance criteria:

- `plan` reports the exact create, replace, and delete set without mutation.
- `apply` performs initial bootstrap only from recognized generated-project scaffolding.
- Successful apply makes `python3 scripts/validate-template.py` succeed and makes
  `python3 scripts/check-project-readiness.py` report no finding other than unreplaced-placeholder
  findings for the slots the applied bundle declared `scaffold`.
- `apply` then runs the adopter hook and reports its result. Neither a failing hook nor an expected
  scaffold finding rolls back the installation.
- `apply` exits 0 only when the complete canonical command would succeed — so a bundle with any
  `scaffold` slot exits 1, naming the slots that still hold placeholders.
- Any exit-1 outcome after installation states plainly that bootstrap files were installed and that
  the repository is not yet locally ready.
- The project-validation hook is installed at the toolchain-neutral path `scripts/validate-project`.
- The result does not depend on Nix unless `nix` is selected.
- The manifest records a mechanical fingerprint and a content fingerprint, without storing prose or
  source paths.
- Reapplying an equivalent bundle against an unchanged template and healthy managed state returns a
  validated no-op.
- Every other combination of input, template, render, and managed state produces its own distinct
  diagnostic naming the one operation that can resolve it.

### US-3: Select an intent-based snapshot profile

As an adopter, I want a named shortcut with stable creation-time meaning so that later template
changes cannot silently add integrations to my project.

Acceptance criteria:

- V1 defines `portable`, `release-automated`, `nix-enabled`, `integrated`, and `custom`.
- A selected named profile expands exactly once and the expanded list is persisted.
- `custom` requires an exact explicit capability list.
- Reconciliation uses the persisted list and never re-expands the stored profile name.
- A profile definition change affects only later bootstraps.

### US-4: Materialize only the effective capabilities

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

### US-5: Preserve product, licensing, and provenance ownership

As an adopter, I want product prose and legal choices to remain mine while template provenance is
retained so that mechanical regeneration cannot overwrite product decisions.

Acceptance criteria:

- README, PRD, validation hook, SECURITY policy, `CONTRIBUTING.md`, root licence, and the
  project-validation workflow become adopter-owned after their initial installation.
- The manifest contains only normalized mechanical state and hashes.
- Licensing selection is mandatory and explicit.
- Bootstrap authors no legal terms and makes no legal-validity claim.
- Template Apache-2.0 text and bundled-skill provenance remain available in every licensing mode.
- The licensing and provenance audit completes before release, for every licensing mode.

### US-6: Add capabilities without changing profile provenance

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

### US-7: Configure external integrations without secrets

As an adopter, I want locally complete integration files even before external secrets exist so that
readiness is distinct from activation.

Acceptance criteria:

- Bootstrap never accepts or persists secret values.
- The manifest records activation requirements, not live activation status.
- Missing secrets produce successful workflow skips and actionable job summaries.
- A read-only preflight job determines availability before any job with write permissions starts.
- The preflight reports availability and, when unavailable, the likely causes for that event type.
  It does not claim to know whether a secret is configured.
- Runtime secret values are never emitted through logs or persisted outputs.
- Durable documentation identifies every manual activation step.

### US-8: Reconcile derived artifacts after Copier update

As a Copier adopter, I want updated compatible compiler inputs to re-render derived outputs without
overwriting my project files or duplicating Copier's merge semantics.

Acceptance criteria:

- The documented sequence is `copier update`, bootstrap `reconcile`, then canonical validation.
- Copier selects and merges template inputs; reconciliation only compiles derived outputs.
- Reconciliation preserves the exact effective capability set and normalized settings.
- It is the only operation that may advance `template_source_fingerprint` or
  `selected_render_fingerprint`.
- It neither adds nor removes capabilities, changes settings, re-expands profiles, nor merges files.
- Copier conflict evidence or an incompatible catalog blocks all writes.
- Managed drift blocks all writes unless `--overwrite-drift` is given, in which case
  `plan-reconcile --overwrite-drift` must first display every byte that would be replaced.
- GitHub-generated projects remain one-time snapshots without Copier update lineage, and their
  documentation states plainly that managed artifacts receive no further template updates.

### US-9: Extend the capability catalog declaratively

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

### US-10: Retain durable adopter documentation

As an adopter, I want operational documentation outside my product README so that delivery and
template knowledge survives normal product customization.

Acceptance criteria:

- Bootstrap produces `docs/delivery-workflow.md`, `docs/template-updates.md`,
  `docs/capabilities.md`, and `docs/github-setup.md`.
- The documents reflect generation path, frozen profile, effective capabilities, external
  prerequisites, validation, update, drift, and recovery behavior.
- Capability additions and reconciliation update affected managed documents in the same transaction
  as code and workflow artifacts.
- Direct edits are treated as managed drift, reported by `status` and readiness, and resolved by
  `restore`.
- Each document's header names itself as managed and points to `CONTRIBUTING.md` and the README for
  project-specific prose.

### US-11: Extend project validation without editing managed CI

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

### US-12: Recover interrupted mutations

As an adopter, I want an interrupted mutation to be detectable and recoverable so that bootstrap
does not leave managed ownership ambiguous.

Acceptance criteria:

- Every mutation records a durable journal before replacing target paths.
- The journal records the normalized target identity, and `recover` refuses a target that does not
  match it.
- A gating-validation or write failure automatically restores planned paths when possible.
- An interrupted journal blocks later mutations.
- `recover` explicitly rolls back to the pre-operation state and never resumes a partial plan.
- Recovery evidence survives `git clean -fdx` in a git working tree.
- Two concurrent mutations cannot interleave.
- Hook-created artifacts outside the planned path set are permitted by the PRD and are not removed by
  recovery.

### US-13: Resolve managed drift

As an adopter, I want a supported way to return an edited managed artifact to its compiled state so
that an accidental edit does not permanently block every lifecycle operation.

Acceptance criteria:

- `status` reports every drifted managed path without mutation.
- `plan-restore` shows the exact bytes that would be replaced, and `restore` applies the change
  transactionally.
- `restore` operates strictly within the recorded template contract: it requires the current
  `template_source_fingerprint` and the recomputed `selected_render_fingerprint` to equal the
  manifest, and it writes only bytes whose hash and mode already equal the manifest's record.
- `restore` never changes any fingerprint, capability state, setting, or other global manifest
  identity, and never touches seed-once or adopter files.
- A template-source or render mismatch causes `restore` to refuse and name `reconcile`.
- `restore --path` restores a named subset, and the operation is refused when a named path is not
  bootstrap-managed.

## Decision record

The following table records the approved answer to each material design question and the extension
path retained for viable deferred work.

| Topic | V1 decision | Proposed future change, if viable |
| --- | --- | --- |
| Bootstrap result | Mechanical installation and product readiness are reported separately; exit 0 requires both | Staged readiness reporting |
| Content completeness | Every slot is an adopter file or an explicit `scaffold` placeholder | Inline prose fields where review and escaping rules are sufficient |
| Slot completion | Derived from placeholder markers in the files, never from the manifest | Structured completion metadata if derivation proves insufficient |
| Profile semantics | Named profiles are one-time snapshots | Explicit live profiles or profile-plus-override policies |
| Initial catalog | Current integrations only, behind a generic catalog | Broader first-party catalog and stack presets |
| Catalog ecosystem | Repository-local trusted definitions | Third-party registries with provenance and trust policy |
| Profile names | Intent-based names | More intent-specific profiles when justified by real usage |
| Selection default | No engine default; initializer may recommend `portable` | Guided recommendations based on declared project characteristics |
| Persisted ownership | Mechanical state in the manifest; prose in adopter files | Richer persisted initialization answers for documentation regeneration |
| Content input | Referenced ordinary files in a self-contained bundle | Inline prose fields with explicit escaping |
| Interaction | Initialize a bundle, then explicitly plan/apply | One-command interactive convenience layered on the same engine |
| Lifecycle | Initial bootstrap, additive changes, and same-contract drift repair | Removal, replacement, rebasing, and full reconfiguration |
| Drift remedy | `restore`, strictly within the recorded contract | Interactive per-path merge |
| Template identity changes | Only `reconcile` may advance template or render identity | None; this is a load-bearing invariant |
| Gating validation | Template contract and readiness gate the transaction; the hook is reported | Opt-in strict mode that gates on the hook |
| External activation | Locally configured, externally unverified, safe skips | GitHub doctor, then explicitly authorized configuration writes |
| Secret diagnosis | Available, or unavailable with likely causes | Authoritative configuration diagnosis in the GitHub doctor |
| Licensing | Explicit adopter-supplied decision; preserve provenance; audit gates all modes | SPDX, SBOM, and richer licence automation after legal review |
| Validation hook | One canonical extensionless path; the rename is a documented breaking change | Declarative command hooks, interpreter adapters, native Windows support |
| Pre-bootstrap projects | Not adopted; migrate by renaming the hook and bootstrapping fresh | An adoption lifecycle with preview and collision handling |
| Documentation | Four managed durable operational documents; `CONTRIBUTING.md` is seed-once | Managed regions or adopter-supplied documentation fragments |
| Line endings | Hash comparison normalizes declared text artifacts to LF; no managed `.gitattributes` | None |
| GitHub diagnosis | Documentation only in this feature | Read-only GitHub configuration doctor |
| Maintenance | Manual Copier update and reconcile | Dependency and template maintenance automation |
| Renderer | Shared declarative Python standard-library compiler | Signed or sandboxed plugins if declarative contributions prove insufficient |
| Copier integration | Copier updates inputs; bootstrap reconciles derived output | Explicit GitHub-snapshot adoption into Copier lineage |
| Secret-gated jobs | Read-only availability preflight before privileged job | Live activation diagnostics through the GitHub doctor |
| Project validation | Seed-once reusable workflow called by managed CI | Richer machine-readable validation metadata if needed |
| Capability evolution | Stable IDs with backward-compatible definitions | Versioned IDs and explicit migrations |
| Target selection | Current directory by default; optional `--target` | Authenticated repository-identity verification |
| Workflow validation | Bounded standard-library checks plus source `actionlint` | A portable structured workflow parser or GitHub-backed validation |
| Transaction scope | Journal and rollback only for planned paths | Hook sandboxing where supported by a selected toolchain |
| Transaction state | Worktree-specific git administrative path, or an explicit `--state-dir` | Configurable retention policy |
| Repository identity | Read live at runtime; no persisted owner/repository slug | Doctor-managed rename and transfer diagnostics |
| Template provenance | Content fingerprints; Copier retains its own revision metadata | Signed release provenance |
| Seed ownership | Install once, then adopter-owned | Explicit opt-in reset or regeneration workflow |
| Schema evolution | Schema 1 remains backward-compatible throughout v1 | Explicit schema migrator in a later major version |
| Maintenance cleanup | Hash-checked inventory; a recorded opt-out transfers retained paths to the adopter | Authenticated source identity and richer provenance policy |
| Delivery | One v1 release built in five reviewable implementation batches | Independent lifecycle releases once the catalog stabilizes |

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

Every mutating command is one instance of the same pipeline. `apply`, `add`, `restore`, and
`reconcile` differ only in their preconditions and in which parts of the persisted state they are
permitted to change. There is no second write path.

### Proposed source layout

```text
scripts/bootstrap-project.py

scripts/bootstrap/
  __init__.py
  cli.py            # argument parsing, exit codes, human-readable output
  inputs.py         # bundle loading, path confinement, normalization
  model.py          # immutable normalized models, render IR, fingerprints
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
  source-ci-allowlist.json            # template-maintenance artifact
```

The exact module split may be refined in the implementation plan, but the dependency direction is
fixed: CLI and filesystem effects depend on the functional model; the model never imports CLI or
filesystem mutation code.

### Transaction state

Transient recovery state is not project content and is never committed.

Bootstrap requires a git working tree. It locates the per-worktree administrative directory with
`git rev-parse --git-path agentic-template`, which resolves to the worktree-specific administrative
area rather than the shared common directory. Using the common directory would let one journal
serialize unrelated linked worktrees and would let `recover` run from one worktree against another's
recorded plan.

- Bare repositories are rejected.
- When the target is not a git working tree, or git is unavailable, mutation fails with
  `BOOTSTRAP_TARGET_NO_GIT` unless `--state-dir PATH` names an existing directory outside the target
  tree. There is no implicit in-tree fallback: an ignored in-tree directory is not protected, because
  `git clean -x` removes ignored files.

The directory holds `journal.json` and a `backups/` tree. The journal is created with `O_CREAT |
O_EXCL`; a pre-existing journal is both the interrupted-transaction signal and the mutual-exclusion
lock, so two concurrent mutations cannot interleave.

The journal records the normalized absolute target path together with its device and inode identity.
`recover` refuses to act when the current target does not match that record.

Atomic replacement requires the source and destination to share a filesystem, and the administrative
directory may be on a different mount. Staging therefore always occurs in a temporary directory
adjacent to each planned path's parent, inside the target tree. Backups live durably in the state
directory, and rollback copies them into same-filesystem staging before renaming them into place.

Recovery evidence for tracked files also exists in git itself. When backups are missing or their
hashes do not match the journal, `recover` fails with `BOOTSTRAP_RECOVERY_EVIDENCE_MISSING` and
directs the operator to `git status` and `git restore` for tracked paths rather than guessing.

### File ownership

| Class | Owner and behavior |
| --- | --- |
| Copier/template inputs | Engine, catalog, render sources, validators, skills, static contracts, and `NOTICE.md`; Copier updates and merges these on its path |
| Bootstrap-managed output | Manifest, compiled CI, selected capability artifacts, and durable operational documents; exact hashes are enforced and `restore` recompiles them |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, `CONTRIBUTING.md`, root licence, and project-validation workflow; installed once and never regenerated in v1 |
| Adopter files | Product code, product documentation, `.gitattributes`, `.gitignore`, unrelated workflows, and all files outside declared template ownership |
| Template-maintenance artifacts | Source tests, source workflow fixtures, the source-CI allowlist, historical source specs, and other paths in the maintenance inventory; excluded by Copier and conditionally removed from GitHub snapshots |

No path may belong to more than one class. Source validation rejects duplicate, nested, or
case-colliding ownership declarations.

`CONTRIBUTING.md` is seed-once because contributor guidance is customized by almost every project,
and a managed, drift-fatal file that adopters are expected to edit converts a normal action into a
blocked repository. `.gitattributes` is adopter-owned for the same reason: LFS patterns, linguist
overrides, export rules, and merge drivers are ordinary adopter configuration. Bootstrap does not
install it at all; line-ending robustness is handled inside hash comparison instead.

The four `docs/*.md` operational documents remain managed because they describe template mechanics
that the adopter does not author.

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

Anything else is neither a scaffold nor a bootstrapped project, and `apply` refuses it. V1 has no
adoption path for a populated repository; the diagnostic says so and points at the migration
instructions.

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
- exclusively owned output paths, each declared `text` or `binary`;
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
classes so that no Unicode normalization question arises in fingerprinting. Repository owner/name is
intentionally absent because GitHub exposes current repository identity at runtime and persisted
slugs become stale after forks, transfers, and renames.

#### Content modes

Every content slot takes one of:

- `{"mode": "file", "path": "..."}` — adopter-authored bytes, copied verbatim; or
- `{"mode": "scaffold"}` — the template's marked placeholder for that slot.

`scaffold` is what keeps bootstrap from becoming an authoring gate. An adopter can select a profile,
compile real CI, and start working within minutes, while readiness continues to fail loudly and name
exactly which slots remain unreplaced. This preserves REQ-001: an untouched generated project is
still deterministically unready.

Licensing has no scaffold mode. A repository whose licence file was invented by a tool is worse than
a repository with no licence at all.

#### Slot completion is derived, never recorded

Whether a slot still holds placeholder content is **derived from the files**, using the marker
mechanism that already ships in `scripts/check-project-readiness.py`: `PRD_MARKER`, `README_MARKER`,
and `HOOK_SENTINEL`, extended to the SECURITY and contributing slots. A marker present means
unreplaced; absent means adopter content.

The manifest's content record is **bootstrap-time input identity only**. It says what was applied at
apply time, it is consumed solely by the apply decision procedure, and it is never a claim about the
current tree. Consequently:

- an adopter replaces a scaffolded file by editing it in place, and nothing needs to transition;
- `status` and readiness stay truthful because they never read the recorded mode; and
- no `finalize` operation is required.

Re-running `apply` with real content for a previously scaffolded slot is refused, and the diagnostic
says to edit the installed file directly. That is the designed path, not a limitation.

#### Content constraints

README, PRD, SECURITY, `CONTRIBUTING.md`, and supplied legal text must be valid UTF-8 text. The
validation hook may be any regular executable file and is copied byte-for-byte to
`scripts/validate-project` with mode `0755`. Referenced paths are relative to the JSON file, must
remain inside the bundle after normalization, must be regular files, and may not traverse a symlink.
Inline Markdown is not supported in v1.

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
sha256_hex(b)         = lowercase hexadecimal SHA-256 of the byte string b

canonical_json(v)     = json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")).encode("utf-8")

tagged(kind, payload) = sha256_hex(b"agentic-template/1/" + kind + b"\n" + payload)

entry(path, b, mode)  = canonical_json({"path": path,
                                        "mode": "100755" | "100644",
                                        "sha256": sha256_hex(b)})

tree_hash(kind, files) = tagged(kind, b"\n".join(entry(...) for every file,
                                                 sorted by the UTF-8 bytes of its path))
```

Entries are canonical JSON objects rather than delimiter-separated fields, so a path containing a
newline or other control character cannot change how the tree is parsed; JSON escaping makes the
`\n` join unambiguous. Domain tags prevent a value computed for one purpose from colliding with
another.

Constraints that make these total functions:

- `canonical_json` accepts only strings, booleans, `null`, integers within ±2^53, arrays, and objects
  with string keys. Floats are rejected outright, so cross-version float repr differences cannot
  enter a fingerprint.
- Paths that are not valid UTF-8 are rejected. Symlinks are rejected anywhere in a hashed source or
  output tree.
- Only regular files are artifacts. Empty directories are outside the artifact model; an absent file
  is already distinct from an empty file, which hashes as the SHA-256 of zero bytes.
- No Unicode normalization is applied anywhere. Adopter content bytes are preserved exactly, and
  mechanical identifiers are restricted to ASCII so that normalization cannot change their meaning.
- `mode` reflects only the owner execute bit. Managed files are installed as exactly `0644` or
  `0755` independent of umask, and comparison ignores group and other bits, matching git's index
  model.

### The four fingerprints

| Fingerprint | Construction | Covers |
| --- | --- | --- |
| `mechanical_fingerprint` | `tagged(b"mechanical", canonical_json(model))` | Project name, default branch, profile ID, explicit capability list, normalized settings, licensing mode |
| `content_fingerprint` | `tagged(b"content", canonical_json(slot_map))` | Each content slot's mode and, for `file`, its content hash |
| `template_source_fingerprint` | `tree_hash(b"template-source", inputs)` | Engine modules, catalog, core definitions, schemas, compatibility fixture, maintenance inventory |
| `selected_render_fingerprint` | `tagged(b"selected-render", canonical_json(render_ir))` | The complete normalized render IR |

`selected_render_fingerprint` is derived from the renderer's own input, not from a hand-maintained
list of contributing values. The render IR is the normalized intermediate representation the renderer
consumes: generation path, project name, default branch, licensing mode, the effective capability
list with each definition's tree hash, normalized settings, every resolved slot contribution in final
order, and the hash of any seed content byte that affects a managed output. Revision 2 enumerated the
inputs by hand and omitted `default_branch`, which appears in generated CI — an enumerated list will
rot silently, and a derived one cannot.

The render IR excludes unselected capabilities so that unrelated catalog additions do not create
false project drift. That exclusion is safe only because `validate-template.py` validates the
complete catalog independently, and because any change to the catalog moves
`template_source_fingerprint` and therefore requires `reconcile`.

### Apply decision procedure

An ordered procedure replaces revision 2's four-row matrix, which compared only the two input
fingerprints and managed state and therefore reported a validated no-op for an `apply` run after
`copier update`. Evaluation stops at the first step that does not hold.

1. **Manifest and recovery state.** Unreadable or corrupt manifest, unknown newer schema, or a
   pending journal → exit 2, naming `recover` where applicable.
2. **Target topology.** Unsafe symlink, ownership collision, or a non-regular file where a file is
   expected → exit 1.
3. **Mechanical input.** Differs → `BOOTSTRAP_INPUT_MECHANICAL_CHANGED`; next action `add` or the
   deferred reconfiguration lifecycle; exit 1.
4. **Content input.** Differs → `BOOTSTRAP_INPUT_CONTENT_CHANGED`; seed content is adopter-owned, so
   the next action is to edit the installed files in place; exit 1.
5. **Template-source identity.** Differs → `BOOTSTRAP_TEMPLATE_SOURCE_CHANGED`; next action
   `reconcile`; exit 1.
6. **Render identity.** Recompute `selected_render_fingerprint`. If it differs while steps 3–5 all
   hold, the engine has produced a different render from identical inputs →
   `BOOTSTRAP_INTERNAL_RENDER_CONTRACT`; exit 2. This is an engine defect, not a user problem.
7. **Managed state.** Any managed path whose hash or owner execute bit differs →
   `BOOTSTRAP_DRIFT_MANAGED`; next action `restore`; exit 1.
8. **All hold.** Validated no-op; exit 0.

Neither input fingerprint authorizes re-copying adopter-owned files.

### Byte-level output rules

For the same template-source fingerprint and render IR, output is byte-for-byte identical:

- generated JSON uses `canonical_json` ordering and separators, with one trailing newline;
- generated text uses UTF-8 and LF endings;
- generated file modes are declared and installed as exactly `0644` or `0755`;
- adopter content bytes are preserved exactly;
- timestamps, random identifiers, working directories, hostnames, locale, and environment variables
  do not enter final output; and
- output path enumeration is sorted by path bytes.

Transaction journals may use unique temporary identifiers because they are transient recovery state,
not accepted generated output.

### Checkout portability

Hash comparison must survive a checkout that rewrote line endings. Every managed artifact is declared
`text` or `binary` in the catalog:

- a `text` artifact's recorded hash is computed over its LF-normalized bytes, and drift comparison
  normalizes the on-disk bytes the same way, so a `core.autocrlf=true` checkout does not report false
  drift; and
- a `binary` artifact is hashed exactly, with no normalization.

Revision 2 solved this by installing a managed `.gitattributes`, which made an ordinary adopter
configuration file drift-fatal — the same trap that moved `CONTRIBUTING.md` to seed-once ownership.
Normalizing inside comparison removes the artifact entirely. `docs/delivery-workflow.md` recommends
`* text=auto eol=lf` as adopter-owned configuration.

## Project manifest

`.agentic-template/project.json` is canonical mechanical state. Conceptually it records:

```text
schema_version
generation_path
template_source_fingerprint
project name and default branch
mechanical_fingerprint and content_fingerprint
content slot modes as applied           (input identity, not current state)
profile ID and frozen profile capability list
explicit capability additions
effective dependency closure
normalized non-secret settings
licensing decision
external activation requirements
selected_render_fingerprint
maintenance_cleanup status and retained paths
managed artifact paths, declared text/binary kind, POSIX modes, and SHA-256 hashes
```

It does not contain:

- product prose or legal text;
- input source paths;
- repository owner/name;
- timestamps or machine-specific absolute paths;
- secrets or secret-presence claims;
- live GitHub configuration state;
- any claim about the current content of a seed-once file; or
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
                                             [--leave-maintenance-artifacts] [--state-dir PATH]

python3 scripts/bootstrap-project.py plan-restore [--path PATH]... [--target PATH]
python3 scripts/bootstrap-project.py restore      [--path PATH]... [--target PATH] [--state-dir PATH]

python3 scripts/bootstrap-project.py plan-add --answers addition.json [--target PATH]
python3 scripts/bootstrap-project.py add      --answers addition.json [--target PATH] [--state-dir PATH]

python3 scripts/bootstrap-project.py plan-reconcile [--target PATH] [--overwrite-drift]
python3 scripts/bootstrap-project.py reconcile      [--target PATH] [--overwrite-drift]
                                                    [--state-dir PATH]

python3 scripts/bootstrap-project.py recover [--target PATH] [--state-dir PATH]
```

`init` creates a complete reviewable bundle only. With `--init-answers`, referenced source paths are
resolved relative to that seed document and copied into the output bundle. The initializer uses a
temporary sibling and installs the complete bundle only after validation.

`status` is read-only. It reports generation path, frozen profile, explicit additions, effective
capability set, unreplaced slots derived from file markers, every drifted managed path, whether
maintenance cleanup was skipped and which paths were retained, declared external activation
requirements, and any pending transaction journal. It exits 0 when it can describe the project — including
when what it describes is drift or unreadiness — and exits 2 when the manifest is unreadable or
corrupt or internal state is invalid. It is the command an adopter or agent runs first, and the one a
diagnostic points at.

`restore` is the drift remedy and operates strictly within the recorded contract. Its preconditions:

- the manifest schema is known and no journal is pending;
- target topology is safe;
- the current `template_source_fingerprint` equals the manifest's;
- the recomputed `selected_render_fingerprint` equals the manifest's;
- the persisted effective capability set resolves exactly;
- every requested path is manifest-managed; and
- each recompiled artifact's hash and mode equal the manifest's record for that path.

The last precondition is what makes `restore` safe: it can only ever write bytes the manifest already
certifies, so it cannot introduce new content. It never changes a fingerprint, capability state,
setting, or any other global manifest identity. A template-source or render mismatch causes it to
refuse and name `reconcile`.

`reconcile` is the **only** operation permitted to advance `template_source_fingerprint` or
`selected_render_fingerprint`. Revision 2 let `restore` do so, which made it reconciliation without
reconciliation's schema, catalog, capability, and Copier-conflict preconditions — and let
`restore --path` advance a repository-wide fingerprint after re-rendering a single path, certifying a
mixed old/new state that never existed as one render.

`--overwrite-drift` is accepted by both `plan-reconcile` and `reconcile`, so the destructive
operation can be faithfully previewed. It is the only exit from drift combined with a changed
template, and is therefore load-bearing rather than a convenience.

`--leave-maintenance-artifacts` is the single supported override for a maintenance inventory that no
longer matches. It skips cleanup and records the retained paths in the manifest, which transfers them
to adopter ownership; no later cleanup operation is needed because deleting an adopter file is the
adopter's business. Readiness reports the skip informationally and does not fail on it. Without this
override, an adopter who committed one change before bootstrapping a GitHub snapshot has no path
forward.

All plan commands run every preflight possible without installing the target plan and report stable,
ordered path operations with old and new hashes. They do not invoke the adopter hook against a
partially rendered target. Mutating commands repeat preflight to avoid time-of-check/time-of-use
assumptions.

Exit codes are stable and match the existing readiness contract:

- `0`: success or deterministic no-op, meaning the complete canonical command would succeed;
- `1`: user-correctable input, readiness, activation declaration, validation, or drift problem —
  including a completed installation whose adopter hook failed; and
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
2. Stage every new file in a temporary directory on the target's filesystem, without changing
   accepted target paths.
3. Create the journal with `O_CREAT | O_EXCL`, containing the operation list, expected hashes, backup
   locations, the transaction phase, and the normalized target identity. A pre-existing journal aborts
   here and is both the interrupted-transaction signal and the concurrency lock.
4. Back up every replaced or deleted planned path into the state directory.
5. Install operations in deterministic order using same-filesystem atomic replacements.
6. Run gating validation, defined below.
7. On gating success, remove backups and the journal. The installation is now final.
8. Run the adopter hook and report its labelled result.
9. On gating failure, restore all planned paths and retain clear diagnostics if restoration is not
   complete.

### What gating validation is

Gating validation is what decides rollback. It is not the canonical command, and it is not readiness
in full. A mutation is gated on the findings **it introduced**, not on the project's absolute
readiness:

- `python3 scripts/validate-template.py` must succeed; and
- `python3 scripts/check-project-readiness.py` must report no finding that was absent before the
  transaction began, except an unreplaced-placeholder finding for a slot the applied bundle
  explicitly declared `scaffold`.

Both clauses are necessary, and they cover different operations:

- The **pre-existing-finding** clause covers `add`, `restore`, and `reconcile`, which have no bundle.
  A project whose PRD is still a placeholder is unready, and it must remain possible to add a
  capability to it. Without this clause, every mutation on a not-yet-completed project would gate-fail
  and roll back.
- The **declared-scaffold** clause covers initial `apply`, where the placeholder findings are new
  precisely because the transaction just installed them on purpose.

The exemption is narrow in both directions. It covers only placeholder findings; it never suppresses a
manifest, ownership, hash, licensing, workflow, or documentation finding; and it never excuses a
finding the operation newly caused, so a mutation cannot degrade readiness and call it pre-existing.

Readiness is captured once before staging and once after installation, and the two finding sets are
compared by stable diagnostic identifier and path.

### Why the adopter hook does not gate, and why it still fails the command

Revision 1 gated the transaction on the full `validate-repository.py`, whose third stage is the
adopter's own executable. That stage can fail because a dependency is not installed, a container is
not running, or a toolchain is absent — none of which say anything about whether bootstrap compiled
the project correctly. Rolling back a correct installation for those reasons is surprising, and doing
so after the hook may have created untracked artifacts is unsafe.

Revision 2 then overcorrected by exiting 0. That contradicts `CONTEXT.md`, which defines project
readiness as including successful completion of the adopter hook, and `docs/prd.md` REQ-002, which
defines the canonical command as all three stages in order.

Both properties are available at once, and v1 takes them:

- the transaction is gated on the deterministic, portable stages bootstrap owns;
- a failing hook never triggers rollback; and
- the command exits 1 and reports that bootstrap files were installed but the repository is not
  locally ready.

`status` reports that state as unready. Exit 0 continues to mean what it has always meant. A future
`--strict` flag could gate the transaction on the hook; it is not needed in v1.

### Drift

A bootstrap-managed path whose normalized bytes or owner execute bit differ from the manifest is
drift. Drift is reported by `status` and readiness, blocks `apply`, `add`, and `reconcile`, and is
resolved by `restore` — or, when the template also moved, by `reconcile --overwrite-drift` after
preview. Drift is never silently overwritten or merged.

Seed-once and adopter files are never drift. They are expected to change.

### Recovery

An interrupted journal blocks `apply`, `add`, `restore`, and `reconcile`. `recover` validates the
journal, confirms the recorded target identity matches the current target, restores the pre-operation
state, and removes recovery state only after verifying restored hashes. It never resumes forward.

The adopter-owned validation hook may create normal validation artifacts as allowed by the PRD.
Bootstrap does not attempt to enumerate or remove those artifacts, terminate external effects, or
claim whole-repository atomicity.

Planned target paths may not traverse a symlink. Existing symlinks at owned paths, parent/child path
ownership collisions, and non-regular files where a file is expected fail preflight.

## Reconciliation contract

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
- the exact persisted effective capability set to remain resolvable without adding or removing an ID;
  and
- current managed bytes equal to old manifest hashes, unless `--overwrite-drift` is given.

It may update implementations, selected documentation, `template_source_fingerprint`,
`selected_render_fingerprint`, and managed hashes. It may not re-expand a profile, modify seed-once
or adopter files, select a template version, merge drift, or invoke an implicit migration.

## Migration from the pre-bootstrap template

V1 changes the canonical project-validation hook path from `scripts/validate-project.py` to the
toolchain-neutral `scripts/validate-project`, and it introduces the manifest. This is a breaking
template-contract change, released with migration instructions, which `docs/prd.md` explicitly
permits for a change that makes a conforming project unready.

Revision 2 instead accepted both hook paths for the lifetime of v1 and added an `adopt` command.
Both are removed. Accepting two paths embeds a permanent ambiguity and an extra error state, and
`adopt` was specified without a `plan-adopt` preview, referred to `plan-add` before a manifest
exists, and left collision handling for installing managed CI into a populated repository undefined.
An underspecified mutation command cannot be un-shipped.

The migration for an existing project is manual and documented in the release notes:

```text
git mv scripts/validate-project.py scripts/validate-project
```

Adopting a populated repository into a bootstrapped one remains a documented future lifecycle,
requiring its own preview, collision, and ownership-transfer design.

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
   result and emits setup guidance when unavailable.
2. A job with the minimum required write permissions starts only when preflight returned available
   and normal event trust conditions pass.

The preflight reports two states, not three:

| State | Condition | Guidance |
| --- | --- | --- |
| Available | The secret resolves to a non-empty value | Proceed |
| Unavailable in this run | Anything else | List the likely causes for this event type, and link the setup step in `docs/github-setup.md` |

Revision 2 claimed a third state that distinguished "not configured" from "unavailable in context".
An empty secret cannot prove that: GitHub withholds Actions secrets from pull requests raised from
forks and from Dependabot-triggered runs, repository and organization policy can restrict them
further, and a configured secret may legitimately be empty. The likely-cause list names the fork and
Dependabot cases explicitly so an adopter does not chase configuration that is already correct.
Authoritative configured/not-configured diagnosis belongs to the proposed GitHub configuration
doctor, which can query repository configuration directly.

The PR Agent review and trusted-comment workflows apply this pattern to `GEMINI_API_KEY`. The Cachix
path skips all Cachix-specific setup and publishing when `CACHIX_AUTH_TOKEN` is unavailable, allowing
Nix validation to continue uncached. When the token is available, publishing is additionally gated on
the default branch event and successful Nix/project validation; an invalid or unavailable configured
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
`integrated`-profile project, so a source fixture renders the `integrated` CI and compares it with
the source workflow.

To avoid becoming another hand-maintained compatibility layer, the comparison is a defined
normalization rather than a judgement:

- both workflows are reduced to a normal form consisting of, per job, the job ID, the sorted `needs`
  set, the `permissions` map, the `if` condition, the `runs-on` value, and the called workflow
  reference where one exists; step bodies are dropped;
- `.agentic-template/source-ci-allowlist.json` declares the source-only job IDs and the source-only
  per-job differences that are permitted, each with a reason; and
- the fixture fails on any difference in the normal form that the allowlist does not name, and also
  fails on an allowlist entry that no longer corresponds to a real difference, so the allowlist
  cannot silently accumulate.

## Validation boundaries

### `scripts/validate-template.py`

Validates reusable template machinery without assuming a bootstrapped adopter instance:

- bootstrap and manifest schemas;
- profiles and the complete capability catalog;
- dependency topology;
- setting declarations and defaults;
- output ownership, declared text/binary kinds, and composition slots;
- renderer inputs and path safety;
- template-maintenance inventory and the source-CI allowlist; and
- stable capability compatibility fixtures.

It remains Python 3.11 standard-library-only and does not execute capability content or the adopter
hook.

### `scripts/check-project-readiness.py`

Validates one project instance. Without a manifest it behaves as it does today, reporting the
project as unbootstrapped. With a manifest it additionally checks:

- manifest schema and internal topology;
- profile snapshot, explicit additions, and effective capability set;
- mechanical, content, template-source, and selected-render fingerprint structure;
- managed artifact modes and normalized hashes;
- licensing decision and required preserved provenance;
- required durable documentation;
- validation hook presence and mode at the canonical path;
- seed-once project-validation workflow's bounded contract;
- external requirement declarations;
- retained maintenance paths, reported informationally; and
- absence of unreplaced placeholder markers in any content slot.

It reports a template-source mismatch as "reconcile required". Individual managed hash mismatch is
drift, reported with `restore` as the next action.

### `scripts/validate-project`

This is the canonical path for the adopter-supplied arbitrary executable. It owns product-specific
validation, chooses its own toolchain, and may create normal validation artifacts. The aggregate
invokes it directly rather than through Python. Native Windows execution is not a v1 guarantee.

### `scripts/validate-repository.py`

Remains the canonical ordered boundary:

1. template contract;
2. project readiness; and
3. adopter project validation.

Stages 1 and 2 gate the bootstrap transaction. Stage 3 is the adopter's, and its failure means the
repository is not locally ready without meaning the installation was wrong. Source-only
GitHub/Copier fixtures and profile/capability matrix suites are not added to this portable
generated-project boundary.

## Licensing and provenance

Bootstrap requires one explicit licensing choice and accepts no licence default and no scaffold.

For `retain-apache-2.0`, the source Apache-2.0 text remains the root `LICENSE`. For
`provided-project-license` and `private`, the adopter-supplied legal text becomes root `LICENSE`. The
conservative minimum preservation design keeps `NOTICE.md` and retains the template Apache-2.0 text
under `LICENSES/Apache-2.0.txt` when it is no longer the root licence.

The licensing and provenance audit is a blocking gate for **every** licensing mode, and must complete
before any licence-writing implementation. It must:

- inspect every bundled skill's upstream licence and notice requirements;
- confirm whether the proposed Apache and notice locations satisfy redistribution obligations;
- identify any notice that must remain verbatim;
- define how adopter additions to notices are preserved; and
- update this design and an ADR if the required layout differs.

Revision 2 scoped the audit to block only the two licence-relocating modes, on the theory that
retaining Apache-2.0 at the root raises no new question. That is wrong: `NOTICE.md` requires
reviewing upstream skill licences "before redistributing this template", and every generation path
redistributes those skills regardless of which text sits at the root. It also contradicted US-5,
which requires the audit before release.

The audit may strengthen preservation requirements but may not authorize bootstrap to invent project
legal terms or declare the resulting project legally valid. Bootstrap reports the selected mode and
preserved provenance as mechanical facts only. This is a design gate, not a legal-validity opinion.

## Durable adopter documentation

The following bootstrap-managed documents are rendered from core and selected capability fragments:

- `docs/delivery-workflow.md`: canonical validation, CI/release gates, review flow, recovery, and the
  recommended adopter-owned `.gitattributes` line-ending configuration;
- `docs/template-updates.md`: GitHub snapshot or Copier lineage, compatible reconciliation, drift,
  `restore`, and the plain statement that GitHub snapshots receive no further managed updates;
- `docs/capabilities.md`: frozen profile, additions, effective set, settings safe to display, and
  dependencies; and
- `docs/github-setup.md`: required secrets, the two preflight states with their likely causes
  including fork and Dependabot runs, Actions/ruleset steps, and the distinction between release and
  merge gates.

Each begins with a header naming it as bootstrap-managed and directing project-specific prose to
`CONTRIBUTING.md`, the README, or product documentation.

Capability addition and reconciliation update these documents atomically with their related
artifacts. The manifest hashes them. Direct edits are drift, reported by `status` and resolved by
`restore`. Managed regions and adopter fragments are proposed future changes.

## Template-maintenance inventory

`.agentic-template/maintenance-artifacts.json` declares paths that exist only to develop and release
the template source, such as source fixture suites, the Copier smoke workflow, the source-CI
allowlist, and historical template-source specs and plans.

The inventory records each path, expected source hash or tree hash, and whether the path is a regular
file or directory tree. It may not overlap a static, seed-once, adopter, or bootstrap-managed path.

- Copier excludes the declared inventory from generated projects. The current `copier.yml` exclude
  list is replaced by the generated inventory; its stale `tools` entry, which matches no existing
  path, is removed.
- GitHub snapshot bootstrap removes only entries whose complete bytes match the declared source
  shape.
- A modified, missing-with-children, unsafe, or partially matching entry blocks initial cleanup,
  reports the exact path, and names `--leave-maintenance-artifacts` as the supported override.
- A skipped cleanup records the retained paths in the manifest and transfers them to adopter
  ownership. Readiness reports them informationally rather than as unreadiness, and no later cleanup
  operation exists, because removing an adopter-owned file needs no bootstrap command.
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
BOOTSTRAP_TEMPLATE_SOURCE_*
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

- Schema normalization and canonical serialization, including rejection of floats, non-string keys,
  out-of-range integers, and non-UTF-8 paths.
- Input path confinement, symlink rejection, regular-file requirements, and UTF-8 requirements.
- Content-mode handling for `file` and `scaffold`, and marker-derived slot completion.
- Profile expansion and exact dependency closure.
- Cycle, collision, type, slot, and compatibility detection.
- The four fingerprint constructions, including domain-tag separation, JSON-entry tree hashing with
  control characters in paths, and mode-token normalization.
- Render IR construction, proving that changing `default_branch` changes
  `selected_render_fingerprint`.
- Deterministic renderers and typed setting encoders.
- LF normalization for declared text artifacts and exact hashing for binary artifacts.
- Plan ordering and every branch of the apply decision procedure, including the
  template-source-changed and internal-render-contract steps.
- Journal state transitions, `O_EXCL` mutual exclusion, target-identity matching, and recovery
  validation.

### Tiered fixture matrix

The full cross-product is too slow for every pull request, so it is tiered. During development each
batch runs the fixtures that exist at that point; the tiers below describe the released steady state.

**Pull-request tier**, targeting a few minutes: both generation paths across `portable` and
`integrated`; `retain-apache-2.0` and `provided-project-license`; one all-`scaffold` bundle and one
fully supplied bundle; the drift/restore cycle; one injected interruption and recovery; and
`actionlint` on the source and on generated workflows.

**Pre-release tier**, run at the release gate: both generation paths across all five profiles;
representative custom empty, single, dependent, and multi-capability sets; all three licensing modes;
every required capability setting variation; and unavailable/available external-activation structures
without real secrets.

Runtime budgets are recorded when the fixtures land, and a tier that exceeds its budget is split
rather than silently slowed.

Each case proves untouched failure where applicable, successful bootstrap, gating validation,
identical-input no-op, exact artifact presence/absence, stable manifest, and absence of source-only
maintenance files.

### Lifecycle coverage

- Add an independent capability; add `cachix-publish` and resolve `nix`; repeat a satisfied addition.
- Reject conflicting existing settings and removal requests.
- Modify one managed artifact and prove `apply`, `add`, and `reconcile` refuse it and `restore`
  resolves it.
- Restore a named subset and prove untouched managed paths are unchanged.
- Prove `restore` refuses when template inputs changed, and names `reconcile`.
- Prove `restore` cannot advance either fingerprint, and that a single-path restore never mutates
  global manifest identity.
- Prove drift plus a changed template is resolvable only through
  `plan-reconcile --overwrite-drift` followed by `reconcile --overwrite-drift`.
- Run `apply` after a Copier update with identical inputs and healthy managed state, and prove the
  result is `BOOTSTRAP_TEMPLATE_SOURCE_CHANGED` rather than a no-op.
- Perform a compatible Copier update, then reconcile.
- Change an unselected capability and prove no selected render drift.
- Present an incompatible capability fixture or unknown manifest schema and prove zero writes.
- Inject failure before the journal, during each mutation phase, during gating validation, and during
  rollback.
- Prove a failing adopter hook leaves the installation in place, exits 1, and is reported as unready
  by `status`.
- Recover an interrupted transaction and verify exact pre-operation planned-path hashes.
- Prove `recover` refuses a target whose identity does not match the journal.
- Prove a second concurrent mutation is refused by the existing journal.
- Let the adopter hook create an unrelated validation artifact and prove rollback leaves it alone.
- Apply an all-`scaffold` bundle and prove the installation is retained, gating validation passes,
  and the command exits 1 naming exactly the scaffolded slots.
- Prove the scaffold exemption suppresses only placeholder findings: inject a manifest hash mismatch
  and a missing durable document alongside a scaffold slot, and prove both still gate-fail and roll
  back.
- Run `add`, `restore`, and `reconcile` on a project whose PRD is still a placeholder, and prove each
  succeeds because the finding pre-existed the transaction.
- Prove a mutation that newly breaks readiness gate-fails and rolls back even when an unrelated
  placeholder finding already existed.
- Replace a scaffolded slot in place and prove `status` and readiness report it complete while the
  manifest's recorded mode is unchanged.
- Check out a managed project with `core.autocrlf=true` and prove no false drift.
- Run in a linked git worktree and prove its journal is independent of the primary worktree's.
- Run against a non-git directory and prove mutation refuses without `--state-dir`.

### Workflow and security coverage

- Run `actionlint` on source and every generated workflow fixture.
- Assert the managed caller passes no secrets and has read-only permissions.
- Assert the seeded project-validation workflow invokes the canonical boundary and has no privileged
  environment.
- Assert release depends on the full project-validation call and selected checks.
- Assert unavailable Gemini/Cachix secrets create successful skip guidance naming the fork and
  Dependabot causes.
- Assert privileged PR Agent or Cachix publishing jobs cannot start when preflight is false.
- Assert the source CI conforms to the normalized `integrated` render, and that a stale allowlist
  entry fails the fixture.
- Assert persisted checkout credentials and real credential-looking values are absent.

## Compatibility and the PRD

### Requirement delta

| Requirement | Change |
| --- | --- |
| REQ-001 detect incomplete setup | Retained and extended: readiness must name unreplaced slots specifically, derived from file markers, so a scaffolded project is still deterministically unready |
| REQ-002 one validation command | Retained; the canonical hook path becomes `scripts/validate-project`, which is a **breaking change** requiring migration notes |
| REQ-003 gate releases on project validation | Retained; the gate becomes a compiled contribution present only when `semantic-release` is selected |
| REQ-004 verify generated behavior from source | Extended to the tiered fixture matrix and both generation paths across profiles |
| REQ-005 preserve generation-path ownership | Extended with the five ownership classes and the drift contract |
| REQ-006 portable, least-privileged template validation | Retained unchanged; bootstrap remains standard-library-only |
| New: deterministic bootstrap | The compiler, its input contract, and byte-for-byte output guarantees |
| New: capability selection | Profiles, catalog, and the absence of unselected artifacts |
| New: managed-artifact ownership and drift | Manifest, hashes, `restore`, and the refusal to merge |
| New: one operation owns template identity | Only `reconcile` may advance template or render identity |
| New: installation is distinct from readiness | A completed installation whose hook fails exits 1 and is reported unready |
| New: activation is not readiness | Two-state secret preflight, safe skips, and the manifest recording requirements only |

The PRD's compatibility quality attribute requires that a change making a conforming project unready
ship as a breaking template-contract change with migration notes. V1 triggers that clause through the
hook-path rename, and satisfies it with the migration instructions above.

### CONTEXT.md changes required

The domain language needs updating alongside the PRD, because v1 changes terms it defines:

- **Project bootstrap** gains the distinction between a completed installation and a locally ready
  project.
- **Project readiness** keeps its meaning, including successful hook completion, and gains the note
  that unreplaced scaffold slots are derived from file markers.
- **Bootstrap-managed artifact** gains `restore` as the supported drift remedy.
- **Project-validation hook** changes path to `scripts/validate-project`.
- New terms: **snapshot profile expansion**, **render identity**, **managed drift**, and
  **maintenance cleanup opt-out**.
- The example dialogue should gain an exchange distinguishing "bootstrap installed the files" from
  "the repository is locally ready".

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A catalog change silently changes an old snapshot | Persist exact sets, freeze compatibility fixtures, and block incompatible reconciliation |
| Copier and bootstrap both modify one output | Exclude derived/seed-once paths from Copier and validate ownership collisions |
| GitHub bootstrap deletes adopter work | Delete only declared exact-hash scaffold or maintenance paths; otherwise fail the whole plan |
| A managed file is edited directly | Detect via normalized manifest hashes and resolve with `restore` |
| Drift leaves the project permanently blocked | `restore` for the in-contract case, previewed `reconcile --overwrite-drift` when the template also moved |
| A repair silently upgrades the template | `restore` may only write bytes the manifest already certifies; only `reconcile` advances identity |
| A partial repair certifies a state that never existed | `restore` cannot change global manifest identity, so a single-path repair cannot bless a mixed render |
| An `apply` after a template update reports success | The decision procedure compares template-source identity before declaring a no-op |
| A fingerprint silently stops covering an input | `selected_render_fingerprint` is derived from the render IR, not an enumerated list |
| A crash leaves mixed output | Durable journal in the worktree administrative path, backups, blocked mutation, and rollback-only `recover` |
| Recovery targets the wrong checkout | Per-worktree state and a recorded target identity |
| Recovery evidence is destroyed | State outside the tree, no reliance on gitignore, and git as the fallback for tracked files |
| Two mutations run at once | `O_EXCL` journal creation is the lock |
| A correct installation is discarded | Gate only on template-owned deterministic validation |
| An unready project is reported ready | Hook failure exits 1 and `status` reports unready |
| The adopter hook creates side effects | Limit the transaction claim to planned paths and never delete unknown hook artifacts |
| False drift from line endings or umask | LF normalization inside comparison and execute-bit-only mode comparison |
| An ownership class traps ordinary configuration | `CONTRIBUTING.md` and `.gitattributes` are adopter-owned |
| Bootstrap becomes an authoring gate | `scaffold` content mode compiles a real project before prose exists |
| A scaffolded slot's state goes stale | Slot completion is derived from file markers, never from the manifest |
| A scaffold apply rolls itself back | Gating validation exempts declared scaffold placeholder findings, narrowly |
| Fixing a typo appears impossible | Split fingerprints so content-only differences get their own diagnostic |
| Missing secrets fail every PR | Read-only activation preflight and successful skip guidance |
| Preflight guidance misdirects | Two honest states with event-specific likely causes; authoritative diagnosis deferred |
| A privileged job starts merely to check a secret | Separate preflight and privileged jobs with dependency-gated start conditions |
| Manifest records stale external state | Persist requirements only; inspect live state in workflows or the future doctor |
| Repository slug becomes stale | Read live GitHub context and omit owner/repository from the manifest |
| GitHub snapshot lacks source commit lineage | Record content fingerprints without inventing release metadata |
| Compiled CI drifts from the template's own CI | Normalized conformance fixture with a self-expiring allowlist |
| A handwritten YAML checker overclaims correctness | Bounded policy checks, source `actionlint`, GitHub runtime validation, and explicit documentation |
| Managed documentation blocks customization | `CONTRIBUTING.md` is seed-once; managed documents point to adopter-owned prose |
| Licence replacement loses obligations | Conservative preservation plus an audit that gates every mode |
| Existing adopters hit an undocumented break | One documented breaking change with a one-line migration |
| An underspecified mutation ships | `adopt` deferred rather than half-specified |
| One change contains the whole system | Five reviewable implementation batches inside one release |
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
- `apply --strict`, gating the transaction on the adopter hook.

### Capability and profile lifecycle

- A broader first-party catalog.
- Third-party capability registries with signing, provenance, compatibility, and trust policy.
- Live profiles or profile-plus-override policies explicitly distinct from snapshots.
- Capability removal, replacement, rebasing, and full reconfiguration.
- Versioned capability IDs and explicit capability/manifest migrations.
- Managed document regions or adopter-provided documentation fragments.
- A signed or sandboxed plugin model if declarative fragments and typed slots prove insufficient.

### Adoption and portability

- An adoption lifecycle for populated repositories, with `plan-adopt`, collision handling, and
  ownership-transfer rules.
- Explicit adoption of GitHub snapshots into Copier update lineage.
- Declarative validation-command lists and generated hook adapters.
- Interpreter adapters and native Windows support.
- A portable structured GitHub workflow parser.
- Structured JSON diagnostics and GitHub Actions annotations.
- Hook sandboxing for selected environments.

### GitHub and external activation

- A read-only GitHub configuration doctor covering Actions availability, current default branch,
  authoritative secret configuration, workflow activation, rulesets, and required checks.
- Authenticated repository-identity and rename/transfer diagnostics.
- Explicitly authorized secret, ruleset, or branch-protection writes in a separate operator tool.

### Distribution and maintenance

- Dependency and template maintenance automation that opens reviewable update PRs with reconciliation
  previews and compatibility evidence.
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
- Claiming to know whether a repository secret is configured from an empty value.
- Letting bootstrap itself perform unapproved external configuration writes.
- Persisting live activation status as repository truth.
- Persisting repository owner/name when it can be read at runtime.
- Silently overwriting or merging bootstrap-managed drift.
- Leaving drift with no supported remedy.
- Letting a drift repair advance template or render identity.
- Letting a partial repair update repository-wide identity.
- Gating the bootstrap transaction on the adopter-owned validation hook.
- Reporting success when the adopter hook failed.
- Requiring complete product prose before a project can be compiled.
- Recording slot completion in the manifest instead of deriving it from the files.
- Accepting two canonical hook paths.
- Shipping an adoption command without a preview or collision rules.
- A second manifest version field that duplicates the template-source fingerprint.
- Managing `.gitattributes` or `CONTRIBUTING.md` as drift-fatal artifacts.
- Storing transaction state in the shared git common directory or in an ignored in-tree directory.
- Treating capability removal as reconciliation.
- A custom version-aware updater that competes with Copier.
- Parallel Copier and Python rendering implementations.
- Mandatory trusted Copier task execution.
- Restricting the adopter validation hook to Python.
- Requiring `--target` solely as an operator-attention mechanism.
- A handwritten general-purpose YAML parser presented as complete semantic validation.
- Legal boilerplate authored by bootstrap, or a claim that a selected licence is legally sufficient.
- Deferring the licensing audit for any distribution mode.
- Independently releasable slices with per-slice manifest compatibility levels.

## Required follow-up documents

Implementation must update or add:

- `docs/prd.md`, promoting the approved bootstrap behavior into authoritative requirements per the
  requirement-delta table, including the breaking hook-path change;
- `CONTEXT.md`, per the domain-language changes listed above;
- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs;
- an ADR for the capability compiler and ownership model if the implementation plan confirms the
  boundary is architectural;
- the licensing/provenance audit record and any resulting ADR;
- `docs/project-readiness.md`, reflecting the canonical hook path, derived slot completion, `status`,
  and `restore`;
- release notes containing the hook-path migration instructions;
- generated adopter documentation described above; and
- source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open for v1.

The licensing and provenance audit is a blocking implementation gate for every licensing mode. If it
changes the proposed `LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design must be amended and
reconfirmed before licence-writing implementation proceeds.

## References

- `docs/prd.md`
- `CONTEXT.md`
- `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md`
- `design.discovery-draft.md` and `design.revision-2.md` in this directory
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub: Dependabot on Actions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions)
- [Git: `git rev-parse`](https://git-scm.com/docs/git-rev-parse)
- [Git: `git clean`](https://git-scm.com/docs/git-clean)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/)
- [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
