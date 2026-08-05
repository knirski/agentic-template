# Deterministic Project Bootstrap with Capability Profiles

**Status:** Revision 4, assembled for independent approval review
**Date:** 2026-08-05
**Planning mode:** Spec-backed Plan
**Supersedes:** `design.discovery-draft.md` (revision 1), `design.revision-2.md`, and
`design.revision-3.reconstructed.md`. Revision 3 was overwritten in place before it was archived; the
file of that name is a reconstruction from session history, not the original artifact, and the
filename says so

## Summary

Add a deterministic, explicit bootstrap compiler that turns either supported generated-repository
shape into a locally ready project from a reviewable input bundle. The compiler expands an explicitly
selected snapshot profile into an exact capability set, writes only declared outputs, persists
normalized mechanical state, and reports the result through the repository's canonical validation
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

V1 is one public release, built in internal review batches whose intermediate merges are inert. It is
a breaking template-contract change, released with migration instructions.

This design is an explicit product decision that extends `docs/prd.md`. Implementation must update
the PRD, `CONTEXT.md`, and ADR 0001 as pre-runtime gates, before any behavior change lands.

## Settled decisions

These are owner decisions. They are recorded here so that later review does not reopen them.

- `scaffold` remains in v1.
- Slot completion is derived from current file markers. There is no `finalize` lifecycle.
- The manifest's content record is bootstrap-time input identity, not current tree state.
- There is one canonical extensionless adopter hook at `scripts/validate-project`. The legacy `.py`
  path, dual-path support, `adopt`, and `plan-adopt` are not restored.
- Capability changes are additive only in v1.
- V1 is one public release; internal review batches are not versions.
- Toolchain neutrality and flexibility take priority over native Windows compatibility.
- GitHub-generated projects remain snapshots. Copier owns template update and merge mechanics.

## Revision ledger

Four tables, separated by kind, because revision 3 conflated deliberate reversals with defect
corrections and undercounted both.

### Deliberate reversals of approved revision 1 decisions

Approving this design approves these reversals.

| Revision 1 decision | Current decision | Why |
| --- | --- | --- |
| A bundle must supply complete content for every slot | Every slot is an adopter file or an explicit `scaffold` placeholder | Requiring a finished PRD before a project could compile made bootstrap an authoring gate and regressed the existing first-run experience |
| Successful `apply` makes the full canonical validator pass | `apply` installs, then reports; a failing adopter hook means exit 1 and "not locally ready", never rollback | The hook can fail because a toolchain is absent, which says nothing about whether bootstrap compiled correctly, and rolling back after the hook may have created artifacts is unsafe |
| Reconciliation writes only paths whose bytes match old manifest hashes | `reconcile --overwrite-drift` may overwrite drift, bound to a preview digest | Without an escape, drift plus a changed template is unresolvable |
| The lifecycle is initial bootstrap plus additive capability changes | Adds `restore`, a same-contract drift repair | Revision 1 detected drift, blocked on it, and provided no mechanism to resolve it |
| Partial bundles and a finalize phase are future work | `scaffold` is in v1; no finalize phase is needed | Slot completion is derived from the files, so there is no state to transition |
| `CONTRIBUTING.md` is bootstrap-managed output (`design.discovery-draft.md:403`) | `CONTRIBUTING.md` is seed-once adopter output | A managed, drift-fatal file that adopters are expected to edit converts an ordinary action into a blocked repository. Revision 3 recorded this as a defect correction; it is a reversal of an approved revision 1 decision |
| The validation hook is installed at `scripts/validate-project.py` | The canonical path is `scripts/validate-project`, released as a breaking template-contract change | Toolchain neutrality; the extension asserted an interpreter the adopter may not use |

### Defect corrections to revision 2

Twenty rows. Revision 3's table had nineteen and described itself as having seventeen.

| Revision 2 defect | Correction |
| --- | --- |
| `restore` recompiled from current template inputs and advanced fingerprints, bypassing reconciliation's preconditions; `restore --path` could bless a mixed old/new render | `restore` operates strictly within the recorded contract and writes only bytes the manifest already certifies; identity transitions are governed by one normative table |
| `plan-reconcile` could not preview `--overwrite-drift` | Both commands accept it, and destructive reconciliation is bound to a plan digest |
| US-8 permitted drift overwrite and forbade it four lines apart | Resolved in favor of the explicit, previewed override, with per-operation drift behavior |
| A mutating command exited 0 when the adopter hook failed, contradicting `CONTEXT.md`'s definition of project readiness | Exit 0 means the full canonical command would succeed; hook failure is exit 1 with the installation retained |
| `scaffold` slot completion had no defined derivation, so the manifest's recorded mode read as current state | Slot completion is derived from declared file markers; the manifest's content record is input identity only |
| Markers were named for three slots and assumed for five, and marker detection assumed decodable text while the hook is an arbitrary executable | Five markers are declared; the hook sentinel is detected at byte level |
| A legacy `.py` hook path was accepted for the lifetime of v1, and `adopt` was added without a preview, with an incoherent `plan-add` reference and no collision rules | Single canonical hook path with a documented migration; `adopt` deferred |
| Slices claimed to be independently releasable, but later slices added artifacts readiness required, making earlier manifests unready | One public release; internal batches whose intermediate merges are inert |
| The apply matrix compared only the two input fingerprints and managed state, so `apply` after `copier update` reported a validated no-op | An ordered classification that also compares template-source and render identity, with an explicit absent-manifest branch |
| The apply matrix had no absent-manifest branch at all, so initial install was unclassified | Branch A covers initial install and populated manifest-free targets |
| `selected_render_fingerprint` covered a hand-maintained subset that omitted `default_branch`, which appears in generated CI | Derived from a versioned immutable `RenderInput`, with field-perturbation tests |
| The supplied licence or private-notice bytes entered no fingerprint, so changing legal text was invisible to `apply` | `content_fingerprint` carries a dedicated licensing entry |
| The manifest was listed among the artifacts whose hashes the manifest records, which is unsatisfiable | The manifest is excluded from its own inventory; primary and derived state are separated |
| `.gitattributes` was bootstrap-managed and therefore drift-fatal, recreating the trap that moved `CONTRIBUTING.md` to seed-once | Not installed; hash comparison normalizes declared text artifacts internally |
| Transaction state used the git common directory, which linked worktrees share, so one journal serialized unrelated worktrees and `recover` could target the wrong checkout | Worktree-specific administrative path, absolute, with recorded target identity |
| The non-git state fallback was justified by being ignored, but `git clean -x` removes ignored files | No implicit fallback; an explicit `--state-dir` outside the target is required |
| The journal served as both live lock and durable recovery record, so a live writer could race recovery and differing `--state-dir` values bypassed exclusion | A per-target in-tree lock is separate from the durable journal |
| The licensing audit was scoped to block only the two licence-relocating modes | The audit gates every mode and precedes any licence-writing implementation |
| Determinism primitives left LF normalization, path grammar, and JSON decoding strictness unspecified | All specified, with boundary fixtures |
| The secret preflight claimed to distinguish "not configured" from "unavailable", which an empty secret cannot prove | Two states with event-specific likely causes, in a fixed trusted job |

### Defect corrections to revision 3

| Revision 3 defect | Correction |
| --- | --- |
| `add` changes the effective capability set and therefore the render input, while the text declared `reconcile` the only operation that may advance render identity | One normative identity-transition table; `add` advances render identity and preserves template-source identity |
| Gating validation keyed its exemption to "the applied bundle", which `add`, `restore`, and `reconcile` do not have, so any mutation on a project with an unreplaced slot would gate-fail and roll back | Gating is scoped to findings the operation introduced, with a narrow declared-scaffold clause for initial apply only |
| Finding comparison used `(code, path)` sets, which collapses repeated findings and cannot detect a worsened count | A structured readiness result with `(code, path, subject, rule)` identity, compared as a multiset |
| The claim that revision 2 had "no normalizer or allowlist" for source-CI conformance is false (`design.revision-2.md`) | The ledger is corrected; revision 2 normalized job IDs, `needs`, and permissions and allowed declared source-only steps |
| Revision 3 dropped revision 2's step-level accountability by discarding step bodies | Step identity is restored and extended to action pins and checkout credential behavior |
| Self-expiry was described as preventing allowlist accumulation, which it does not | The claim is corrected; entries carry owner, reason, and review-by metadata |
| A lifecycle test required `status` to report a previous hook failure, which `status` cannot know without executing an arbitrary hook | `status` reports mechanical readiness and "hook not evaluated"; the test is corrected |
| The transaction step list placed the gating-failure branch after the hook step | Ordering branches immediately on gating failure, before cleanup or hook execution |
| "Every command accepts `--target`" included `init`, which has no target | Scoped to commands that inspect or mutate a generated project |
| `--state-dir` was accepted only by mutating commands, so `status` and the plan commands could not observe the transaction state they report on | Accepted by every command that observes transaction state |
| Step 6 of the apply procedure was classified as a current-engine defect, which misdescribes an inherited or corrupted manifest | Classified as a render-contract violation, with both causes named |
| A template-source change on a GitHub snapshot was told to run `reconcile` without saying that snapshots have no Copier lineage to reconcile from | The diagnostic is generation-path aware and names a reachable action |
| Multi-file atomic visibility was implied by "atomic replacements" | Replaced by the accurate guarantee: recoverable planned-path transactionality |
| Blanket statements that drift blocks all mutations contradicted the per-operation rules | Per-operation drift behavior is tabulated |
| Path identity was checked once at preflight, leaving a symlink/rename TOCTOU window | Directory-anchored operations with no-follow semantics and re-verified identity |

### New additions in revision 4

| Addition | Purpose |
| --- | --- |
| Identity-transition table | One normative answer for what each operation may change |
| `RenderInput` schema and pure `render` boundary | Makes render identity derived rather than enumerated |
| Structured readiness-result contract | Makes gating comparison well-defined |
| Per-target lock, separate from the journal | Mutual exclusion that `--state-dir` cannot bypass |
| Durable transaction phases with write-ahead and fsync ordering | Makes recovery decidable after interruption |
| Plan digest for destructive reconciliation | Binds an overwrite to the preview that authorized it |
| Manifest primary/derived separation and optional checksum | Makes manifest integrity checkable |
| Populated manifest-free project contract | Says what such projects may do, rather than only what they may not |
| Batch inertness contract | Lets intermediate merges reach the default branch without changing behavior |

### Unchanged load-bearing decisions

Carried forward from revision 1 unless a table above says otherwise: snapshot profiles freeze at
creation; additions are recorded separately from the dependency closure; secrets are never accepted
or persisted; repository owner and name are never persisted; Copier owns version selection and merge;
transactions cover only planned paths and never claim to roll back hook-created artifacts; the
renderer is declarative and cannot execute capability-supplied code; template-owned validation is
Python 3.11 standard library only.

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

## Goals

- Produce a locally ready repository from adopter-supplied product content and explicit mechanical
  choices, without requiring that content to exist before the project can be compiled.
- Make the same `RenderInput` and template inputs produce byte-for-byte identical bootstrap-managed
  output.
- Require explicit intent-based profile selection and freeze its expansion at creation time.
- Support exact custom capability selection and additive post-bootstrap capability changes.
- Keep core validation independent of optional capabilities and external activation.
- Share one bootstrap engine across GitHub-snapshot and Copier generation paths.
- Give Copier and bootstrap non-overlapping update responsibilities.
- Preserve adopter-owned product content, detect drift in bootstrap-managed artifacts, and provide a
  supported remedy for that drift.
- Govern every change to project identity by one normative transition table.
- Make missing external secrets safe and actionable instead of causing noisy workflow failures.
- Produce durable adopter-facing delivery, update, capability, and GitHub setup documentation.
- Allow new declarative capabilities without changing the resolver or transaction engine.
- Make an interrupted mutation recoverable for every planned path.

## Non-goals

- Inventing or judging product requirements, README content, security policy, or legal terms.
- Judging whether the adopter's validation hook is substantively adequate for the product.
- Rolling back a completed, mechanically valid installation because the adopter hook failed.
- Claiming atomic visibility across multiple files.
- Accepting, storing, discovering, or writing secrets during bootstrap.
- Authoritatively diagnosing whether a repository secret is configured.
- Mutating GitHub repository settings, rulesets, branch protection, or external services.
- Capability removal, replacement, or arbitrary reconfiguration in v1.
- Re-expanding a stored snapshot when a named profile changes later.
- Migrating incompatible capability or manifest schemas.
- Bootstrapping or adopting a populated project that has no manifest.
- Giving GitHub snapshots a template update lifecycle.
- Reimplementing Copier's version selection, update merge, or conflict behavior.
- Providing native Windows execution guarantees.
- Providing a general-purpose template language, executable capability plugins, or trusted Copier
  tasks.
- Proving the semantic validity of an arbitrary adopter-owned GitHub Actions workflow from the
  generated-project validation boundary.
- Rolling back filesystem artifacts or external side effects created by the adopter validation hook.

## Identity transitions

This table is normative. Every operation, precondition, diagnostic, and test in this document must
agree with it. Revision 3 asserted that only `reconcile` could advance render identity while also
specifying that `add` changes the effective capability set, which is a render input; that
contradiction is resolved here.

Five identities are tracked:

| Identity | Meaning | Mutability |
| --- | --- | --- |
| `initial_mechanical_fingerprint` | The initial bundle's normalized mechanical answers | Immutable after initial install |
| `initial_content_fingerprint` | The initial bundle's content slot modes, content hashes, and licensing entry | Immutable after initial install |
| `template_source_fingerprint` | Engine, catalog, core definitions, schemas, compatibility fixture, maintenance inventory | Advanced only by `reconcile` |
| `render_identity` | The canonical digest of the current `RenderInput` | Advanced by `add` and `reconcile` |
| Managed inventory and hashes | Path, kind, mode, and hash of every bootstrap-managed artifact | Written by initial install; updated by `add`, `restore`, and `reconcile` |

The two initial fingerprints are immutable because they record what was applied, not what the project
now is. Current capability state lives in the frozen profile list, the explicit additions, and the
effective closure, and it is `render_identity` that reflects it. Without this separation, `add` would
mutate the very value that `apply` compares against, and re-running the original bundle after an
addition would misclassify.

| Operation | `initial_mechanical` | `initial_content` | `template_source` | `render_identity` | Managed inventory | Capability state |
| --- | --- | --- | --- | --- | --- | --- |
| `init` | Not applicable — no target | | | | | |
| `status` | Read | Read | Read and recompute | Read and recompute | Read and verify | Read |
| `plan`, `plan-add`, `plan-restore`, `plan-reconcile` | Read | Read | Read and recompute | Read and recompute | Read and verify | Read |
| `apply`, initial install | Sets | Sets | Sets | Sets | Sets | Sets |
| `apply`, equivalent input | Must equal | Must equal | Must equal | Must equal recomputed | Must equal | Unchanged |
| `add` | Must equal, unchanged | Must equal, unchanged | Must equal, unchanged | **Advances** | Updated | Extended, additively |
| `restore` | Must equal, unchanged | Must equal, unchanged | Must equal, unchanged | Must equal, **unchanged** | Bytes rewritten to recorded hashes; inventory unchanged | Unchanged |
| `reconcile` | Must equal, unchanged | Must equal, unchanged | **Advances** | **Advances** | Updated | Unchanged |
| `recover` | Restored | Restored | Restored | Restored | Restored | Restored |

`add` requires the current template-source identity to equal the manifest's, and directs the operator
to `reconcile` first when it does not. This keeps a capability addition from silently absorbing an
unrelated template update.

`restore`'s row is what makes it safe: it may write only bytes whose hash and mode already equal the
manifest's record, so it cannot introduce content, and it may not touch any identity. A single-path
`restore` therefore cannot certify a mixed render.

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
- It rejects an adopter `file` input that contains a reserved placeholder marker.
- It does not mutate a generated project or perform external operations, and accepts no `--target`.
- It refuses a non-empty output location instead of silently replacing a bundle.

### US-2: Bootstrap a generated project deterministically

As an adopter, I want to preview and explicitly apply a bundle so that the result is ready without
manual placeholder replacement.

Acceptance criteria:

- `plan` reports the exact create, replace, and delete set without mutation.
- `apply` performs initial install only from a scaffold recognized for the target's generation path,
  and refuses a populated target that has no manifest, naming the migration contract.
- Successful install makes `python3 scripts/validate-template.py` succeed and introduces no readiness
  finding other than the placeholder findings declared by the bundle's `scaffold` slots.
- `apply` then runs the adopter hook once and reports its point-in-time result. Neither a failing hook
  nor an expected scaffold finding rolls back the installation.
- `apply` exits 0 only when the complete canonical command would succeed, so a bundle with any
  `scaffold` slot exits 1 and names the slots that still hold placeholders.
- An equivalent reapply is a no-op with respect to the filesystem, and still runs the full readiness
  and reporting boundary and the adopter hook, so its exit code carries the same meaning as any other
  `apply`. An all-`scaffold` reapply therefore exits 1.
- Any exit-1 outcome after installation states plainly that bootstrap files were installed and that
  the repository is not yet locally ready.
- The project-validation hook is installed at `scripts/validate-project` with mode `0755`.
- The result does not depend on Nix unless `nix` is selected.
- Every classification outcome names a next action that exists for the target's generation path.

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
- The manifest contains only normalized mechanical state and hashes, and no legal prose.
- Licensing selection is mandatory and explicit, and the supplied bytes are covered by
  `content_fingerprint` under a dedicated entry.
- Bootstrap authors no legal terms and makes no legal-validity claim.
- Template Apache-2.0 text and bundled-skill provenance remain available in every licensing mode.
- The licensing and provenance audit completes before any licence-writing implementation, for every
  licensing mode.

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
- `add` advances `render_identity`, preserves `template_source_fingerprint`, and requires the current
  template-source identity to equal the manifest's, naming `reconcile` when it does not.

### US-7: Configure external integrations without secrets

As an adopter, I want locally complete integration files even before external secrets exist so that
readiness is distinct from activation.

Acceptance criteria:

- Bootstrap never accepts or persists secret values.
- The manifest records activation requirements, not live activation status.
- Missing secrets produce successful workflow skips and actionable job summaries.
- A read-only preflight job determines availability before any job with write permissions starts.
- The preflight is a fixed trusted job: no checkout, no third-party actions, no repository scripts, no
  untrusted expressions, no shell tracing, and no secret-bearing persisted output.
- Its only outputs are a literal availability boolean and constant guidance text.
- The preflight reports availability and, when unavailable, the likely causes for that event type. It
  does not claim to know whether a secret is configured.
- Durable documentation identifies every manual activation step.

### US-8: Reconcile derived artifacts after Copier update

As a Copier adopter, I want updated compatible compiler inputs to re-render derived outputs without
overwriting my project files or duplicating Copier's merge semantics.

Acceptance criteria:

- The documented sequence is `copier update`, `plan-reconcile`, `reconcile`, then canonical
  validation.
- Copier selects and merges template inputs; reconciliation only compiles derived outputs.
- Reconciliation preserves the exact effective capability set and normalized settings.
- It is the only operation that may advance `template_source_fingerprint`, and it may also advance
  `render_identity`, per the identity-transition table.
- It neither adds nor removes capabilities, changes settings, re-expands profiles, nor merges files.
- Copier conflict evidence or an incompatible catalog blocks all writes.
- Managed drift blocks reconciliation unless `--overwrite-drift` is given together with the plan
  digest emitted by `plan-reconcile --overwrite-drift`, which `reconcile` revalidates before writing.
- GitHub-generated projects have no Copier lineage and therefore no update lifecycle; their
  documentation states this plainly, and a template-source change on a snapshot is diagnosed as a
  local modification with a reachable next action.

### US-9: Extend the capability catalog declaratively

As a template maintainer, I want to add a compatible capability through declared data and fixtures so
that the resolver and transaction engine stay stable.

Acceptance criteria:

- A capability declares dependencies, settings, external requirements, owned artifacts with declared
  text or binary kind, contribution slots, and documentation fragments.
- Capability definitions cannot execute commands during bootstrap.
- Settings use a small typed schema and are explicitly declared non-secret.
- New compatible capabilities require no capability-specific branch in the resolver, renderer, or
  transaction engine.
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
- Their inputs are part of `RenderInput`, so a documentation-affecting change advances
  `render_identity`.
- Capability additions and reconciliation update affected managed documents in the same transaction
  as code and workflow artifacts.
- Direct edits are drift, reported by `status` and readiness, and resolved by `restore`.
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
- The readiness checker performs bounded structural and security-policy checks from the standard
  library and does not claim to be a complete YAML semantic validator.

### US-12: Recover interrupted mutations

As an adopter, I want an interrupted mutation to be detectable and recoverable so that bootstrap
does not leave managed ownership ambiguous.

Acceptance criteria:

- Every mutation acquires the per-target lock before staging, and `recover` acquires the same lock.
- Every mutation records a durable journal, fsynced, before the first replacement.
- The journal records durable phases, the normalized target identity, and every planned path's
  expected old and new hash and mode.
- `recover` refuses a target whose identity does not match the journal.
- A live writer cannot race recovery, two recoveries cannot race, and differing `--state-dir` values
  cannot bypass mutual exclusion.
- A gating-validation or write failure restores planned paths immediately, before cleanup or hook
  execution.
- An interrupted journal blocks later mutations.
- `recover` rolls back to the pre-operation state and never resumes forward.
- Recovery evidence survives `git clean -fdx` in a git working tree.
- Hook-created artifacts outside the planned path set are permitted by the PRD and are not removed by
  recovery.
- The guarantee is recoverable planned-path transactionality, not atomic multi-file visibility.

### US-13: Resolve managed drift

As an adopter, I want a supported way to return an edited managed artifact to its compiled state so
that an accidental edit does not permanently block the operations that depend on managed integrity.

Acceptance criteria:

- `status` reports every drifted managed path without mutation and without executing the hook.
- `plan-restore` shows the exact bytes that would be replaced, and `restore` applies the change
  transactionally.
- `restore` requires the current `template_source_fingerprint` and the recomputed `render_identity` to
  equal the manifest's, and requires each recompiled artifact's hash and mode to equal the manifest's
  record for that path.
- `restore` advances no identity and never touches seed-once or adopter files.
- A template-source or render mismatch causes `restore` to refuse and name `reconcile`.
- `restore --path` restores a named subset, is refused when a named path is not bootstrap-managed, and
  cannot change any global manifest field.
- Drift does not block `status`, any plan command, or `recover`.

## Decision record

| Topic | V1 decision | Proposed future change, if viable |
| --- | --- | --- |
| Bootstrap result | Installation and locally ready are separate; exit 0 requires both | Staged readiness reporting |
| Content completeness | Every slot is an adopter file or an explicit `scaffold` placeholder | Inline prose fields with explicit escaping |
| Slot completion | Derived from declared file markers, never from the manifest | Structured completion metadata if derivation proves insufficient |
| Hook sentinel detection | Byte level, so the hook may be any executable | Declarative command hooks |
| Profile semantics | Named profiles are one-time snapshots | Explicit live profiles or profile-plus-override policies |
| Initial catalog | Current integrations only, behind a generic catalog | Broader first-party catalog and stack presets |
| Catalog ecosystem | Repository-local trusted definitions | Third-party registries with provenance and trust policy |
| Selection default | No engine default; initializer may recommend `portable` | Guided recommendations |
| Content input | Referenced ordinary files in a self-contained bundle | Inline prose fields |
| Interaction | Initialize a bundle, then explicitly plan/apply | One-command convenience over the same engine |
| Lifecycle | Initial install, additive changes, same-contract drift repair, reconciliation | Removal, replacement, rebasing, reconfiguration |
| Identity transitions | One normative table; `restore` advances nothing, `add` advances render, `reconcile` advances both | None; load-bearing |
| Drift remedy | `restore` within contract; previewed `reconcile --overwrite-drift` otherwise | Interactive per-path merge |
| Destructive reconciliation | Bound to a plan digest that `reconcile` revalidates | None |
| Gating validation | Scoped to findings the operation introduced, plus a declared-scaffold clause for initial apply | Opt-in strict mode gating on the hook |
| Hook evidence | Point-in-time; never persisted, never replayed, never claimed by `status` | Cached evidence with explicit invalidation |
| External activation | Locally configured, externally unverified, safe skips | GitHub doctor, then authorized configuration writes |
| Secret diagnosis | Available, or unavailable with likely causes | Authoritative diagnosis in the GitHub doctor |
| Licensing | Explicit adopter decision; bytes fingerprinted; audit gates all modes | SPDX, SBOM, richer licence automation |
| Validation hook path | One canonical extensionless path; the rename is a documented breaking change | Interpreter adapters, native Windows support |
| Populated manifest-free projects | Remain on the pinned pre-bootstrap lifecycle; not bootstrapped, not adopted | An adoption lifecycle with preview and collision rules |
| Documentation | Four managed operational documents; `CONTRIBUTING.md` is seed-once | Managed regions or adopter fragments |
| Line endings | Hash comparison normalizes declared text artifacts; no managed `.gitattributes` | None |
| Renderer | Pure `render(RenderInput) -> RenderResult`, standard library only | Signed or sandboxed plugins |
| Copier integration | Copier updates inputs; bootstrap reconciles derived output | GitHub-snapshot adoption into Copier lineage |
| Transaction state | Per-target in-tree lock; durable journal in the worktree admin path or an explicit `--state-dir` | Configurable retention |
| Path safety | Directory-anchored, no-follow operations with re-verified identity | None |
| Manifest integrity | Primary and derived state separated; derived recomputed before trust | Signed manifests |
| Workflow validation | Standard-library bounded checks in the generated project; a real YAML parser in source-only fixtures | A portable structured parser |
| Delivery | One public release; internal batches with inert intermediate merges | Independent lifecycle releases |

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
- arbitrary YAML semantics cannot be fully checked from the generated-project boundary.

### Approach B: Mirror conditionals in Copier and Python — rejected

Copier would render its generation path while a separate Python implementation would mutate GitHub
snapshots. This creates two sources of truth for profiles, capability dependencies, documentation,
and output ownership.

### Approach C: Run bootstrap as a trusted Copier task — rejected

Copier tasks require an explicit trust decision and do not apply to GitHub repository-template
creation. Making task execution mandatory would weaken the no-surprise generation contract and still
leave a separate GitHub path.

## Architecture

### Compiler pipeline

```text
bundle + catalog + manifest
          |
          v
   adapters preload every byte-affecting input
          |
          v
   RenderInput (versioned, immutable)
          |
          v
   render(RenderInput) -> RenderResult      [pure]
          |
          v
   plan -> lock -> stage -> journal -> install
          |
          v
   gating validation (scoped to introduced findings)
          |
          v
   readiness reporting + adopter hook (point-in-time)
```

The functional core is pure. The effectful edge reads source bytes, acquires the lock, writes the
journal, installs the plan, invokes validation, and performs recovery. CLI and filesystem effects
depend on the model; the model never imports CLI or mutation code.

### Proposed source layout

```text
scripts/bootstrap-project.py

scripts/bootstrap/
  __init__.py
  cli.py            # argument parsing, exit codes, human-readable output
  inputs.py         # bundle loading, path grammar, confinement, normalization
  model.py          # RenderInput, ReadinessResult, fingerprints, immutable models
  catalog.py        # capability and profile definition loading
  resolver.py       # profile expansion, dependency closure, collision checks
  renderer.py       # pure render(RenderInput) -> RenderResult
  planner.py        # target inspection, ownership classification, plan construction
  transaction.py    # lock, journal, phases, staging, backups, install, rollback
  readiness.py      # structured readiness result and comparison
  diagnostics.py    # stable identifiers and rendering

.agentic-template/
  project.json                        # the manifest; bootstrap-managed output
  .lock                               # transient per-target lock; never committed
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

### File ownership

| Class | Owner and behavior |
| --- | --- |
| Copier/template inputs | Engine, catalog, render sources, validators, skills, static contracts, and `NOTICE.md`; Copier updates and merges these on its path |
| Bootstrap-managed output | Compiled CI, selected capability artifacts, and durable operational documents; exact hashes are enforced and `restore` recompiles them |
| Manifest | `.agentic-template/project.json`; bootstrap-managed but excluded from its own inventory, with its own integrity rules |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, `CONTRIBUTING.md`, root licence, and project-validation workflow; installed once and never regenerated in v1 |
| Adopter files | Product code, product documentation, `.gitattributes`, `.gitignore`, unrelated workflows, and all files outside declared template ownership |
| Transient state | `.agentic-template/.lock` and, when in-tree, staging directories; never artifacts, never hashed, never committed |
| Template-maintenance artifacts | Source tests, source workflow fixtures, the source-CI allowlist, historical source specs, and other paths in the maintenance inventory |

No path may belong to more than one class. Source validation rejects duplicate, nested, or
case-colliding ownership declarations.

`CONTRIBUTING.md` and `.gitattributes` are adopter-owned because both are ordinary adopter
configuration, and a managed drift-fatal file that adopters are expected to edit converts a normal
action into a blocked repository. The four `docs/*.md` operational documents remain managed because
they describe template mechanics the adopter does not author.

### Generation-path behavior

Copier configuration excludes bootstrap-managed output, seed-once adopter output, transient state, and
declared template-maintenance artifacts. Copier copies the engine, catalog, static contracts, and
update metadata. Initial install writes derived and seed-once files.

Because seed-once output is excluded rather than conditionally copied, the current
`_skip_if_exists: scripts/validate-project.py` entry is removed: seed-once ownership subsumes it, and
leaving both mechanisms in place would give one path two owners. The stale `tools` exclude, which
matches no existing path, is removed at the same time.

GitHub's repository-template operation copies the source tree unchanged. Initial install therefore
uses the maintenance inventory and known scaffold hashes to replace seed placeholders, remove
unselected capability artifacts, replace source CI with compiled project CI, and remove recognized
template-maintenance artifacts.

"Recognized scaffold" is defined per path and checked explicitly:

- **Copier path:** `.copier-answers.yml` exists, no manifest exists, and every seed-once path is
  either absent or byte-identical to the template's scaffold content.
- **GitHub path:** no `.copier-answers.yml` and no manifest exist, and every seed-once path is
  byte-identical to a known scaffold hash for a released template version.

Any unexpected bytes at a path proposed for replacement or deletion block the whole mutation.
Bootstrap never treats "looks like a template file" as sufficient evidence.

GitHub snapshots retain one-time semantics. `docs/template-updates.md` states plainly that a
GitHub-generated project receives no further template updates to its managed artifacts, and that
adopting Copier lineage is deferred work.

### Source-target protection

Every command that inspects or mutates a generated project accepts `--target PATH` and otherwise uses
the current directory, and displays the normalized target. `init` has no target and accepts no
`--target`.

Mutation refuses a Git remote that normalizes to the canonical template repository. This is defense in
depth rather than proof of repository identity; template forks and repositories without a remote
remain the operator's responsibility.

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
the final effective closure.

### Capability definition

A capability declares a stable ID and description; dependency IDs; setting definitions typed
`string`, `boolean`, or `enum`; validation constraints for every string used in a structured output
context; external activation requirements; exclusively owned output paths each declared `text` or
`binary`; contributions to named typed slots; documentation contributions; and fixture cases.

Definitions are data. A definition cannot choose arbitrary target paths, execute a command, load a
Python object, access the network, or read environment variables. Settings must be declared
non-secret. Unknown capabilities, unknown settings, missing required settings, settings for
unselected capabilities, and out-of-constraint values fail validation.

### Stable-ID compatibility contract

Within v1, an existing capability ID may update implementation artifacts and documentation but may not
silently add or remove a dependency, remove a setting, change a setting's type or meaning, make an
optional setting required, change external-prerequisite semantics incompatibly, or transfer ownership
of an existing path incompatibly.

Adding an optional setting with a deterministic default is compatible. A frozen compatibility fixture
records the v1 public surface, and `validate-template.py` compares the live catalog with it.

`pr-agent-gemini` encodes the backend in the ID. A `backend` setting would be more elegant, but
changing a setting is reconfiguration, which v1 does not support; a separate ID per backend keeps the
only supported transition — add a new capability — available.

### V1 capability-to-artifact mapping

| Capability | Principal managed output and contributions | External activation |
| --- | --- | --- |
| `semantic-release` | `.releaserc`, reusable semantic-release workflow, gated release job contribution | None beyond normal GitHub token permissions |
| `nix` | `flake.nix`, `flake.lock`, Nix setup action, Nix CI check contribution | None |
| `cachix-publish` | Cachix configuration and publish contributions; depends on `nix`; requires a non-secret cache-name setting | Existing Cachix cache plus `CACHIX_AUTH_TOKEN`; Cachix-specific work skips when unavailable while Nix continues uncached |
| `pr-agent-gemini` | `.pr_agent.toml`, review and trusted-command workflows, activation preflights, setup documentation | `GEMINI_API_KEY` |

The source catalog owns the final exact path list.

## Input contracts

### Bootstrap input bundle

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

For `custom`, `profile.capabilities` is mandatory. Other profiles reject that field.

Project name and default branch are constrained to explicit ASCII character classes so no Unicode
normalization question arises in fingerprinting. Repository owner and name are intentionally absent
because GitHub exposes repository identity at runtime and persisted slugs go stale after forks,
transfers, and renames.

### Content modes

Every content slot takes `{"mode": "file", "path": "..."}` or `{"mode": "scaffold"}`.

`scaffold` keeps bootstrap from becoming an authoring gate. An adopter can select a profile, compile
real CI, and start working within minutes, while readiness continues to fail and name exactly which
slots remain unreplaced. This preserves REQ-001.

Licensing has no scaffold mode. A repository whose licence file was invented by a tool is worse than a
repository with no licence at all.

### Declared placeholder markers

Slot completion is derived from the current files. Five markers are declared, and the template's
scaffold content for each slot contains exactly its own marker.

| Slot | Installed path | Marker | Detection |
| --- | --- | --- | --- |
| `readme` | `README.md` | `<!-- agentic-template:placeholder:readme -->` | UTF-8 text search |
| `prd` | `docs/prd.md` | `<!-- agentic-template:placeholder:prd -->` | UTF-8 text search |
| `security_policy` | `SECURITY.md` | `<!-- agentic-template:placeholder:security -->` | UTF-8 text search |
| `contributing` | `CONTRIBUTING.md` | `<!-- agentic-template:placeholder:contributing -->` | UTF-8 text search |
| `validation_hook` | `scripts/validate-project` | `agentic-template:unconfigured:validate-project` | Raw-byte substring search |

The hook sentinel is detected as an ASCII byte substring of the file's raw bytes, never by decoding.
The hook is an arbitrary executable, so it may be a compiled binary or use any encoding; requiring it
to be decodable UTF-8 would contradict toolchain neutrality. The four document markers are searched as
UTF-8 text because those slots are already required to be valid UTF-8.

`init` and `apply` reject a `file` input that contains its slot's reserved marker, or any other
declared marker, with `BOOTSTRAP_INPUT_RESERVED_MARKER`. Otherwise adopter content could impersonate
an unreplaced placeholder and permanently suppress its own readiness finding.

The manifest's content record is bootstrap-time input identity. It says what was applied, it is
consumed only by the apply classification, and it is never a claim about the current tree. An adopter
replaces a scaffolded file by editing it in place; nothing transitions, `status` and readiness stay
truthful because they never read the recorded mode, and no `finalize` operation exists.

### Content constraints

README, PRD, SECURITY, `CONTRIBUTING.md`, and supplied legal text must be valid UTF-8. The validation
hook may be any regular executable file and is copied byte-for-byte with mode `0755`. Referenced paths
are relative to `bootstrap.json`, must satisfy the canonical path grammar, must remain inside the
bundle after normalization, must be regular files, and may not traverse a symlink.

Licensing modes are `retain-apache-2.0` with no adopter path; `provided-project-license` with required
adopter legal text; and `private` with a required adopter private notice.

### Additive capability input

```json
{
  "schema_version": 1,
  "add_capabilities": ["nix", "cachix-publish"],
  "capability_settings": {}
}
```

Settings may be supplied only for newly requested capabilities and newly resolved dependencies. A
setting for an existing capability must match the persisted value or the operation fails.

## Determinism contract

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
newline or other control character cannot change how the tree is parsed; JSON escaping makes the `\n`
join unambiguous.

### Canonical path grammar

Every path recorded, hashed, planned, or accepted from input is a repository-relative POSIX path that
must:

- be valid UTF-8;
- be non-empty and not absolute;
- use `/` as the only separator, with no backslash anywhere;
- contain no empty component, no repeated separator, and no trailing separator;
- contain no `.` or `..` component;
- contain no NUL or other C0 control byte; and
- be byte-compared without case folding and without Unicode normalization.

Paths are never normalized into validity. A path that does not already satisfy the grammar is
rejected with `BOOTSTRAP_INPUT_PATH_GRAMMAR`. Two declared paths that differ only by case collide on
case-insensitive filesystems and are rejected at source validation.

### LF normalization

Every managed artifact is declared `text` or `binary`.

For a `text` artifact, the normalized form used for hashing and comparison is produced by:

1. requiring the bytes to decode as UTF-8, else `BOOTSTRAP_ARTIFACT_ENCODING`;
2. replacing every CRLF with LF;
3. replacing every remaining lone CR with LF;
4. requiring exactly one trailing LF, adding one if absent and collapsing a run of trailing LFs to
   one.

Mixed endings within one file normalize without error, because a checkout may produce them. A
`binary` artifact is hashed exactly, with no normalization and no encoding requirement.

Generated text is always installed in normalized form, so the on-disk bytes of a freshly installed
artifact already equal their normalized form. Comparison normalizes the on-disk bytes the same way, so
a `core.autocrlf=true` checkout does not report false drift.

Revision 2 solved line endings by installing a managed `.gitattributes`, which made ordinary adopter
configuration drift-fatal. Normalizing inside comparison removes the artifact entirely.
`docs/delivery-workflow.md` recommends `* text=auto eol=lf` as adopter-owned configuration.

### Strict JSON decoding

Every JSON document bootstrap reads — bundle, addition input, manifest, catalog, profiles, schemas,
inventory, allowlist — is decoded strictly:

- duplicate object keys are rejected via an `object_pairs_hook`, rather than last-wins;
- types are checked exactly, so `True` is not accepted where an integer is required and `1` is not
  accepted where a boolean is required;
- floats are rejected outright, as are NaN and infinities;
- integers must lie within ±2^53;
- object keys must be strings; and
- unknown keys are rejected wherever the schema is closed.

`canonical_json` accepts only strings, booleans, `null`, in-range integers, arrays, and string-keyed
objects.

### Other primitive rules

- Paths that are not valid UTF-8 are rejected. Symlinks are rejected anywhere in a hashed source or
  output tree.
- Only regular files are artifacts. Empty directories are outside the artifact model; an absent file
  is distinct from an empty file, which hashes as the SHA-256 of zero bytes.
- No Unicode normalization is applied anywhere. Adopter content bytes are preserved exactly, and
  mechanical identifiers are ASCII.
- `mode` reflects only the owner execute bit. Managed files are installed as exactly `0644` or `0755`
  independent of umask, and comparison ignores group and other bits, matching git's index model.

### RenderInput and render identity

`RenderInput` is a versioned, immutable value object defined in batch 1. It is the complete input to
rendering, and `render_identity = tagged(b"render-input", canonical_json(RenderInput))` — the
fingerprint is taken over exactly the canonical serialization of that object, not over a separately
maintained summary.

```text
RenderInput
  render_input_version            # integer; bumped when the schema changes
  generation_path                 # "copier" | "github"
  project.name
  project.default_branch
  licensing.mode
  licensing.content_sha256        # null for retain-apache-2.0
  profile.id
  profile.frozen_capabilities     # the one-time expansion, sorted
  explicit_additions              # sorted
  effective_capabilities          # the dependency closure, sorted
  capability_definitions          # id -> definition tree hash, for effective capabilities only
  core_inputs                     # core definition and static artifact tree hash
  settings                        # normalized, non-secret, per capability
  resolved_contributions          # every slot's contributions in final resolved order
  managed_document_inputs         # fragment identities feeding the four operational documents
  maintenance_cleanup             # "performed" | "skipped"
  seed_content_digests            # per slot: mode, and content hash where it affects managed output
```

The renderer is pure: `render(RenderInput) -> RenderResult`. Filesystem and environment adapters
preload every byte-affecting input into `RenderInput` before rendering begins. Renderer and resolver
code may not read the filesystem, the environment, the clock, or the network. Any undeclared read is a
contract violation caught by running the renderer against a `RenderInput` with no ambient access.

Unselected capabilities are excluded, so an unrelated catalog addition creates no false project drift.
That exclusion is safe because `validate-template.py` validates the complete catalog independently and
any catalog change moves `template_source_fingerprint`, which requires `reconcile`.

`maintenance_cleanup` is included because a skipped cleanup transfers paths to adopter ownership,
which changes what the durable documentation states.

Field-perturbation tests assert that changing **any** `RenderInput` field changes `render_identity`,
and that changing an unselected capability's definition does not.

### The four recorded fingerprints

| Fingerprint | Construction | Covers |
| --- | --- | --- |
| `initial_mechanical_fingerprint` | `tagged(b"mechanical", canonical_json(model))` | Project name, default branch, profile ID, explicit capability list, normalized settings, licensing mode |
| `initial_content_fingerprint` | `tagged(b"content", canonical_json(slot_map))` | Each content slot's mode and, for `file`, its content hash — plus a dedicated `licensing` entry carrying the mode and the supplied bytes' hash |
| `template_source_fingerprint` | `tree_hash(b"template-source", inputs)` | Engine modules, catalog, core definitions, schemas, compatibility fixture, maintenance inventory, source-CI allowlist |
| `render_identity` | `tagged(b"render-input", canonical_json(RenderInput))` | Everything above |

The licensing entry closes a revision 2 and 3 defect: licensing was a top-level bundle key rather than
a content slot, so the supplied legal bytes entered no fingerprint at all and an `apply` with
different legal text reported an equivalent no-op.

```text
slot_map = {
  "readme":          {"mode": "file",     "sha256": "..."},
  "prd":             {"mode": "file",     "sha256": "..."},
  "security_policy": {"mode": "scaffold"},
  "contributing":    {"mode": "scaffold"},
  "validation_hook": {"mode": "scaffold"},
  "licensing":       {"mode": "provided-project-license", "sha256": "..."}
}
```

## Apply classification

Two phases: independently reportable preflight, then a single ordered classification.

### Preflight

Preflight errors are independent, so all of them are collected and reported in stable sorted order
before anything else happens. No writes occur. Preflight covers bundle schema and value validation,
path grammar and confinement, reserved-marker rejection, UTF-8 requirements, target topology (unsafe
symlink, ownership collision, non-regular file where a file is expected), lock acquisition, Copier
conflict evidence, source-target protection, and state-directory validity.

Exit 1 for user-correctable preflight errors; exit 2 for an invalid catalog or engine contract.

### Ordered classification

Exactly one outcome, first match wins. Preflight has already passed.

**Branch A — no manifest.**

| Step | Condition | Outcome |
| --- | --- | --- |
| A1 | A recognized scaffold for this generation path | **Initial install.** Sets all identities |
| A2 | Anything else | `BOOTSTRAP_TARGET_NOT_SCAFFOLD`, exit 1. The target is populated and manifest-free; naming the migration contract, which does not bootstrap it |

**Branch B — manifest present.**

| Step | Condition | Outcome and next action |
| --- | --- | --- |
| B1 | Schema version is newer than this engine understands | Exit 2; upgrade the engine |
| B2 | Manifest unreadable, or its derived fields do not recompute | Exit 2; manifest recovery guidance |
| B3 | Pending journal | Exit 2; `recover` |
| B4 | `initial_mechanical_fingerprint` differs | `BOOTSTRAP_INPUT_MECHANICAL_CHANGED`, exit 1; `add`, or the deferred reconfiguration lifecycle |
| B5 | `initial_content_fingerprint` differs | `BOOTSTRAP_INPUT_CONTENT_CHANGED`, exit 1; seed content is adopter-owned, so edit the installed files in place |
| B6 | `template_source_fingerprint` differs from current inputs | `BOOTSTRAP_TEMPLATE_SOURCE_CHANGED`, exit 1; next action per generation path, below |
| B7 | Recomputed `render_identity` differs from the manifest | `BOOTSTRAP_RENDER_CONTRACT`, exit 2; render-contract violation, below |
| B8 | Any managed path's normalized hash or owner execute bit differs | `BOOTSTRAP_DRIFT_MANAGED`, exit 1; `restore` |
| B9 | All equal | **Equivalent reapply.** No filesystem change |

`render_identity` at B7 is recomputed from the manifest's persisted state — frozen profile, explicit
additions, effective closure, settings — and the current template inputs. It is not recomputed from
the bundle, because B4 has already established that the bundle's mechanical identity matches. This is
what lets `apply` run correctly after an `add`: the addition is part of persisted state, so the
recomputation includes it.

### B6 next action by generation path

| Generation path | Meaning | Next action |
| --- | --- | --- |
| Copier | Template inputs were updated, normally by `copier update` | `plan-reconcile`, then `reconcile` |
| GitHub snapshot | There is no update lineage, so the engine or catalog bytes were modified locally | Either `git restore` the reported template-input paths to undo an unintended edit, or run `plan-reconcile` and `reconcile` to accept the modification deliberately. The diagnostic states that reconciliation does not require Copier lineage and that accepting the change does not create one |

Revision 3 told snapshots to "reconcile" without acknowledging that they have no lineage to reconcile
from, which read as recommending an unavailable operation. Reconciliation is in fact available — it
consumes current inputs, not Copier metadata — so the correction is to say which situation the
operator is in and give both reachable actions.

### B7 render-contract violation

A render mismatch while B4, B5, and B6 all hold means the recorded `render_identity` disagrees with
what the current engine computes from the recorded state and the recorded template source. Two causes,
both engine-side rather than user-correctable:

- the engine's `RenderInput` construction or `render_input_version` changed without the
  template-source fingerprint changing, which is a template-contract defect; or
- the manifest's derived fields were altered or corrupted after being written.

Both exit 2. The diagnostic names the recorded and recomputed values and directs the operator to
manifest recovery guidance, not to a lifecycle command. Revision 3 called this "an engine defect",
which misdescribes the corrupted-manifest case and left an inherited manifest unexplained.

### Equivalent reapply

B9 makes no filesystem change, but it is not a silent success. It still:

- runs the complete readiness boundary and reports its structured result;
- runs the adopter hook once and reports its point-in-time result; and
- exits by the same rule as any other `apply` — 0 only when the complete canonical command would
  succeed.

An all-`scaffold` project therefore exits 1 on reapply, naming the slots that still hold placeholders,
exactly as its initial install did. Revision 3's "validated no-op, exit 0" was wrong on both counts.

## Readiness result and gating validation

### The structured readiness result

`check-project-readiness.py` and the bootstrap engine share one contract so that gating comparison is
well-defined rather than textual.

```text
ReadinessResult
  schema_version
  findings: ordered list of Finding

Finding
  code        # stable diagnostic identifier, e.g. READINESS_PRD_HEADING_MISSING
  path        # repository-relative canonical path, or "" for repository-level findings
  subject     # the specific thing at fault: a slot id, heading title, requirement id,
              # capability id, artifact path, or workflow job id
  rule        # the specific check that produced it, stable across message rewording
  severity    # "blocking" | "informational"
  message
  next_action
```

**Finding identity is the tuple `(code, path, subject, rule)`.** Comparison is over **multisets**, so a
finding that occurs twice is not collapsed into one, and an increase in occurrences is detectable.
Revision 3 compared `(code, path)` sets, which could not distinguish two missing PRD headings from
one, nor detect that a mutation had worsened an existing condition.

`severity: informational` findings — a skipped maintenance cleanup, a deprecation note — never make a
project unready and never gate a transaction.

### Gating validation

Gating decides rollback. It is neither the canonical command nor readiness in full. A mutation is
gated on what **it** did, not on the project's absolute readiness.

**Step 1, unconditional artifact verification.** Independently re-read every planned path after
installation and verify its normalized hash and owner execute bit against the plan. Any mismatch fails
the gate immediately. This runs **before** any exemption logic is considered, so no exemption can
excuse an artifact that was not written as planned.

**Step 2, `validate-template.py`** must succeed. No exemptions apply.

**Step 3, readiness comparison**, by operation:

| Operation | Baseline | Rule |
| --- | --- | --- |
| `apply`, initial install | Empty | The post-install blocking multiset must contain **exactly** the placeholder findings predicted for the bundle's declared `scaffold` slots, and nothing else. Pre-bootstrap findings are not inherited |
| `apply`, equivalent reapply | Pre-transaction result | No filesystem change occurred, so the multisets must be equal |
| `add`, `restore`, `reconcile` | Pre-transaction result, captured before staging | For every finding identity, the post count must be less than or equal to the baseline count. Genuinely pre-existing findings are retained; none may be introduced or worsened |

The initial-install rule is deliberately exact rather than permissive. Bootstrap installs the scaffold
placeholders itself, so it knows precisely which placeholder findings it should produce — one per
declared `scaffold` slot, at that slot's path, with that slot's marker rule. Accepting a superset would
let a defective install hide behind the exemption; inheriting arbitrary pre-bootstrap findings would
let scaffold state excuse unrelated breakage.

The `add`/`restore`/`reconcile` rule is what makes those operations usable at all. A project whose PRD
is still a placeholder is unready, and it must remain possible to add a capability to it. Revision 3
keyed the exemption to "the applied bundle", which those operations do not have, so every mutation on
an incomplete project would have gate-failed and rolled back.

Exit status is separate from rollback throughout. Gating decides whether the installation survives;
the canonical command decides the exit code.

## Project manifest

`.agentic-template/project.json` separates primary state from derived state, because revision 2 and 3
listed the manifest among the artifacts whose hashes the manifest records — a self-reference that
cannot be satisfied.

```text
{
  "schema_version": 1,
  "state": {                          # primary; the source of truth
    "generation_path",
    "project": {"name", "default_branch"},
    "licensing": {"mode"},            # mode only; never legal prose
    "profile": {"id", "frozen_capabilities"},
    "explicit_additions",
    "settings",
    "content_slots",                  # applied modes; input identity, not tree state
    "maintenance_cleanup": {"status", "retained_paths"},
    "initial_mechanical_fingerprint",
    "initial_content_fingerprint",
    "template_source_fingerprint"
  },
  "derived": {                        # recomputable; verified before trusted
    "effective_capabilities",
    "render_identity",
    "render_input_version",
    "external_activation_requirements",
    "managed_artifacts": [            # excludes this manifest
      {"path", "kind", "mode", "sha256"}
    ]
  },
  "checksum": "..."                   # tagged over canonical_json of the payload minus this field
}
```

### Manifest integrity

- **The manifest is excluded from `managed_artifacts`.** It is bootstrap-managed, but its integrity is
  established by recomputation and its own checksum rather than by a self-referential hash.
- **Derived fields are recomputed before they are trusted.** Every read recomputes the effective
  closure from the frozen list plus additions, the render identity from the reconstructed
  `RenderInput`, and the expected managed inventory from the effective capability set. A mismatch is
  `BOOTSTRAP_MANIFEST_DERIVED_MISMATCH`, exit 2 — never a silent repair, because a manifest that
  disagrees with itself cannot be used to decide what the project should contain.
- **`checksum`** is `tagged(b"manifest", canonical_json(document without the checksum field))`. It
  detects truncation and casual editing; it is not a security control.
- **Corrupt or unreadable manifest** exits 2 with explicit guidance, and never suggests `restore`.
  `restore` reads the manifest to decide what to write, so it cannot repair the thing it depends on.
  Guidance in order: `git restore .agentic-template/project.json` if it is tracked and a good version
  exists; `recover` if a journal is pending; re-run `apply` from the original bundle only if the
  project is still a recognized scaffold; otherwise reconstruct manually with `plan` output as the
  reference.

The manifest never contains product prose or legal text, input source paths, repository owner or name,
timestamps, machine-specific absolute paths, secrets or secret-presence claims, live GitHub state, any
claim about a seed-once file's current content, or a hash that would make seed-once content managed.

On Copier projects, source version and lineage stay in `.copier-answers.yml`. GitHub snapshots record
content identity only and invent no tag or commit.

### Manifest schema lifetime

Every v1 engine must read every valid schema-version-1 manifest. Compatible updates may add optional
fields with deterministic defaults but may not reinterpret existing fields or require a new field from
an old manifest. An unknown newer schema fails before any write.

## CLI contract

```text
python3 scripts/bootstrap-project.py init --output PATH [--init-answers FILE]

python3 scripts/bootstrap-project.py status          [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py plan            --answers PATH/bootstrap.json
                                                    [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py plan-add        --answers addition.json
                                                    [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py plan-restore    [--path PATH]... [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py plan-reconcile  [--target PATH] [--state-dir PATH]
                                                    [--overwrite-drift] [--out FILE]

python3 scripts/bootstrap-project.py apply     --answers PATH/bootstrap.json [--target PATH]
                                               [--state-dir PATH] [--leave-maintenance-artifacts]
python3 scripts/bootstrap-project.py add       --answers addition.json [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py restore   [--path PATH]... [--target PATH] [--state-dir PATH]
python3 scripts/bootstrap-project.py reconcile [--target PATH] [--state-dir PATH]
                                               [--overwrite-drift --plan FILE]

python3 scripts/bootstrap-project.py recover   [--target PATH] [--state-dir PATH]
```

`--target` is accepted by every command that inspects or mutates a generated project. `init` accepts
none, because it writes a bundle and never touches a project.

`--state-dir` is accepted by every command that observes transaction state, including `status` and all
plan commands. Revision 3 gave it only to mutating commands, so `status` could report "no pending
journal" while a journal existed in a state directory it never looked at.

`init` creates a complete reviewable bundle only, using a temporary sibling and installing it only
after validation.

`status` is read-only. It reports generation path, frozen profile, explicit additions, effective
capability set, unreplaced slots derived from file markers, every drifted managed path, recorded and
recomputed identities, maintenance-cleanup status with retained paths, declared activation
requirements, and any pending journal or held lock. It **never executes the adopter hook** and never
claims a hook outcome: it reports mechanical readiness and then `adopter hook: not evaluated; run
python3 scripts/validate-repository.py`. It exits 0 when it can describe the project — including when
what it describes is drift or unreadiness — and 2 when the manifest is unreadable or corrupt or
internal state is invalid.

`restore` repairs drift within the recorded contract, per the identity-transition table. Its
preconditions are the manifest being readable with derived fields recomputing, no pending journal, safe
target topology, current `template_source_fingerprint` equal to the manifest's, recomputed
`render_identity` equal to the manifest's, the persisted effective set resolving exactly, every
requested path being manifest-managed, and each recompiled artifact's hash and mode equalling the
manifest's record. The last precondition is what makes it safe: it can write only bytes the manifest
already certifies.

`reconcile` may advance both template-source and render identity. `--overwrite-drift` requires
`--plan FILE` containing the digest emitted by `plan-reconcile --overwrite-drift --out FILE`.

`--leave-maintenance-artifacts` is the supported override for a maintenance inventory that no longer
matches. It skips cleanup, records the retained paths in `state.maintenance_cleanup`, and transfers
those paths to adopter ownership; no later cleanup command exists because removing an adopter-owned
file needs none. Readiness reports the skip as `informational`. Because the outcome is part of
`RenderInput`, it also changes what the durable documentation says.

All plan commands run every preflight possible without installing, and report stable ordered path
operations with old and new hashes. They never invoke the adopter hook.

Exit codes:

- `0`: the complete canonical command would succeed;
- `1`: user-correctable input, readiness, activation, validation, or drift problem — including a
  completed installation whose adopter hook failed or whose scaffold slots remain; and
- `2`: usage error, invalid catalog or engine contract, manifest corruption, render-contract
  violation, internal error, pending recovery, or recovery failure.

## Plan digest for destructive reconciliation

`reconcile --overwrite-drift` destroys adopter edits to managed files, so it must be bound to the
preview that authorized it.

`plan-reconcile --overwrite-drift --out FILE` writes a plan document containing the normalized target
identity, the resolved operation list, each path's expected old hash and mode and new hash and mode,
the source and render identity the plan was computed against, and

```text
plan_digest = tagged(b"reconcile-plan", canonical_json(plan_document_without_digest))
```

`reconcile --overwrite-drift --plan FILE` then:

1. re-reads the plan and recomputes its digest, rejecting any mismatch;
2. verifies the recorded target identity against the current target;
3. recomputes the plan from current state and requires an exact match, so nothing changed between
   preview and execution; and
4. proceeds only then.

`--overwrite-drift` without `--plan` is a usage error, exit 2. There is no interactive confirmation
path, so the contract is identical in a terminal and in automation; the same two commands are the
whole procedure.

## Transaction, lock, and recovery semantics

The guarantee is **recoverable planned-path transactionality**: every planned path can be returned to
its pre-operation state. Bootstrap does not provide atomic multi-file visibility — a concurrent reader
can observe a partially installed plan — and does not claim it. Revision 3's "same-filesystem atomic
replacements" implied otherwise.

### The lock, separate from the journal

Revision 3 used the journal as both live lock and durable record, which let a live writer race
`recover` and let two invocations with different `--state-dir` values proceed simultaneously.

- The lock is `<target>/.agentic-template/.lock`, **inside the target tree**, because the target is the
  shared resource. Its location cannot vary with `--state-dir`, so no state-directory choice bypasses
  mutual exclusion.
- It is acquired by every mutating command and by `recover`, before staging, via `O_CREAT | O_EXCL`
  plus an advisory `flock` on the descriptor. The `flock` makes an abandoned lock file from a killed
  process detectable rather than permanently fatal.
- It records the holder's PID, the operation name, and the normalized target identity. `status` reports
  a held lock.
- It is transient: never committed, never hashed, never an artifact, excluded from Copier and from
  every ownership class except transient state.

The journal is durable recovery evidence and is not a lock. A pending journal blocks mutation because
the project's state is unknown, not because another process is running.

### Durable phases and write-ahead ordering

The journal records one of:

| Phase | Meaning | `recover` action |
| --- | --- | --- |
| `PREPARING` | Journal written and fsynced; no target path replaced yet | Discard staging; no target path needs restoring |
| `APPLYING` | At least one planned path may have been replaced | Restore every planned path from backups, verifying hashes |
| `COMMITTED` | Every planned path installed and verified; cleanup not yet finished | Finish cleanup only; never roll back |

Ordering:

1. Acquire the lock.
2. Validate inputs, definitions, target topology, old hashes, and rendered bytes.
3. Stage every new file in a staging directory on the target's filesystem. Write, fsync each file,
   then fsync the staging directory.
4. Copy every replaced or deleted planned path into backups. Fsync each backup, then the backup
   directory.
5. Write the journal in phase `PREPARING` with every expected old and new hash and mode, fsync the
   journal file, then fsync its parent directory. **No target path has been touched yet.**
6. Update the journal to `APPLYING` and fsync.
7. Install each operation in deterministic order, fsyncing each replaced file and its parent
   directory.
8. Re-read and verify every planned path's normalized hash and mode.
9. Update the journal to `COMMITTED` and fsync.
10. Run gating validation. **On failure, branch immediately to rollback — before any cleanup and
    before the adopter hook runs.**
11. On gating success, remove backups, remove the journal, fsync the state directory, then release the
    lock.
12. Run the adopter hook once and report its point-in-time result.

Rollback restores every planned path from its verified backup, using the same directory-anchored
operations, then removes the journal and releases the lock. If restoration cannot complete, the
journal is left in place and the failure is reported with the exact paths.

### Path identity and TOCTOU

Revision 3 validated topology at preflight and then operated on paths by name, leaving a window in
which a path could be replaced by a symlink between check and use.

Every backup, replacement, and rollback operation is directory-anchored:

- open each planned path's parent directory with `O_DIRECTORY | O_NOFOLLOW` and keep the descriptor;
- resolve, stat, open, rename, and unlink relative to that descriptor using `dir_fd`, never by
  re-walking the path string;
- open target files with `O_NOFOLLOW` so a symlink substituted at the final component fails rather
  than being followed;
- record each parent directory's device and inode when the descriptor is opened, and re-verify with
  `fstat` on the descriptor before each mutating step; and
- verify the pre-existing file's device, inode, and normalized hash immediately before replacing it,
  under the same descriptor.

Any identity change between check and use aborts the transaction and, once past `APPLYING`, triggers
rollback. These primitives are available in the Python 3.11 standard library on Linux and macOS via
`os.open`, `os.stat`, `os.rename`, and `os.unlink` with `dir_fd`. Where `O_NOFOLLOW` or `dir_fd` is
unavailable, bootstrap refuses to mutate rather than degrading silently, which is consistent with not
guaranteeing native Windows execution.

### State directory resolution

Durable state lives in the worktree-specific git administrative directory, resolved from the
**verified** target as an absolute path:

```text
git -C <verified target> rev-parse --path-format=absolute --git-path agentic-template
```

`--git-path` is worktree-aware, unlike the shared common directory that revision 2 used, so linked
worktrees do not serialize each other and `recover` cannot act on another worktree's plan.
`--path-format=absolute` removes any dependence on the invoking working directory; a relative result
from an older git is resolved against the verified target and re-verified.

| Situation | Behavior |
| --- | --- |
| Primary worktree | Use the resolved administrative path |
| Linked worktree | Use the resolved per-worktree path; independent of the primary |
| Submodule | Use the submodule's own administrative path; the superproject's is never used |
| Bare repository | Refuse: `BOOTSTRAP_TARGET_BARE_REPOSITORY` |
| Git unavailable, or target is not a working tree | Refuse unless `--state-dir` is given: `BOOTSTRAP_TARGET_NO_GIT` |

When `--state-dir PATH` is given it must be an existing directory, not a symlink at any component,
outside the target tree, owned by the invoking user, not group- or world-writable, and on a filesystem
that supports the required operations. State is namespaced within it by the target's identity, so one
state directory may serve several targets without collision. Bootstrap creates the per-target
subdirectory with mode `0700`.

There is no implicit in-tree fallback. An ignored in-tree directory is not protected, because
`git clean -x` removes ignored files.

Recovery evidence for tracked files also exists in git. When backups are missing or their hashes do
not match the journal, `recover` fails with `BOOTSTRAP_RECOVERY_EVIDENCE_MISSING` and directs the
operator to `git status` and `git restore` for tracked paths rather than guessing.

### Drift behavior by operation

Revision 3 asserted both that drift blocks all mutations and that specific operations tolerate it.

| Operation | Behavior with managed drift present |
| --- | --- |
| `status`, every plan command | Reports it; never blocked |
| `recover` | Proceeds; it restores planned paths regardless |
| `apply` | Blocked at B8; next action `restore` |
| `add` | Blocked; next action `restore` |
| `restore` | This is its purpose |
| `reconcile` | Blocked unless `--overwrite-drift` with a valid plan digest |

## The adopter hook

The hook is adopter-owned, may be any executable, and is invoked directly rather than through Python.

- It runs **once**, after the transaction has committed, and never gates or reverses the installation.
- A failing hook produces exit 1 with the installation retained, reported as "bootstrap files were
  installed; the repository is not locally ready".
- Its result is **point-in-time evidence**. It is never written to the manifest, never cached, and
  never replayed.
- `status` does not execute it and does not claim any past or present outcome. It reports mechanical
  readiness and directs the operator to the canonical validator.

Revision 3 both stated that hook evidence is point-in-time and required a lifecycle test in which
`status` reported a previous hook failure. `status` cannot know that without executing an arbitrary
program, which a read-only inspection command must not do. The test is corrected accordingly.

Gating validation covers `validate-template.py` and readiness only. Stage 3 of the canonical command
is the adopter's, and its failure means the repository is not locally ready without meaning the
installation was wrong.

## Reconciliation contract

```text
copier update --vcs-ref <tag>
python3 scripts/bootstrap-project.py plan-reconcile
python3 scripts/bootstrap-project.py reconcile
python3 scripts/validate-repository.py
```

Copier owns source selection, version metadata, three-way merging, and conflict reporting for the
files it copies. Reconciliation reads the updated compatible inputs and the existing manifest, then
recompiles only bootstrap-managed outputs.

Reconciliation requires a schema the engine understands; a manifest whose derived fields recompute; a
compatible capability catalog; no unresolved Copier conflicts; the persisted effective set remaining
resolvable without adding or removing an ID; and either no managed drift or `--overwrite-drift` with a
valid plan digest.

It may advance `template_source_fingerprint` and `render_identity` and update managed hashes. It may
not re-expand a profile, change the frozen profile list or explicit additions, modify seed-once or
adopter files, select a template version, merge drift, or invoke an implicit migration.

## Migration from the pre-bootstrap template

V1 changes the canonical hook path from `scripts/validate-project.py` to `scripts/validate-project`
and introduces the manifest. This is a breaking template-contract change, released with migration
instructions, which `docs/prd.md` permits for a change that makes a conforming project unready.

### What the rename does and does not do

```text
git mv scripts/validate-project.py scripts/validate-project
chmod +x scripts/validate-project
```

**Does:** move the adopter's existing hook to the path the v1 contract requires, so
`validate-repository.py` and readiness locate it and the project passes canonical validation again.

**Does not:** create a manifest; bootstrap the project; select a profile or capabilities; compile CI;
install durable documentation; make `add`, `restore`, or `reconcile` available; or give a GitHub
snapshot an update lifecycle. A renamed project is a **populated manifest-free project**, which is
exactly the target `apply` refuses at branch A2.

### Supported contract for populated manifest-free projects

Such projects remain on the pre-bootstrap lifecycle, and that lifecycle is supported for the life of
v1:

- `validate-template.py`, `check-project-readiness.py`, and `validate-repository.py` continue to accept
  them, with readiness reporting them as unbootstrapped at `informational` severity rather than
  failing them for the absence of a manifest.
- They receive no bootstrap-managed artifacts, and no bootstrap mutation applies to them.
- Copier projects **pin** the last pre-bootstrap template release for template updates and stop
  updating past it. The v1 release notes state the pinned tag explicitly.
- Adopting such a project is deferred work with its own preview, collision, and ownership-transfer
  design.

### Ordering for Copier projects

The rename and the breaking update must be ordered, because Copier's exclude configuration changes in
v1:

1. Commit or stash all work; the migration must start from a clean tree.
2. Run `copier update --vcs-ref <v1 tag>` and resolve any conflict Copier reports.
3. Perform the rename above. Because v1 excludes seed-once paths, Copier neither deletes the old hook
   nor creates the new one; the adopter owns both sides of the move.
4. Run `python3 scripts/validate-repository.py` and fix any remaining diagnostic.

Reversing steps 2 and 3 leaves the project briefly with a hook at neither expected path, so the
release notes give this order explicitly.

### Migration preconditions and failure handling

- **Preconditions:** a clean working tree; `scripts/validate-project.py` exists and is a regular file;
  `scripts/validate-project` does not already exist.
- **Destination collision:** if both paths exist, stop. The adopter chooses which is authoritative;
  the release notes state that having both is ambiguous and that no tool will guess.
- **Executable mode:** verify the owner execute bit after the move and set it explicitly, because some
  checkout and archive paths do not preserve it.
- **Validation:** `python3 scripts/validate-repository.py` must pass afterwards.
- **Rollback:** the move is a single tracked rename, so `git restore --staged --worktree scripts/`
  reverts it. No bootstrap state is created, so nothing else needs undoing.

An end-to-end fixture generates a project from the previous template release, runs `copier update` to
the v1 tag, performs the rename, and asserts canonical validation passes and no bootstrap artifact was
created.

## GitHub workflow architecture

### Stable project-validation boundary

Bootstrap-managed CI contains a reusable-workflow job named `Project validation` that calls
`.github/workflows/project-validation.yml`. The caller declares `contents: read`, passes no named or
inherited secrets, and has no privileged environment. The seeded adopter workflow declares
`on.workflow_call`, checks out without persisted credentials, runs on the supported GitHub-hosted
runner, invokes `python3 scripts/validate-repository.py`, and uses no secret and no write-capable
permission.

Adopters may add jobs, matrices, and toolchain setup inside that workflow while preserving the
security and canonical-validation contract. GitHub constrains reusable-workflow permissions so they can
be maintained or reduced through the call chain, not elevated.

The standard-library readiness checker performs bounded checks for presence, recognizable
`workflow_call`, canonical command, absence of secret passing or references and privileged environment
declarations, and the managed caller's exact hash. It does not claim general YAML parsing. GitHub
remains the runtime syntax authority for adopter modifications.

### Secret-dependent capability jobs

Secret-dependent workflows split authority into a read-only availability preflight and a privileged
job that starts only when preflight returned available and normal event trust conditions pass.

The preflight is a **fixed trusted job**, because it is the one place a secret is read:

- no `actions/checkout` and no access to repository content;
- no third-party or local actions — only `runs-on`, `env`, and a literal `run` step;
- no repository script execution, so nothing the adopter or an attacker can modify participates;
- no untrusted expression interpolation; event data is never inlined into the script;
- no `set -x` or other shell tracing, and no command echoing;
- the secret is referenced exactly once, compared for emptiness, and never printed, written to a file,
  or placed in an artifact; and
- its only outputs are a literal boolean `available` and constant guidance text.

Two states, not three:

| State | Condition | Guidance |
| --- | --- | --- |
| Available | The secret resolves to a non-empty value | Proceed |
| Unavailable in this run | Anything else | Constant text listing the likely causes for this event type, and a link to `docs/github-setup.md` |

Revision 2 claimed a third state distinguishing "not configured". An empty secret cannot prove that:
GitHub withholds Actions secrets from pull requests raised from forks and from Dependabot-triggered
runs, repository and organization policy can restrict them further, and a configured secret may
legitimately be empty. Authoritative diagnosis belongs to the proposed GitHub configuration doctor.

Two tests protect this:

- a **structural policy test** asserting the preflight job contains no checkout, no `uses:`, no
  reference to a repository path, no untrusted expression, and exactly one secret reference; and
- a **synthetic canary test** running the preflight with a known sentinel value in the secret and
  asserting the sentinel appears nowhere in logs, step outputs, job outputs, or artifacts.

The PR Agent review and trusted-comment workflows apply this pattern to `GEMINI_API_KEY`. The Cachix
path skips Cachix-specific setup and publishing when `CACHIX_AUTH_TOKEN` is unavailable, letting Nix
validation continue uncached; when available, publishing is additionally gated on the default-branch
event and successful validation, and an invalid or unavailable configured cache fails as an activation
error rather than silently disabling Nix validation.

### Release graph

When `semantic-release` is selected, release runs only on the configured default branch after the
complete adopter project-validation workflow, every selected managed capability check, and any core
delivery-contract job the generated graph requires. The release job retains its last-moment branch-tip
eligibility check. Without `semantic-release`, no release workflow or job is emitted.

### Template-source CI conformance

The template source is effectively an `integrated`-profile project, and its hand-written
`.github/workflows/ci.yml` will drift from the compiled render. A source fixture renders `integrated`
CI and compares it with the source workflow under a defined normalization.

Revision 2 normalized job IDs, `needs`, and permissions and allowed declared source-only **steps**.
Revision 3 dropped step bodies entirely, losing that accountability — and its ledger wrongly claimed
revision 2 had no normalizer. Revision 4 restores step-level accountability and extends the graph
normalization.

**Graph normal form**, per workflow:

- triggers: event names with their filters, normalized and sorted;
- concurrency group and cancel-in-progress;
- job topology: job IDs and each job's sorted `needs` set;
- effective permissions per job, with workflow-level defaults resolved into each job;
- `environment` references;
- `runs-on`, including matrix expansion into the concrete set of generated jobs;
- `container` and `services` images with their pinned digests or tags;
- `if` conditions, normalized for whitespace only;
- called-workflow references with their `with` inputs and `secrets` declarations, including whether
  `secrets: inherit` appears; and
- `timeout-minutes` and `continue-on-error`.

**Step normal form**, per step:

- for `uses` steps: the action reference, its pin (the 40-character SHA where present, plus any tag
  comment), and the security-relevant `with` keys — `persist-credentials`, `ref`, `repository`,
  `token`, and `submodules`;
- for `run` steps: the shell, and a stable hash of the command text after normalizing line endings and
  stripping trailing whitespace; and
- for both: `if`, `env` key names (not values), and `working-directory`.

Comparison is over these normal forms. Source-only differences are permitted **only** through explicit
entries in `.agentic-template/source-ci-allowlist.json`, each carrying the job or step identity, the
reason, an owner, and a review-by date. The fixture fails when a difference is not covered by an
entry, and also when an entry no longer corresponds to a real difference.

Self-expiry prevents **stale** entries. It does not prevent accumulation of genuine differences —
revision 3 claimed it did. The review-by metadata exists so that accumulation is at least visible and
attributable; keeping the count low remains a maintainer judgement, and the fixture reports the
current entry count so growth is observable.

**Parsing.** This is a source-only fixture and a template-maintenance artifact, so it is not bound by
the generated project's standard-library-only constraint. It requires a real YAML parser, which the
repository does not currently have: `flake.nix` provides bare `python3` and `actionlint`, and bare
`python3` does not include PyYAML. Batch 5a therefore adds `python3.withPackages (ps: [ ps.pyyaml ])`
to the dev shell and the corresponding flake check.

The fixture is Nix-gated: it runs inside the dev shell and in the `nix flake check` derivation, and it
skips with an explicit "parser unavailable" report outside them. This keeps a third-party parser from
becoming a hidden dependency of the portable generated-project boundary. `actionlint` continues to lint
the source and every generated workflow fixture.

No claim is made that a standard-library checker can generally parse Actions YAML. The standard-library
checks in `check-project-readiness.py` remain deliberately bounded — presence, recognizable
`workflow_call`, canonical command, absence of secret passing and privileged environment declarations,
and the managed caller's exact hash — and are documented as bounded rather than semantic.

## Validation boundaries

### `scripts/validate-template.py`

Validates reusable template machinery without assuming a bootstrapped instance: bootstrap, addition,
and manifest schemas; profiles and the complete capability catalog; dependency topology; setting
declarations and defaults; output ownership, declared kinds, and composition slots; the `RenderInput`
schema and renderer purity; canonical path grammar across every declared path; the template-maintenance
inventory and the source-CI allowlist's structure; and the stable capability compatibility fixture.

Python 3.11 standard library only. It executes no capability content and no adopter hook.

### `scripts/check-project-readiness.py`

Emits a `ReadinessResult`. Without a manifest it behaves as today and reports the project as
unbootstrapped at `informational` severity. With a manifest it additionally checks manifest schema,
checksum, and internal topology; that derived fields recompute; profile snapshot, additions, and
effective set; fingerprint structure; managed artifact modes and normalized hashes; licensing decision
and required preserved provenance; required durable documentation; hook presence and mode at the
canonical path; the seeded workflow's bounded contract; activation declarations; retained maintenance
paths, reported informationally; and the absence of declared placeholder markers in any slot.

A template-source mismatch is reported as "reconcile required". Individual managed hash mismatch is
drift, with `restore` as the next action.

### `scripts/validate-project`

The canonical path for the adopter-supplied executable. It owns product-specific validation, chooses
its own toolchain, and may create normal validation artifacts. Native Windows execution is not a v1
guarantee.

### `scripts/validate-repository.py`

The canonical ordered boundary: template contract, project readiness, adopter project validation.
Stages 1 and 2 gate the bootstrap transaction. Source-only fixtures and matrix suites are not added to
this portable boundary.

## Licensing and provenance

Bootstrap requires one explicit licensing choice, with no default and no scaffold.

For `retain-apache-2.0` the source Apache-2.0 text remains root `LICENSE`. For
`provided-project-license` and `private` the adopter's text becomes root `LICENSE`, `NOTICE.md` is
kept, and the template Apache-2.0 text is retained at `LICENSES/Apache-2.0.txt`.

The supplied bytes are covered by `initial_content_fingerprint` under the dedicated `licensing` entry,
so changing legal text is visible to `apply`. The bytes themselves are never stored in the manifest.

**The licensing and provenance audit is a prerequisite to any licence-writing implementation**, not a
final release check, and it gates every mode. It must inspect every bundled skill's upstream licence
and notice requirements; confirm whether the proposed Apache and notice locations satisfy
redistribution obligations; identify any notice that must remain verbatim; define how adopter
additions to notices are preserved; and amend this design and an ADR if the required layout differs.

Revision 3 scoped the audit to the two licence-relocating modes, on the theory that retaining
Apache-2.0 at the root raises no new question. `NOTICE.md:15` requires reviewing upstream skill
licences "before redistributing this template", and every generation path redistributes those skills
regardless of which text sits at the root.

The audit may strengthen preservation requirements but may not authorize bootstrap to invent legal
terms or declare a project legally valid. This is a design gate, not a legal-validity opinion.

## Durable adopter documentation

Four bootstrap-managed documents, rendered from core and selected capability fragments, with their
inputs in `RenderInput`:

- `docs/delivery-workflow.md`: canonical validation, CI and release gates, review flow, recovery, and
  the recommended adopter-owned `.gitattributes` configuration;
- `docs/template-updates.md`: generation path, Copier lineage or its absence, reconciliation, drift,
  `restore`, the plain statement that GitHub snapshots receive no further managed updates, and the
  populated manifest-free contract;
- `docs/capabilities.md`: frozen profile, additions, effective set, displayable settings, and
  dependencies; and
- `docs/github-setup.md`: required secrets, the two preflight states with their likely causes including
  fork and Dependabot runs, Actions and ruleset steps, and the distinction between release and merge
  gates.

Each header names the document as managed and directs project-specific prose to `CONTRIBUTING.md`, the
README, or product documentation. Additions and reconciliation update them atomically with related
artifacts; direct edits are drift resolved by `restore`.

## Template-maintenance inventory

`.agentic-template/maintenance-artifacts.json` declares paths that exist only to develop and release
the template source: source fixture suites, the Copier smoke workflow, the source-CI allowlist, and
historical source specs and plans. Each entry records the path, its expected source hash or tree hash,
and whether it is a regular file or a directory tree. Entries may not overlap any other ownership
class.

- Copier excludes the declared inventory. The current `copier.yml` exclude list is replaced by it.
- GitHub snapshot install removes only entries whose complete bytes match the declared shape.
- A modified, missing-with-children, unsafe, or partially matching entry blocks cleanup, reports the
  exact path, and names `--leave-maintenance-artifacts`.
- A skipped cleanup records the retained paths and transfers them to adopter ownership.
- `add`, `restore`, and `reconcile` never use the inventory to delete adopter files.

## Diagnostics and failure semantics

```text
BOOTSTRAP_INPUT_*           BOOTSTRAP_TRANSACTION_*
BOOTSTRAP_PROFILE_*         BOOTSTRAP_RECOVERY_*
BOOTSTRAP_CAPABILITY_*      BOOTSTRAP_ACTIVATION_*
BOOTSTRAP_TARGET_*          BOOTSTRAP_LICENSE_*
BOOTSTRAP_TEMPLATE_SOURCE_* BOOTSTRAP_MANIFEST_*
BOOTSTRAP_DRIFT_*           BOOTSTRAP_RENDER_*
BOOTSTRAP_LOCK_*            BOOTSTRAP_INTERNAL_*
```

Every user-correctable diagnostic includes the affected input, capability, or repository-relative path
and one next action. **Every next action must name a command or step that exists and is reachable for
the target's generation path**; a source-fixture check enumerates the diagnostic table and asserts
this, so no diagnostic can recommend an unavailable operation. Diagnostics never include secret values.
Independent preflight errors are reported together in stable sorted order; mutation and recovery
failures stop at the first point where continuing could destroy evidence.

## Implementation batches

One public release, one release gate. Six internal review batches so no single change contains the
whole system. A batch is a review boundary, not a version.

### Inertness contract

Intermediate batches may merge to the default branch because they are inert by construction:

- `scripts/bootstrap-project.py` is not created until the final activation batch, so no CLI entry point
  exists;
- `scripts/bootstrap/` modules are importable but referenced by nothing in `validate-template.py`,
  `check-project-readiness.py`, `validate-repository.py`, or any workflow until activation;
- no new readiness requirement is enforced until activation, so no batch can make a conforming project
  unready;
- `.agentic-template/` data files land as inert data, validated by their own source fixtures only; and
- the template's own CI gains only source-fixture invocations, which is the mechanism the repository
  already uses.

Batch fixtures run as source-only tests throughout, so each batch carries its own evidence without
changing generated-project behavior.

| Batch | Contents | Evidence before merge |
| --- | --- | --- |
| 1 | Schemas: bundle, addition, manifest with primary/derived split, capability, profile. The complete versioned `RenderInput` schema. Determinism primitives: canonical JSON with strict decoding, path grammar, LF normalization, tree and entry hashing. `ReadinessResult` contract. Ownership declarations | Unit coverage for every primitive and boundary case; schema round-trips; path-grammar and JSON-strictness rejection fixtures; ownership collision detection |
| 2 | Pure compiler: resolver, renderer, typed slots, planner. `render(RenderInput) -> RenderResult`. No filesystem mutation | Byte-identical repeated renders; renderer purity under no ambient access; field-perturbation tests over every `RenderInput` field; profile expansion and closure; cycle, collision, type, and slot detection; plan ordering |
| 3 | Transaction engine: lock, journal phases, write-ahead and fsync ordering, directory-anchored operations, backups, rollback, `recover`, `status`, same-contract `restore`. Gating comparison over `ReadinessResult` multisets | Injected failure at every phase; interrupted-journal blocking; concurrent-mutation and concurrent-recovery refusal; `--state-dir` bypass attempt; TOCTOU symlink substitution; drift detection and repair; worktree independence |
| 4 | Generation-path integration: `init`, `plan`, `apply`, the ordered classification, seed-once installation, marker derivation, maintenance cleanup, Copier exclude configuration, core-rendered CI, validation-boundary changes | Both paths install a `portable` project; the full classification table including A2, B6 per path, B7, and B9; scaffold and fully supplied bundles; reserved-marker rejection; licensing-bytes fingerprint fixture |
| 5a | Capability catalog, the four capabilities, all five profiles, slot contributions, compiled capability CI, secret preflights, compatibility fixture | Full profile matrix; `actionlint`; source-CI conformance; preflight structural-policy and canary tests; activation skips |
| 5b | Durable documentation rendering | Per-profile document content; documentation drift and repair |
| 5c | `add` and `plan-add` | Additive lifecycle including dependency resolution, satisfied repeat, conflicting settings, removal refusal, render-identity advance, template-source precondition |
| 5d | `reconcile`, `plan-reconcile`, the plan digest, and the migration fixture | Copier update then reconcile; digest binding and rejection; drift-overwrite path; previous-release migration end to end |
| 6 | Activation: create `scripts/bootstrap-project.py`, wire the boundaries, enforce new readiness requirements, publish documentation | The complete release gate below |

### Pre-runtime gates

These are prerequisites, not final checks:

- `docs/prd.md`, `CONTEXT.md`, and ADR 0001 are updated **before** batch 6 changes any runtime
  behavior. No batch that alters the generated-project contract merges ahead of them.
- The licensing and provenance audit completes **before** the batch that writes licence files, which is
  batch 4. Batch 4 does not merge until the audit's layout is fixed.

### Release gate

- Both generation paths pass the full profile matrix.
- Copier update coverage proves seed-once preservation and derived reconciliation.
- The previous-release migration fixture passes.
- Drift, recovery, lock, TOCTOU, and worktree suites pass.
- `actionlint` passes on the source and every generated workflow fixture.
- Source-CI conformance passes with no stale allowlist entry.
- Preflight structural-policy and canary tests pass.
- The diagnostic reachability check passes.
- The licensing and provenance audit is complete and reflected in the installed layout.
- The PRD, `CONTEXT.md`, and ADR 0001 reflect the approved boundary, including the breaking hook-path
  change and its migration instructions.
- Repository formatting, linting, tests, builds, and template-source fixtures pass.
- Verification-before-completion and substantive code review find no unresolved required issue.

## Verification strategy

### Unit coverage

- Canonical JSON: strict decoding, duplicate-key rejection, exact type checks including boolean versus
  integer, float and NaN rejection, integer range.
- Path grammar: absolute, `.`, `..`, backslash, repeated separator, trailing separator, empty
  component, NUL, non-UTF-8, and case-collision rejection.
- LF normalization: CRLF, lone CR, mixed endings, absent final newline, multiple trailing newlines,
  invalid UTF-8 in a declared text artifact, and exact hashing of binary artifacts.
- Tree and entry hashing, including a path containing a newline and a control character.
- Domain-tag separation across all five tagged constructions.
- Absent versus empty file; empty directory outside the model; symlink rejection; execute-bit-only
  mode comparison.
- `RenderInput` field perturbation: every field changes `render_identity`; an unselected capability's
  definition does not.
- Renderer purity: rendering succeeds with no filesystem, environment, clock, or network access.
- `ReadinessResult` identity and multiset comparison, including a repeated finding and a worsened
  count.
- Manifest primary/derived separation, derived recomputation mismatch, and checksum over the payload
  excluding the checksum.
- Every branch of the ordered classification.
- Journal phase transitions, lock acquisition and release, plan-digest computation and rejection.

### Tiered fixture matrix

During development each batch runs the fixtures that exist at that point. The tiers describe the
released steady state.

**Pull-request tier**, a few minutes: both generation paths across `portable` and `integrated`;
`retain-apache-2.0` and `provided-project-license`; one all-`scaffold` and one fully supplied bundle;
the drift and restore cycle; one injected interruption and recovery; `actionlint`.

**Pre-release tier**, at the release gate: both paths across all five profiles; custom empty, single,
dependent, and multi-capability sets; all three licensing modes; every required setting variation; and
unavailable and available activation structures without real secrets.

Runtime budgets are recorded when fixtures land; a tier exceeding its budget is split rather than
silently slowed.

### Lifecycle coverage

Identity and classification:

- Every row of the identity-transition table: assert exactly which identities each operation changes,
  and that `restore` changes none.
- `add` advances `render_identity`, leaves `template_source_fingerprint` untouched, and refuses when
  the current template source differs, naming `reconcile`.
- After an `add`, re-running the original bundle reaches B9 rather than misclassifying, because
  `render_identity` is recomputed from persisted state.
- `apply` after a Copier update with identical inputs and healthy managed state reaches B6, not B9.
- B6 on a GitHub snapshot names both reachable actions and does not imply Copier lineage.
- B7 is reachable by perturbing a recorded derived field, and exits 2 with manifest guidance.
- A2: a populated manifest-free target is refused and pointed at the migration contract.
- Changing only the supplied licence bytes produces `BOOTSTRAP_INPUT_CONTENT_CHANGED`.

Gating and scaffold:

- An all-`scaffold` install is retained, gate-passes, and exits 1 naming exactly the scaffolded slots.
- An all-`scaffold` **reapply** also exits 1, runs the readiness boundary, and runs the hook once.
- The initial-install exemption is exact: an install producing a placeholder finding for a slot that
  was not declared `scaffold`, or any extra blocking finding, gate-fails and rolls back.
- Planned-artifact verification precedes exemptions: corrupt one planned artifact post-install and
  prove the gate fails despite a valid scaffold exemption.
- `add`, `restore`, and `reconcile` succeed on a project whose PRD is still a placeholder.
- A mutation that newly breaks readiness gate-fails even when an unrelated placeholder finding already
  existed.
- A mutation that increases an existing finding's count gate-fails, which a set comparison would miss.
- A `file` input containing a reserved marker is rejected.
- A hook that is a non-UTF-8 binary is accepted, and its sentinel is detected at byte level.

Drift, restore, reconcile:

- Modify one managed artifact; `apply` and `add` refuse, `status` and every plan command report it,
  `recover` is unaffected, and `restore` resolves it.
- `restore --path` restores a subset, leaves other managed paths untouched, and changes no global field.
- `restore` refuses when template inputs changed and names `reconcile`.
- Drift plus a changed template is resolvable only through `plan-reconcile --overwrite-drift --out`
  followed by `reconcile --overwrite-drift --plan`.
- `reconcile --overwrite-drift` without `--plan` is a usage error; a tampered digest is rejected; a
  plan whose recomputation no longer matches is rejected.
- Change an unselected capability and prove no render drift.
- An incompatible capability fixture or unknown manifest schema produces zero writes.

Transaction, lock, recovery:

- Inject failure before the journal, in each phase, during gating validation, and during rollback.
- Gating failure rolls back before cleanup and before the hook runs.
- A `COMMITTED` journal is completed by `recover`, never rolled back.
- Two concurrent mutations: the second is refused by the lock.
- A mutation and a `recover` concurrently: the second is refused by the lock.
- Two invocations with different `--state-dir` values: the second is still refused, because the lock is
  in-tree.
- An abandoned lock from a killed process is detected via `flock` and reported, not treated as fatal
  forever.
- `recover` refuses a target whose identity does not match the journal.
- Substitute a symlink at a planned path between preflight and install; prove the operation aborts or
  rolls back and never follows it.
- Recovery evidence survives `git clean -fdx`.
- A linked worktree's journal is independent of the primary worktree's; a submodule uses its own
  administrative path; a bare repository is refused; a non-git directory is refused without
  `--state-dir`; a `--state-dir` that is a symlink, inside the target, or group-writable is refused.
- `status` and the plan commands report a pending journal that lives in a `--state-dir`.

Hook and status:

- A failing hook leaves the installation in place and exits 1.
- `status` never executes the hook, and reports "hook not evaluated" rather than any past outcome.
- The hook runs exactly once per mutating invocation.

### Workflow and security coverage

- `actionlint` on the source and every generated workflow fixture.
- The managed caller passes no secrets and has read-only permissions.
- The seeded workflow invokes the canonical boundary and has no privileged environment.
- Release depends on the full project-validation call and selected checks.
- Unavailable Gemini and Cachix secrets produce successful skip guidance naming the fork and Dependabot
  causes.
- Privileged jobs cannot start when preflight is false.
- Preflight structural policy: no checkout, no `uses:`, no repository path reference, no untrusted
  expression, exactly one secret reference, no tracing.
- Preflight canary: a sentinel secret value appears in no log, output, or artifact.
- Source CI conforms to the normalized `integrated` render; a stale allowlist entry fails; an
  uncovered step-level difference fails; the entry count is reported.
- Every diagnostic's next action exists for the relevant generation path.
- Persisted checkout credentials and credential-looking values are absent.

## Compatibility and the PRD

### Requirement delta

| Requirement | Change |
| --- | --- |
| REQ-001 detect incomplete setup | Retained and extended: readiness names unreplaced slots specifically, derived from declared file markers |
| REQ-002 one validation command | Retained; the canonical hook path becomes `scripts/validate-project`, a **breaking change** requiring migration notes |
| REQ-003 gate releases on project validation | Retained; the gate becomes a compiled contribution present only when `semantic-release` is selected |
| REQ-004 verify generated behavior from source | Extended to the tiered matrix and both paths across profiles |
| REQ-005 preserve generation-path ownership | Extended with the ownership classes, the drift contract, and the populated manifest-free contract |
| REQ-006 portable, least-privileged template validation | Retained; the generated boundary stays standard-library only, while source-only fixtures may use dev-shell tools |
| New: deterministic bootstrap | The compiler, its input contract, and byte-for-byte output guarantees |
| New: capability selection | Profiles, catalog, and the absence of unselected artifacts |
| New: identity transitions | One normative table governing what each operation may change |
| New: managed-artifact ownership and drift | Manifest, hashes, `restore`, and the refusal to merge |
| New: installation is distinct from readiness | A completed installation whose hook fails exits 1 and is reported unready |
| New: recoverable planned-path transactionality | Lock, journal phases, and rollback, without atomic multi-file visibility |
| New: activation is not readiness | Two-state preflight in a fixed trusted job |

The PRD's compatibility attribute requires that a change making a conforming project unready ship as a
breaking template-contract change with migration notes. V1 triggers that clause through the hook-path
rename and satisfies it with the documented migration.

### CONTEXT.md changes required

- **Project bootstrap** gains the distinction between a completed installation and a locally ready
  project.
- **Project readiness** keeps its meaning, including successful hook completion, and gains that
  unreplaced slots are derived from declared file markers.
- **Bootstrap-managed artifact** gains `restore` as the supported drift remedy.
- **Project-validation hook** changes path to `scripts/validate-project`.
- New terms: **render identity**, **identity transition**, **managed drift**, **populated
  manifest-free project**, **maintenance cleanup opt-out**, and **point-in-time hook evidence**.
- The example dialogue gains an exchange distinguishing "bootstrap installed the files" from "the
  repository is locally ready".

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| An operation changes identity it should not | One normative identity-transition table, asserted row by row |
| A repair silently upgrades the template | `restore` may write only bytes the manifest certifies and advances nothing |
| A partial repair certifies a state that never existed | `restore` cannot change any global field |
| An `apply` after a template update reports success | Classification compares template-source identity before B9 |
| A diagnostic recommends an unavailable operation | Generation-path-aware next actions plus a reachability check over the diagnostic table |
| A fingerprint stops covering an input | `render_identity` is taken over the canonical `RenderInput`, with field-perturbation tests |
| Changing legal text is invisible | A dedicated licensing entry in `content_fingerprint` |
| The manifest cannot describe itself | Excluded from its own inventory; integrity by recomputation and checksum |
| A corrupt manifest is "repaired" into a wrong state | Derived mismatch is exit 2, never silent repair, and `restore` is never offered |
| A mutation on an incomplete project rolls itself back | Gating is scoped to findings the operation introduced |
| A defective install hides behind the scaffold exemption | The initial-install exemption is exact, and planned-artifact verification precedes it |
| A repeated or worsened finding goes undetected | Multiset comparison over `(code, path, subject, rule)` |
| Adopter content impersonates a placeholder | Reserved markers are rejected in `file` inputs |
| A non-text hook breaks marker detection | Byte-level sentinel search |
| A live writer races recovery | A per-target in-tree lock, held by mutations and `recover` alike |
| `--state-dir` bypasses exclusion | The lock is in-tree, so its path cannot vary |
| An interrupted mutation is undecidable | Durable `PREPARING`/`APPLYING`/`COMMITTED` phases with write-ahead and fsync ordering |
| A symlink is substituted between check and use | Directory-anchored, no-follow operations with re-verified device and inode |
| Recovery targets the wrong checkout | Worktree-specific administrative path and recorded target identity |
| Recovery evidence is destroyed | State outside the tree, no reliance on gitignore, git as fallback for tracked files |
| Atomicity is overclaimed | The guarantee is stated as recoverable planned-path transactionality |
| A correct installation is discarded | Gate only on template-owned deterministic validation |
| An unready project is reported ready | Hook failure exits 1; equivalent reapply still runs the boundary |
| `status` claims knowledge it lacks | It never executes the hook and reports "not evaluated" |
| False drift from line endings or umask | Specified LF normalization and execute-bit-only comparison |
| An ownership class traps ordinary configuration | `CONTRIBUTING.md` and `.gitattributes` are adopter-owned |
| Bootstrap becomes an authoring gate | `scaffold` compiles a real project before prose exists |
| A scaffolded slot's state goes stale | Completion derived from markers, never from the manifest |
| A destructive overwrite runs unreviewed | Bound to a plan digest that `reconcile` revalidates |
| Compiled CI drifts from the template's own CI | Graph and step normalization with an attributed allowlist |
| Allowlist entries accumulate | Owner, reason, and review-by metadata, plus a reported entry count; the stale-entry check is not claimed to prevent growth |
| A YAML checker overclaims | Bounded standard-library checks in the generated project; a real parser only in source fixtures |
| A secret leaks through the preflight | Fixed trusted job, structural policy test, and synthetic canary |
| Preflight guidance misdirects | Two honest states with event-specific likely causes |
| Licence obligations are lost | Conservative preservation plus an audit gating every mode before licence-writing |
| Existing adopters hit an undocumented break | One documented breaking change with an ordered migration and a fixture |
| A renamed project is mistaken for bootstrapped | A2 refuses it explicitly and the migration states what the rename does not do |
| An intermediate merge changes behavior | The inertness contract: no entry point, no wiring, no new readiness requirement until activation |
| An underspecified mutation ships | `adopt` deferred rather than half-specified |
| One change contains the whole system | Six internal review batches |

## Proposed future changes

### Bootstrap experience

- One-command interactive initialize-and-apply over the same engine.
- Inline prose fields with explicit escaping.
- Guided PRD authoring without treating generated prose as authoritative.
- Stack presets and recommendations without an implicit engine default.
- Opt-in reset or regeneration of seed-once files after an ownership-aware design.
- `apply --strict`, gating the transaction on the adopter hook.

### Capability and profile lifecycle

- A broader first-party catalog; third-party registries with signing and trust policy.
- Live profiles or profile-plus-override policies.
- Capability removal, replacement, rebasing, and reconfiguration.
- Versioned capability IDs and explicit migrations.
- Managed document regions or adopter fragments.
- A signed or sandboxed plugin model if declarative slots prove insufficient.

### Adoption and portability

- An adoption lifecycle for populated repositories, with `plan-adopt`, collision handling, and
  ownership-transfer rules.
- Adoption of GitHub snapshots into Copier lineage.
- Declarative validation-command lists and generated hook adapters.
- Interpreter adapters and native Windows support.
- A portable structured GitHub workflow parser.
- Structured JSON diagnostics and GitHub Actions annotations.
- Hook sandboxing where a selected toolchain supports it.

### GitHub and external activation

- A read-only GitHub configuration doctor covering Actions availability, default branch, authoritative
  secret configuration, workflow activation, rulesets, and required checks.
- Authenticated repository-identity and rename or transfer diagnostics.
- Authorized secret, ruleset, or branch-protection writes in a separate operator tool.

### Distribution and maintenance

- Maintenance automation opening reviewable update PRs with reconciliation previews.
- Signed template-release provenance.
- SPDX, SBOM, and richer licence automation.
- Copier-native conditional rendering if one generation path ever suffices.
- Opt-in trusted Copier tasks where users knowingly accept task execution.

Recommended order: deterministic bootstrap, then the GitHub configuration doctor, then maintenance
automation.

## Rejected alternatives

- Ordinal profiles such as minimal/default/full.
- An implicit mutation-engine profile default.
- Re-expanding a stored snapshot profile during update or reconciliation.
- Accepting, persisting, logging, or inferring secret values.
- Claiming to know whether a secret is configured from an empty value.
- Reading a secret in a job that also checks out the repository or runs repository scripts.
- Bootstrap performing unapproved external configuration writes.
- Persisting live activation status, or repository owner and name.
- Silently overwriting or merging managed drift.
- Leaving drift with no supported remedy.
- Letting a drift repair advance template or render identity.
- Letting a partial repair update repository-wide identity.
- Declaring one operation the sole advancer of render identity while another changes render inputs.
- Destructive reconciliation not bound to its preview.
- An interactive-only confirmation for a destructive operation.
- Gating the transaction on the adopter hook.
- Reporting success when the adopter hook failed.
- Treating an equivalent reapply as an unconditional exit-0 no-op.
- Recording or replaying hook results, or having `status` execute the hook.
- Requiring complete product prose before a project can be compiled.
- Recording slot completion in the manifest instead of deriving it.
- Requiring the adopter hook to be decodable UTF-8.
- Accepting adopter content that contains a reserved placeholder marker.
- Accepting two canonical hook paths.
- Shipping an adoption command without a preview or collision rules.
- Implying that a manual rename bootstraps a populated project.
- Listing the manifest among the artifacts whose hashes it records.
- Trusting derived manifest fields without recomputation, or silently repairing them.
- A second manifest version field duplicating the template-source fingerprint.
- Managing `.gitattributes` or `CONTRIBUTING.md` as drift-fatal artifacts.
- Using one journal as both live lock and durable record.
- Storing transaction state in the shared git common directory or an ignored in-tree directory.
- Deriving the lock location from `--state-dir`.
- Claiming atomic multi-file visibility.
- Operating on planned paths by name after a one-time preflight check.
- Comparing readiness findings as `(code, path)` sets.
- Discarding step bodies from source-CI conformance.
- Claiming that stale-entry expiry prevents allowlist accumulation.
- Implying a standard-library checker can generally parse Actions YAML.
- Treating capability removal as reconciliation.
- A custom version-aware updater competing with Copier.
- Parallel Copier and Python rendering implementations.
- Mandatory trusted Copier task execution.
- Requiring `--target` on `init`.
- Legal boilerplate authored by bootstrap, or a claim that a licence is legally sufficient.
- Deferring the licensing audit for any distribution mode, or treating it as a final release check.
- Independently releasable slices with per-slice manifest compatibility levels.

## Required follow-up documents

- `docs/prd.md`, per the requirement-delta table, including the breaking hook-path change. **Pre-runtime
  gate.**
- `CONTEXT.md`, per the domain-language changes above. **Pre-runtime gate.**
- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs. **Pre-runtime gate.**
- An ADR for the capability compiler, identity model, and ownership boundary if the implementation plan
  confirms the boundary is architectural.
- The licensing and provenance audit record and any resulting ADR. **Prerequisite to batch 4.**
- `docs/project-readiness.md`, reflecting the canonical hook path, derived slot completion, `status`,
  `restore`, and the populated manifest-free contract.
- Release notes containing the ordered migration, the pinned pre-bootstrap tag, and the collision and
  rollback guidance.
- Generated adopter documentation described above.
- Source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open for v1.

The licensing and provenance audit is a blocking gate for every licensing mode and a prerequisite to
batch 4. If it changes the proposed `LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design must
be amended and reconfirmed before licence-writing implementation proceeds.

## References

- `docs/prd.md`
- `CONTEXT.md`
- `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md`
- `design.discovery-draft.md` and `design.revision-2.md` in this directory
- `design.revision-3.reconstructed.md` — a reconstruction of revision 3, which was overwritten before
  being archived; faithful in substance but not verifiable byte-for-byte against the original
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub: Dependabot on Actions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions)
- [Git: `git rev-parse`](https://git-scm.com/docs/git-rev-parse)
- [Git: `git clean`](https://git-scm.com/docs/git-clean)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/)
- [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
