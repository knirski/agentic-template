# Deterministic Project Bootstrap with Capability Profiles

**Status:** Revision 12, assembled for owner approval
**Date:** 2026-08-05
**Planning mode:** Spec-backed Plan
**Supersedes:** earlier discovery and revision drafts, consolidated into this document and removed
from the active spec directory.

## Summary

Add a deterministic bootstrap compiler that turns either supported generated-repository shape into a
mechanically complete project from a reviewable input bundle. The compiler expands an explicitly
selected snapshot profile into an exact capability set, renders declared outputs from pure functions,
installs one complete typed plan through a recoverable transaction, and reports installation and
readiness separately through the repository's canonical validation boundary. A fully supplied bundle
whose adopter hook succeeds is locally ready; a declared scaffold or failed hook is installed but not
locally ready.

The first capability catalog covers the integrations already present in the template: semantic-release;
Nix; Cachix publishing, which depends on Nix; and Qodo PR Agent with a Gemini backend.

V1 is one public release, developed on an integration branch and activated by a single merge. No
generated projects exist on the current template, so activation is greenfield: there is one canonical
extensionless hook and one manifest-bearing lifecycle, with no legacy hook, compatibility release,
adoption command, or migration path.

Revision 6 keeps Revision 5's structural simplification and completes it. All template-owned Python
commands use one functional-core/imperative-shell architecture: immutable sum types represent only
legal states; total pure transitions return typed success or error values; the shell alone performs
filesystem, Git, process, environment, and terminal effects. Initial adopter bytes, prospective target
state, source baselines, operation-specific render oracles, and exact recovery evidence are now explicit
values rather than ambient inputs or prose-only obligations.

This design refines `docs/prd.md`. Requirements REQ-007 through REQ-015 now authorize the complete
bootstrap product boundary; the settled domain terms are updated with this revision. ADR 0001 and the
functional-core/ownership ADR remain pre-runtime gates.

## Settled decisions

Owner decisions, recorded so review does not reopen them.

- `scaffold` remains in v1.
- Slot completion is derived from current file markers. There is no `finalize` lifecycle.
- The manifest's content record is bootstrap-time input identity, not current tree state.
- One canonical extensionless adopter hook at `scripts/validate-project`. No legacy path, no `adopt`,
  no `plan-adopt`.
- Capability changes are additive only in v1.
- GitHub generation produces one-time snapshots. Copier alone owns template version selection, update
  lineage, and merge mechanics.
- Toolchain neutrality outranks native Windows compatibility.
- V1 is one public release; internal review batches are not versions.
- `restore` is a same-contract repair and never advances project identity.
- An installation may survive adopter-hook failure, but the command then exits nonzero and the project
  is not locally ready.
- All template-owned Python scripts share the functional-core/imperative-shell boundary defined here.
- V1 has no legacy generated-project population. The `.py` hook path, compatibility releases,
  migration fixtures, and adoption lifecycle are absent rather than supported conditionally.

## Scope reduction

**A git working tree is required.** This removes `--state-dir`, non-git targets, and an in-tree lock.
State location is a pure function of the verified target, eliminating alternate lock domains and hidden
recovery state. GitHub generation already creates a repository. Copier onboarding must initialize Git
before bootstrap when the destination is not already a working tree.

This is an adopted v1 boundary, not a temporary compatibility measure. Non-git support remains a
possible future capability only if it supplies an equally unique state namespace.

## Revision ledger

### Corrections to earlier ledgers

Revision 4's ledger contained factual errors. They are struck here rather than carried forward.

| Earlier claim | Status | Evidence |
| --- | --- | --- |
| "Revision 1 installed the hook at `scripts/validate-project.py`" | **False; struck** | The earlier discovery record already specified the extensionless path. The current source scaffold predates bootstrap, but no generated project compatibility contract exists |
| "Revision 3's scaffold exemption made `add`, `restore`, and `reconcile` necessarily gate-fail" | **False; struck** | `design.revision-3.reconstructed.md:1120` contains the pre-existing-finding clause covering exactly those operations. The multiset formulation is an improvement, but the stated defect did not exist |
| "Revision 3 described itself as having seventeen corrections" | **Unverifiable; struck** | A reconstruction cannot establish historical wording or counts |
| "Revision 2's apply matrix had no absent-manifest branch at all" | **Too broad; softened** | Revision 2 covered initial install under generation-path behavior. The real defect was the absence of one exhaustive classification |
| Revision 2's retained-path and `status`-exit defects | **Omitted from revision 4; restored below** | Both were recorded in revision 3 and dropped |

### Deliberate reversals of approved revision 1 decisions

| Revision 1 decision | Current decision | Why |
| --- | --- | --- |
| A bundle must supply complete content for every slot | Every slot is an adopter file or an explicit `scaffold` placeholder | Requiring a finished PRD before a project could compile made bootstrap an authoring gate |
| Successful `apply` makes the full canonical validator pass | `apply` installs, then reports; a failing hook means nonzero exit and "not locally ready", never rollback | The hook can fail because a toolchain is absent, which says nothing about whether bootstrap compiled correctly |
| Reconciliation writes only paths whose bytes match old hashes | `reconcile --overwrite-drift` may overwrite drift, bound to a preview digest | Without an escape, drift plus a changed template is unresolvable |
| The lifecycle is initial bootstrap plus additive capability changes | Adds `restore`, a same-contract drift repair | Revision 1 blocked on drift and provided no remedy |
| Partial bundles and a finalize phase are future work | `scaffold` is in v1; no finalize phase | Slot completion is derived from files, so there is no state to transition |
| `CONTRIBUTING.md` is bootstrap-managed output | Seed-once adopter output | A managed drift-fatal file that adopters are expected to edit blocks the repository |
| One `initial_input_fingerprint` | Normalized answers stored as values; **no input fingerprint at all** | A fingerprint is a lossy compression of a comparison; storing the values yields field-level diagnostics for free |
| `.agentic-template.json` | `.agentic-template/project.json` | One namespace; one character of separation was too little |
| `compiler_contract_version` in the manifest | Removed | `template_source_fingerprint` already covers engine and catalog identity |
| Persisted effective dependency closure | Closure is derived from frozen profile selection plus additions | The primary intent is sufficient, while incompatibility must remain a classification outcome rather than manifest corruption |
| Persisted selected-render fingerprint | A `ManagedInventory` is the operation-specific render oracle | Path-level records localize disagreements and do not require re-deriving an old fingerprint from changed source |
| Template-source fingerprint included the maintenance inventory | Cleanup has its own ephemeral, bounded `CleanupContract` | Snapshot cleanup data is consumed before the generated lifecycle begins and is not retained by Copier |
| `recover` always rolls back and never finishes forward | `PLANNED` cleans preparation, `MUTATING` rolls back, `RESTORED` finishes rollback cleanup, and `SEALED` finishes installed-state cleanup | Recovery follows the durable phase and never chooses between two outcomes for one phase |

Revision 4 additionally granted GitHub snapshots a local `reconcile` lifecycle. That was an unlisted
reversal of revision 1's Copier-only update boundary and is **withdrawn** in this revision.

### Defect corrections to revision 2

| Defect | Correction |
| --- | --- |
| `restore` recompiled from current inputs and advanced fingerprints, bypassing reconciliation's preconditions | `restore` writes only bytes the recorded inventory already certifies and records nothing |
| `plan-reconcile` could not preview `--overwrite-drift` | Both commands accept it; the destructive form requires a plan digest |
| US-8 permitted and forbade drift overwrite four lines apart | Resolved in favour of the previewed override, with per-operation drift policy |
| A mutating command exited 0 when the adopter hook failed | Exit 0 means the complete canonical command would succeed |
| `scaffold` slot completion had no defined derivation | Derived from declared file markers; the manifest records input identity only |
| Markers were named for three slots and assumed for five, and detection assumed decodable text while the hook is an arbitrary executable | Five markers declared; the hook sentinel is detected at byte level |
| A legacy `.py` hook path and a half-specified `adopt` | One canonical path; no legacy or adoption lifecycle exists in v1 |
| Slices claimed to be independently releasable | One public release; integration branch with one activation merge |
| The apply matrix lacked one exhaustive classification and never compared template-source identity | A total classifier over independently computed facts |
| `selected_render_fingerprint` covered a hand-maintained subset omitting `default_branch` | The concept is deleted; the recorded inventory is the render oracle |
| Supplied licence bytes entered no fingerprint | The licensing content digest is primary manifest state |
| The manifest was listed among the artifacts whose hashes it records | The manifest is excluded from its own inventory |
| `.gitattributes` was managed and therefore drift-fatal | Not installed; comparison normalizes declared text artifacts |
| Transaction state used the shared git common directory | Per-worktree administrative path |
| The non-git state fallback relied on gitignore, which `git clean -x` defeats | A git working tree is required |
| The journal served as both live lock and durable record | Separate never-unlinked lock and atomically replaced journal |
| The licensing audit gated only two modes | It gates every mode and precedes licence-writing implementation |
| Determinism primitives left normalization, path grammar, and JSON strictness unspecified | All specified, with boundary fixtures |
| The preflight claimed to distinguish "not configured" from "unavailable" | Two states with event-specific likely causes, in a fixed trusted job |
| **A skipped maintenance cleanup recorded no retained paths and defined no follow-up** | Retained paths recorded; ownership transfers to the adopter |
| **`status` always exited 0** | Inspection-family exit semantics defined explicitly |

### Defect corrections to revision 3

| Defect | Correction |
| --- | --- |
| `add` changes the effective capability set while the text made `reconcile` the sole advancer of render identity | Render identity is deleted; one operation-semantics table governs what each operation may change |
| Findings were compared as `(code, path)` sets, collapsing repeats and hiding worsened counts | `(code, path, subject, rule)` identity, compared as a multiset |
| The transaction step list placed the gating-failure branch after the hook step | Gating occurs inside the mutating phase, before any cleanup or hook execution |
| "Every command accepts `--target`" included `init` | Scoped to commands that inspect or mutate a project |
| Step bodies were dropped from source-CI conformance, losing revision 2's step accountability | Step identity restored and extended |
| Self-expiry was said to prevent allowlist accumulation | It removes stale entries only; entries carry owner, reason, and review-by metadata |
| A test required `status` to report a previous hook failure | `status` never executes the hook and reports "not evaluated" |

Revision 4's ledger described revision 3 as having "no normalizer or allowlist" for source-CI
conformance. That was false and is not repeated: revision 2 normalized job IDs, `needs`, and
permissions, and allowed declared source-only steps.

### Defect corrections to revision 4

| Defect | Correction |
| --- | --- |
| Recomputing every derived field before trusting the manifest made `TemplateChanged` and render-contract violation unreachable, and shadowed pending-journal detection | The manifest has no derived section; validity is parse, schema, and checksum only; journal detection precedes manifest trust |
| `RenderInput` carried tree hashes and identities, so `render(RenderInput)` could not produce bytes without ambient reads | `render(RenderInput, BlobMap)` over decoded definitions and fragment bodies |
| Primary state could not reconstruct `RenderInput`: no per-slot digests, no licensing digest, and `retained_paths` absent from the render input | All three are primary state, and `retained_paths` enters `RenderInput` |
| `source-ci-allowlist.json` was fingerprinted and validated by `validate-template.py` while also being excluded by Copier and deleted by snapshot install | Removed from the fingerprint and from generated-project validation; source-only fixture input |
| The journal entered COMMITTED before gating, so a crash preserved ungated output and an interrupted rollback completed forward | Durable `PLANNED`/`MUTATING`/`RESTORED`/`SEALED` phases; gating inside `MUTATING`; `SEALED` only after gating passes |
| `O_CREAT \| O_EXCL` plus `flock` cannot detect an abandoned lock, and unlink-and-recreate splits lock domains | A never-unlinked lock inode opened without `O_EXCL`, then `flock(LOCK_EX \| LOCK_NB)` |
| Journal phase updates had no atomicity requirement, permitting torn JSON | Temp-write, fsync, rename, fsync parent |
| Differing `--state-dir` values could conceal a pending journal | `--state-dir` removed; state location is a pure function of the target |
| Staging was weakened to one directory "on the target's filesystem", which a repository spanning mounts defeats | Staging is adjacent to each destination parent |
| Target identity was no longer normatively defined | Defined as the verified absolute worktree root plus its device and inode |
| `O_NOFOLLOW` on the parent protects only the final component, and `fstat` does not prove continued attachment | Root-anchored per-component walk, re-resolution before mutation, and a **narrowed threat model** |
| A compatible v1 update could add a required seed-once path that no lifecycle could satisfy | A template-evolution compatibility rule, enforced by a frozen readiness-rule baseline |
| The migration promised both "update to v1" and "pin the pre-bootstrap release" | The premise is removed: no generated projects exist before bootstrap v1, so there is no legacy population or compatibility release |
| Intermediate batches were called inert while batch 4 changed Copier configuration and validation boundaries | Integration branch with a single activation merge |
| "Six internal review batches" contradicted a table with nine boundaries | Nine boundaries, stated as nine |
| GitHub snapshots were offered `reconcile` despite having no update lifecycle | Withdrawn |
| Source-CI normalization omitted `env` values and most action inputs; the canary relied on GitHub logs, which mask registered secrets | Full canonical `env` and `with` comparison; local canary across all channels |
| Lone surrogate code points pass strict JSON typing but fail UTF-8 encoding | Surrogates rejected explicitly |
| `Finding.path` allowed `""`, violating the canonical path grammar | `Path \| Repository` sum |
| A tree-hash test used control characters in paths, which the grammar rejects | Entry encoding tested in isolation |
| `ReadinessResult` was "ordered" with no normative order | Sort key defined |
| One global exit-code rule contradicted `status` returning 0 for reported unreadiness | Exit semantics per command family |
| "The hook runs exactly once per mutating invocation" is false on preflight refusal, rollback, and recovery | Invocation rule stated exactly |
| The dev shell's unversioned `python3` does not establish the 3.14 floor | An explicit 3.14 validation lane |

### New in revision 5

| Addition | Purpose |
| --- | --- |
| Domain model with primary/derived/observed/effectful classification | One canonical value per concept |
| Total `classify : Intent -> Facts -> ApplyDecision` with a preimage witness per constructor | No constructor is shadowed by an earlier condition |
| `render(RenderInput, BlobMap)` | A purity contract that is actually satisfiable |
| Recorded inventory as the render oracle | Render-contract violations become reachable, at the point of use |
| Three-phase transaction with gating inside `MUTATING` | Committed cannot precede gated |
| Template-evolution compatibility rule | Compatible updates cannot create unsatisfiable obligations |
| Three-way input boundary: generated-lifecycle, source-only, cleanup-only | Resolves the allowlist contradiction by construction |
| Narrowed path-safety threat model | A guarantee the primitives deliver |

### Corrections in revision 6

| Revision 5 gap | Revision 6 correction |
| --- | --- |
| Initial seed and legal bytes were referenced only by digest, so the pure plan could not install them | `VerifiedBundle` carries an immutable content-addressed `AdopterBlobMap`; the complete `OperationPlan` includes seed, legal, manifest, cleanup, and managed operations |
| `ObservedTarget` exposed hashes but not the bytes readiness parses | `TargetSnapshot` contains immutable observed file bytes and metadata; `ExpectedTarget` is the pure overlay of a complete plan |
| A flat `Facts` product admitted impossible combinations and one decision type was overloaded across commands | Staged observation sums plus exhaustive family-specific `BundleIntent × BundleState` and `ProjectIntent × SystemState` transition algebras |
| Inventory comparison was not operation-specific | Restore validates its requested projection; add validates the complete old render before compiling the expanded render; reconcile validates observed old files and treats new-source output as the candidate |
| Normalized hashes and owner-execute modes could not prove exact rollback | Journal operations carry normalized preconditions separately from raw backup digests and exact pre-operation modes; rollback is an idempotent pure reducer |
| Directory creation, cleanup expansion, corrupt journals, and pre-journal orphans were outside the transaction model | Typed directory operations, transaction-scoped preparation, explicit invalid/recovery-blocked states, and safe orphan cleanup |
| Rule metadata could not detect a stricter readiness predicate under the same identifier | Schema-v1 adopter-facing blocking predicates are frozen as canonical rule definitions and exercised over a compatibility corpus |
| A snapshot source fingerprint could detect change but not name or recover paths | The manifest stores a source inventory and, for snapshots, the clean baseline commit used for targeted repair |
| Cleanup inventory alone authorized its deletion set | Runtime cleanup is the intersection of the ephemeral inventory and a finite generated ownership declaration; disagreement deletes nothing |
| Hook execution was said to be exactly once across a crash boundary | At most one attempt per uninterrupted command; recovery never invokes or replays the hook |
| Existing validators mixed IO, mutation, and policy | Every template-owned Python command now follows the same functional-core/imperative-shell contract and typed CLI result algebra |
| Legacy compatibility and migration occupied v1 without an installed population | All legacy paths, compatibility releases, migration fixtures, and migration documentation are removed |
| Initial settings were immutable but settings supplied by `add` had no persisted owner | `CapabilityAdditions` persists explicit added IDs and complete normalized settings for every newly effective capability while `InitialAnswers` remains immutable |
| Existing-project facts still admitted cross-generation combinations and gave no precedence to unsafe topology or target protection | Generation-specific nested sums, protected-target transitions, and per-constructor preimage witnesses make the project decision algebra total |
| Cleanup mismatch made the leave override unreachable | Scaffold recognition carries `CleanupObservation`; only explicit leave converts mismatch into finite retained ownership |
| Cleanup deletion authority was not fingerprint-bound | One `source-ownership.json` serialization declares retained lifecycle and snapshot-cleanup paths and is itself a fingerprinted lifecycle entry |
| Plan/mutation grouping contradicted drift previews and recovery/init exit mappings | Normative transitions distinguish each plan from its mutation; target mismatch, invalid state, output occupancy, and invalid input have one outcome each |
| Closed core signatures referenced undefined error/hook types and omitted ordinary OS failures | Operation-local aliases narrow one `CommandError`; hook/process/transaction/resource outcomes are closed sums with total mappings |
| The transaction reducer covered files but not directory rollback or sealed forward verification | Directory content identities, reverse dependency rollback, atomic tree moves, exact empty-directory restoration, and a sealed candidate verifier make both phase directions idempotent |
| Cleanup after a completed rollback had no durable state distinct from partial mutation | `RESTORED` durably records verified pre-state before any rollback evidence is removed, so interrupted cleanup never makes a `MUTATING` journal unrecoverable |
| Unlocked inspection could combine journal and target observations from different transaction moments | Every project observation is accepted only after two identical bounded passes; repeated change returns `ConcurrentTargetChange` without a partial state |
| Empty-target wording implied an installation branch with no trustworthy generation provenance | Only exact GitHub or Copier scaffold recognition permits initial installation; arbitrary empty and populated manifest-free targets share one explicit refusal state |
| Eager byte-carrying values had no resource bound | One bounded content-addressed `VerifiedBlobStore` owns bytes; exact file/path/operation/diagnostic limits fail before partial decisions |
| Mechanical findings were named as complete project readiness | `MechanicalReadinessResult` gates installation; `ProjectReadinessOutcome` additionally requires this invocation's hook success |
| The original source-tool recommendation was not reevaluated against the FP boundary | Strict `ty`, pytest, Hypothesis, Ruff, and PyYAML are pinned through uv; stdlib `argparse` is a contained shell adapter, and generated projects may declare uv-managed runtime dependencies |

### Corrections in revision 7

| Revision 6 decision | Revision 7 correction |
| --- | --- |
| `ty` was listed as a non-normative future option while Pyright was the type gate | `ty` is the sole normative type checker, managed through uv and configured for strict Python 3.14 checking |
| Source dependencies were described as Nix-flake-only | Python source dependencies are declared in `pyproject.toml`, locked in `uv.lock`, and run with `uv run`; Nix exposes uv and remains the reproducible host/tooling boundary |
| Generated-project Python was required to be standard-library-only | Generated projects may declare runtime dependencies in rendered uv metadata; bootstrap does not install packages or execute package setup code |
| Capabilities had no dependency contribution contract | A capability may declare non-secret runtime dependencies, supported Python range, and invocation metadata alongside its outputs and settings |

### Corrections in revision 8

| Dependency-locking ambiguity | The template source commits its root `uv.lock`; bootstrap renders generated `pyproject.toml` but does not generate a project `uv.lock`. When selected capabilities declare runtime dependencies, the generated project names `uv lock`/`uv sync` as the explicit adopter follow-up. Lock resolution remains outside the pure compiler because it depends on uv, package indexes, platform markers, and external availability |

### Corrections in revision 9

| Source uv metadata could leak into generated projects | The source root `pyproject.toml` and `uv.lock` are source-only cleanup targets: GitHub snapshot cleanup removes them after verification, and Copier excludes them. Bootstrap renders a bootstrap-managed `pyproject.toml` for every generated project; selected capabilities may add declared runtime dependencies, and bootstrap still does not create `uv.lock` |

### Corrections in revision 10

| Python support floor | Python 3.14 is the minimum and primary runtime for source and generated projects; uv and CI use 3.14 explicitly, with no 3.11 or 3.13 compatibility lane |

### Correction in revision 11

| Generated project metadata ownership | Every generated project receives bootstrap-managed `pyproject.toml` containing the Python 3.14 requirement; selected capabilities may add declared runtime dependencies, while bootstrap never creates `uv.lock` |

### Correction in revision 12

| Python support range | Python 3.14 is the minimum and primary validation lane; source and generated metadata use `requires-python = ">=3.14"`, so later Python 3.x releases remain supported unless a future compatibility decision narrows the range |

### Unchanged load-bearing decisions

Snapshot profiles and `InitialAnswers` freeze at creation; `CapabilityAdditions` records later IDs and
their settings while closure is derived separately; secrets are
never accepted or persisted; repository owner and name are never persisted; transactions cover only
planned paths and never claim to roll back hook-created artifacts; the renderer cannot execute
capability-supplied code; generated-project runtime dependencies are declared and managed through uv.

Approaches B (mirrored Copier and Python rendering) and C (trusted Copier task) were considered and
rejected in revision 1; see the consolidated discovery decisions above. Approach A, one shared declarative
compiler with a dependency-light functional core and uv-managed project dependencies, remains selected.

## Context and problem

The current template detects incomplete generated-project setup but does not perform it. A generated
repository inherits a fixed integration set and requires manual replacement of the README, PRD, and
validation hook. CI and the release graph assume Nix, Cachix, semantic-release, and Gemini review
whether or not an adopter wants them. This yields five problems: no reviewable transition from
scaffold to ready project; optional integrations coupled to the source tree; two generation paths
drifting into separate setup implementations; no strict file-ownership boundary; and durable
operational guidance lost to README customization.

## Goals

- Produce a verified bootstrap installation from explicit content/scaffold choices, and a locally ready
  repository when supplied content and the adopter hook satisfy readiness.
- Make rendering a pure function of explicit inputs, so identical inputs yield identical bytes.
- Require explicit intent-based profile selection and freeze its expansion at creation time.
- Support exact custom capability selection and additive post-bootstrap changes.
- Keep core validation independent of optional capabilities and external activation.
- Share one functional core, transition algebra, and renderer across both generation paths and every
  template-owned Python command.
- Give Copier and bootstrap non-overlapping update responsibilities.
- Preserve adopter-owned content, detect managed drift, and provide a supported remedy.
- Make every legal intent/state pair map to exactly one typed decision and reject invalid states before
  policy evaluation.
- Make an interrupted mutation exactly recoverable for every planned file and directory, or stop on a
  third state without overwriting evidence.
- Make missing external secrets safe and actionable.
- Produce durable adopter-facing operational documentation.
- Allow new declarative capabilities without changing the resolver, renderer, or transaction shell.

## Non-goals

- Inventing or judging product requirements, README content, security policy, or legal terms.
- Judging whether the adopter's validation hook is adequate, or rolling back a valid installation
  because it failed.
- Claiming atomic visibility across multiple files.
- Preserving timestamps, ownership, ACLs, extended attributes, or hard-link topology; planned files must
  be ordinary single-link files, and the transaction guarantee covers raw bytes and POSIX mode.
- Accepting, storing, or writing secrets, or authoritatively diagnosing whether a secret is configured.
- Mutating GitHub repository settings, rulesets, branch protection, or external services.
- Capability removal, replacement, or reconfiguration in v1.
- Re-expanding a stored snapshot when a named profile changes later.
- Migrating incompatible capability or manifest schemas.
- Bootstrapping, adopting, or migrating a populated project that has no manifest.
- Supporting any pre-bootstrap generated-project or legacy hook contract; none exists in the released
  population.
- Giving GitHub snapshots any template update lifecycle, including local reconciliation.
- Reimplementing Copier's version selection, update merge, or conflict behavior.
- Operating on a target that is not a git working tree.
- Defending against a local adversary with concurrent write access to the target during a mutation.
- Providing native Windows execution guarantees.
- Providing a general-purpose template language, executable plugins, or trusted Copier tasks.
- Proving the semantic validity of an adopter-owned workflow from the generated-project boundary.
- Rolling back artifacts or external effects created by the adopter validation hook.

## Functional-core architecture

The architecture applies to every template-owned Python command, including the new bootstrap CLI and
the existing template validator, readiness checker, and aggregate repository validator. The
adopter-owned `scripts/validate-project` hook is deliberately outside this rule.

### Layer rule

```text
entry point       parse argv, select text or JSON presentation                 [shell]
observers         read files, Git, environment, process results, terminal      [shell]
decoders          bytes/primitive values -> immutable domain values or errors  [pure]
decision core     family-specific intent × legal state -> CommandDecision      [pure]
compiler core     decision + explicit bytes -> OperationPlan                   [pure]
policy core       readiness, validation, gating, compatibility                 [pure]
interpreter       execute a typed plan and capture an ExecutionTrace           [shell]
finalizer         decision + execution trace -> hook decision/CommandOutcome    [pure]
presenter         CommandOutcome -> deterministic text or canonical JSON       [pure]
```

The functional core imports no shell adapter and performs no filesystem, Git, subprocess, environment,
clock, randomness, network, locale, or terminal IO. Shell code contains no product policy: it obtains
an explicitly requested observation or executes one operation from a typed plan, then returns a typed
observation. Dependency direction is always shell -> core.

Existing scripts become thin command adapters over shared core modules rather than importing or
executing one another for policy decisions:

- `validate-template` observes the declared template-source inputs, decodes them, and evaluates pure
  template rules;
- `check-project-readiness` observes the declared readiness paths and evaluates pure readiness rules;
- `validate-repository` folds a pure `ValidationProgram` over effectful stage results in canonical
  order, stopping according to the program rather than ad hoc control flow; and
- `bootstrap-project` observes target/template/bundle state, obtains a pure command decision and plan,
  and interprets that plan transactionally.

Subprocess execution remains an effect. A stage's exit, signal, stdout, and stderr become a
`StageObservation`; the pure aggregate validator decides the next stage and final result.

### Representation rules

Core values are deeply immutable: frozen data classes, enums, byte strings, tuples, frozensets, and
sorted tuples of key/value pairs. Mutable dictionaries and lists may exist while decoding but never
cross into the core. `Path` objects, open descriptors, exception objects, callbacks, iterators, and
subprocess handles are shell values and never appear in persisted or pure domain values.

Bytes are owned once. Observation and compilation intern unique byte strings in a `VerifiedBlobStore`
keyed by `ContentId = sha256(raw_bytes)`; snapshots, renders, plans, and prospective overlays refer to
that ID. Equality remains content equality, not Python object identity. No accepted command may exceed
these v1 resource limits: 4,096 observed or planned file paths, 8,192 total file-plus-directory
operations, 16 MiB for one regular file, 128 MiB of unique retained bytes, 4,096 diagnostics, 1,024
UTF-8 bytes per repository-relative path, 255 bytes per path component, or 64 components. Observation
stops before crossing a limit and returns `InputLimitExceeded`, `ObservationLimitExceeded`, or
`PlanLimitExceeded`; it does not attempt a partial decision. Exact boundary and one-over-boundary cases
are fixtures. Raising a limit is a reviewed schema/contract change, not an ambient machine-dependent
choice.

Every fallible pure function returns a closed result type:

```text
Result[A, E] = Ok A | Err E
```

Expected input, domain, and policy failures are values, not exceptions. Exhaustive `match` statements
end in `typing.assert_never`; static checking must fail when a new union member lacks a case. Assertions
and exceptions are reserved for impossible implementation defects. The outermost shell catches those,
redacts unsafe values, and maps them to `InternalFailure` without continuing a mutation.

Booleans are used only for genuine two-valued facts. Lifecycle state is represented by distinct
constructors, never by combinations such as `manifest_present=True`, `manifest_valid=False`, and
`journal_pending=True`. Optional values are used only when absence is itself valid and cannot change
which transition is legal.

### Error algebra

Every expected sad path belongs to one closed family before presentation:

```text
CommandError =
    UsageError(UnknownCommand | UnknownOption | MissingOption | ConflictingOptions | InvalidValue)
  | InputError(MissingInput | WrongKind | InvalidEncoding | InvalidJson | SchemaViolation
              | DigestMismatch | MarkerCollision | UnsafeRelativePath | InputLimitExceeded)
  | ObservationError(PathMissing | PermissionDenied | SymlinkEncountered | HardLinkEncountered
                     | UnsupportedFilesystem | GitUnavailable | GitCommandFailed
                     | ConcurrentTargetChange | ProcessLaunchFailed(ProcessError)
                     | ProcessSignalled(SignalNumber) | ObservationLimitExceeded)
  | ContractError(InvalidTemplate | InvalidManifest | IncompatibleCatalog
                  | RenderContractViolation | CleanupContractInvalid | SourceContractInvalid
                  | InvalidOperationPlan | PlanLimitExceeded)
  | TransitionError(OperationUnavailable | InputChanged | ManagedDrift | TemplateChanged
                    | CopierConflicts | UnsupportedTarget | RecoveryRequired | LockHeld
                    | OutputLocationOccupied | RecoveryTargetMismatch | RecoveryThirdState)
  | TransactionError(InvalidJournal | InvalidStateRoot | PreconditionChanged | BackupInvalid
                     | TransactionPrimitiveFailed(TransactionPrimitive, ErrnoClass)
                     | FsyncFailed | AtomicReplaceFailed)
  | InternalFailure(StableInternalCode)

TransactionPrimitive =
    CreateStage | CreateBackup | ReadBackup | WriteFile | SetMode | CreateDirectory
  | RemoveFile | RemoveDirectory | ReplacePath | CleanupState

ErrnoClass =
    Permission | ReadOnly | NoSpace | Quota | Missing | Exists | NotDirectory | IsDirectory
  | CrossDevice | Unsupported | Interrupted | ShortWrite | OtherSanitizedErrno

ProcessError =
    ExecutableNotFound | ExecutePermissionDenied | InvalidExecutable
  | ProcessResourceUnavailable | UnsupportedProcessOperation | OtherSanitizedLaunchError

SignalNumber = PositiveInteger(1..255)
```

Shell exceptions are caught at the smallest effect boundary and converted to the corresponding closed
observation or transaction error with sanitized `errno`/Git/process facts. An unrecognized exception
becomes `InternalFailure`; it is never interpolated with `repr(exc)` into user output and never permits
the interpreter to continue. Each error constructor has one stable diagnostic code, outcome class,
subject schema, and admissible `NextAction` constructor. A source fixture proves that mapping is total.

Operation-local aliases never add hidden error constructors:

```text
DecodeError        = UsageError | InputError | ContractError
CompileError       = InputError | ContractError | TransitionError | InternalFailure
PlanInvariantError = ContractError(InvalidOperationPlan | PlanLimitExceeded)
EffectError        = ObservationError | TransactionError | InternalFailure
RenderError        = ContractError(InvalidTemplate | RenderContractViolation | PlanLimitExceeded)
                   | InternalFailure
```

An alias narrows `CommandError`; it is not a second algebra. Expected validation and hook outcomes are
closed values defined below, not errors smuggled through exceptions.

### Primary, observed, derived, and effectful values

| Value | Kind | Contents |
| --- | --- | --- |
| `Intent` | primary | One closed command variant with validated arguments |
| `InitialAnswers` | primary | `project`, frozen profile selection, normalized settings for the initial closure, licensing choice, and slot choices; immutable after install |
| `CapabilityAdditions` | primary | Sorted explicit post-bootstrap capability IDs plus normalized settings introduced with them, including settings for newly resolved dependencies; append-only in v1 |
| `VerifiedBundle` | observed | `InitialAnswers` plus `AdopterBlobMap`; every content reference resolves to bytes matching its declared digest |
| `AdopterBlobMap` | observed | `sha256 -> bytes` for seed-once and legal inputs; immutable and available only during initial apply or equivalent `apply` verification |
| `TemplatePackage` | observed | Decoded definitions plus `TemplateBlobMap`, generated-lifecycle source inventory, source fingerprint, and cleanup contract |
| `TemplateBlobMap` | observed | `sha256 -> bytes` for retained static template payloads, verified on load |
| `RecordedProjectState` | primary | Immutable initial answers, `CapabilityAdditions`, generation provenance, maintenance outcome, `ManagedInventory`, and `SourceBaseline` |
| `ManagedInventory` | primary | Exact bootstrap-managed output entries only; never seed-once files, cleanup files, or the manifest |
| `SourceBaseline` | primary | Generated-lifecycle source entries and tree fingerprint; snapshots also record the clean baseline Git commit |
| `TargetSnapshot` | observed | Immutable bytes and metadata for every path required by ownership, readiness, planning, source comparison, and recovery |
| `SystemState` | derived | The one legal top-level interpretation of target, journal/state-root, manifest, source, and operation-specific observations |
| `CommandDecision` | derived | An intent-specific executable, informational, equivalent, or refused decision |
| `RenderInput` | derived | Complete decoded input for bootstrap-managed rendering |
| `VerifiedBlobStore` | observed/derived | Content-addressed immutable unique bytes under explicit count and byte limits; other core values carry `ContentId`, not duplicate byte strings |
| `ManagedRender` | derived | Bootstrap-managed `path -> {kind, install_mode, content_id}` plus its verified blob store |
| `OperationPlan` | derived | Complete ordered file and directory operations, verified blob store, target identity, expected identities, and gate specification |
| `ExpectedTarget` | derived | Pure overlay of an `OperationPlan` on a `TargetSnapshot` |
| `MechanicalReadinessResult` | derived | Ordered template/readiness findings before the adopter hook, with multiset-comparable identity |
| `ExecutionTrace` | effectful observation | Typed record of completed interpreter steps; no policy conclusions |
| `EffectObservation` | effectful observation | One closed shell reply matching a requested transaction primitive, or `EffectFailed` with a closed error |
| `HookEvidence` | observed | `NotAttempted(reason) \| HookExited(status, streams) \| HookSignalled(SignalNumber, streams) \| HookLaunchFailed(ProcessError)` for this invocation only |
| `ProjectReadinessOutcome` | derived | `Ready(mechanical, hook)` or `NotReady(mechanical, hook, reasons)` for this invocation; never persisted |
| `CommandOutcome` | derived | Exit class, diagnostics, optional plan/status view, and `HookEvidence` |

The manifest uses the key `managed`, never the ambiguous key `installed`. `ManagedInventory` means only
bootstrap-managed output. Initial bootstrap also writes seed-once files and a manifest and may delete
cleanup-only files; those effects belong to the installation plan but never become managed output.

### Complete prospective target

The compiler never validates a partial render as if it were the project:

```text
compile_initial(VerifiedBundle, TemplatePackage, TargetSnapshot)
    -> Result[OperationPlan, CompileError]

apply_plan(TargetSnapshot, OperationPlan)
    -> Result[ExpectedTarget, PlanInvariantError]

mechanical_readiness(ExpectedTarget, ReadinessRules)
    -> MechanicalReadinessResult
```

An initial plan contains managed output, supplied or scaffold seed-once bytes, legal output, the
manifest, cleanup deletions or retained-path ownership transfer, and required parent-directory
operations. Later plans contain only operations their lifecycle owns. No shell-side “extra copy” or
post-plan manifest write is permitted.

`ExpectedTarget` exposes bytes to pure validators. It is not persisted. `TargetSnapshot` contains only
the paths required by the selected command and rejects any change to those paths between observation
and interpretation through the plan's preconditions.

Initial compilation is ordered data flow, not mutation:

1. Strictly decode and verify the bundle, template package, ownership declarations, scaffold, and
   cleanup contract.
2. Select `CleanMaintenance` or explicit `RetainMaintenance(paths)` before rendering.
3. Resolve the frozen capability selection and contributions.
4. Build `RenderInput` and `ManagedRender` from template-owned inputs only.
5. Derive `ManagedInventory` from the exact managed render and `SourceBaseline` from lifecycle source.
6. Build and checksum the candidate manifest from primary values.
7. Compile all seed/legal, managed, manifest, cleanup, and directory effects into one `OperationPlan`.
8. Overlay the plan to obtain `ExpectedTarget`, evaluate template/readiness policy, and attach the exact
   gate specification to the plan.

Any `Err` stops this flow before a lock or filesystem mutation. The shell later re-observes and repeats
the pure decision/compilation under the lock, requiring the same byte-erased `PlanReceipt`.

### Pipeline by command family

```text
decode_cli(raw_argv)                                  -> Result[Intent, UsageError]
observe_bundle(bundle_intent)                         -> Result[RawBundleObservation, ObservationError] [shell]
decode_bundle_state(raw_bundle)                       -> Result[BundleState, InputError]
decide_bundle(bundle_intent, bundle_state)             -> BundleDecision

observe_project(project_intent)                       -> Result[StableRawProjectObservation, ObservationError] [shell]
decode_system_state(stable_raw_project)               -> Result[SystemState, ContractError]
decide_project(project_intent, system_state)           -> StatusDecision | PlanningDecision
                                                         | MutationDecision | RecoveryDecision

compile(decision, explicit_content)                   -> Result[OperationPlan, CompileError]
expected = apply_plan(target_snapshot, operation_plan)-> Result[ExpectedTarget, PlanInvariantError]
evaluate_expected(expected)                           -> ExpectedValidation

drive_transaction(operation_plan, expected_validation)-> ExecutionTrace                         [shell/core loop]
finalize_transaction(decision, trace)                 -> PostInstallDecision
attempt_hook(AttemptHook)                             -> HookEvidence                            [shell]
complete(decision, trace, hook)                        -> CommandOutcome
present(outcome, OutputFormat)                        -> bytes
```

`init` stops after producing and validating a bundle. Inspection commands stop after `decide` and
presentation. Plan commands stop after compilation and serialize the plan. Recovery consumes a valid
journal directly and never compiles a render. `PostInstallDecision` is
`AttemptHook(path) | DoNotRunHook(reason)`; only the first variant permits the shell effect.
`ExpectedValidation = ExpectedGatePass(MechanicalReadinessResult) |
ExpectedGateRefusal(tuple[Diagnostic])`. `HookEvidence` is the effect observation; there is no second
undefined hook type. The pipeline is shared where the types permit sharing;
there is no artificial universal stage that accepts meaningless `NotApplicable` values.

### Dependency policy

Generated-project runtime commands target Python 3.14 and may use dependencies declared by the
generated project's `pyproject.toml`. Source and generated project metadata declare
`requires-python = ">=3.14"`, and the repository pins its primary interpreter with
`.python-version` set to `3.14`. Bootstrap renders dependency declarations as part of the selected
capability set, but does not install packages, execute package setup code, or accept secrets. The core
still uses a small repository-owned `Ok`/`Err` type, frozen data classes, `Enum`, and
`typing.assert_never`; a general FP framework would add domain and dependency surface without adding
capability.

Source assurance uses a small modern toolchain managed by uv and made available from the Nix dev shell:

- **ty** is the one normative type checker, configured through `[tool.ty.environment]` for Python 3.14,
  `[tool.ty.terminal]` with warnings treated as errors, and explicit rules for unresolved references and
  unused ignore comments. A checker canary adds a union constructor and must make the check fail. ty is
  preferred because it is the modern Astral checker aligned with the repository's uv/Ruff toolchain.
  Running a second type checker would add a divergent type-policy surface without independent acceptance
  evidence.
- **pytest** is the source test runner. Existing `unittest` tests remain runnable while fixtures move to
  explicit pytest fixtures; production code never imports pytest.
- **Hypothesis** supplies value properties and rule-based state-machine sequences. The pull-request
  profile is deterministic and database-free; an exploratory pre-release profile records its seed.
  Every discovered failure is shrunk and promoted to a named example-based regression, so a seed is
  evidence for reproduction rather than the permanent regression test.
- **Ruff** is the single Python linter and formatter, configured for Python 3.14. CI runs
  `ruff check` and `ruff format --check`; automatic fixes are a developer action, never a release-gate
  mutation.
- **PyYAML** exists only in the source-CI workflow conformance fixture, behind the custom Actions loader
  defined below.

The template source commits `uv.lock` for its Python packages, while `flake.lock` pins Nix-provided tools.
The Nix dev shell includes uv explicitly and exposes a documented `uv sync`/`uv run` workflow. Source
checks run through uv's locked environment; no ambient user-site or PATH package may satisfy a gate.
Bootstrap renders generated dependency declarations but never resolves or writes a generated `uv.lock`.
When a generated project selects runtime dependencies, its adopter-facing next action is `uv lock` followed
by `uv sync`; generated workflows may enforce that lock after the adopter has created it.

The runtime CLI uses `argparse` only as a shell-side token grammar. A private parser adapter disables
automatic process termination where supported, captures the remaining `error`/`exit` callbacks at that
single effect boundary, and immediately converts them to `UsageError`; callbacks never dispatch domain
work. Pure decoding then turns primitive parsed values into exactly one `Intent` constructor. Help text
is generated from immutable command metadata and golden-tested alongside text and JSON outcomes.

The design does not prohibit runtime libraries categorically. A capability may declare a runtime
dependency when its generated artifacts need one; the dependency, supported Python range, and invocation
contract must be represented in the capability definition and rendered project metadata. Bootstrap does
not silently install or execute those dependencies. Typer, Pydantic, Rich, and similar libraries remain
optional rather than default choices because the v1 CLI and domain algebra already define their own
contracts.

### Why only one aggregate fingerprint remains

A fingerprint is justified only where storing the full bytes is inappropriate. Answers are stored as
normalized values. Managed output is stored as a path-level inventory. Generated-lifecycle source is
stored as a path-level source inventory plus one aggregate `template_source_fingerprint`, allowing both
fast equality and exact changed-path diagnostics. Adopter bytes remain digest-only in the manifest
because their prose must not be persisted there.

## Determinism contract

### Primitives

```text
sha256_hex(b)          = lowercase hexadecimal SHA-256 of byte string b

canonical_json(v)      = json.dumps(v, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")).encode("utf-8")

tagged(kind, payload)  = sha256_hex(b"agentic-template/1/" + kind + b"\n" + payload)

entry(path, b, mode)   = canonical_json({"path": path,
                                         "mode": "100755" | "100644",
                                         "sha256": sha256_hex(b)})

tree_hash(kind, files) = tagged(kind, b"\n".join(entry(...) for every file,
                                                 sorted by the UTF-8 bytes of its path))
```

Entries are canonical JSON objects, so no path content can change how a tree is parsed; JSON escaping
makes the `\n` join unambiguous.

### Value domain

`canonical_json` accepts only strings, booleans, `null`, integers within ±2^53, arrays, and
string-keyed objects. Floats, NaN, and infinities are rejected.

**Strings must contain no surrogate code point.** Python's JSON decoder accepts `"\ud800"` and
produces a lone surrogate that `ensure_ascii=False` UTF-8 encoding then refuses, so a document that
decodes successfully could still fail to serialize. Surrogates are rejected at decode time with
`BOOTSTRAP_INPUT_SURROGATE`.

### Strict decoding

Every JSON document bootstrap reads is decoded with duplicate object keys rejected via an
`object_pairs_hook`; exact type checks, so `True` is not an integer and `1` is not a boolean; floats,
NaN, and infinities rejected; integers range-checked; object keys required to be strings; and unknown
keys rejected wherever the schema is closed.

### Canonical path grammar

Every path recorded, hashed, planned, or accepted must be a repository-relative POSIX path that is
valid UTF-8; non-empty and not absolute; separated only by `/`, with no backslash; free of empty
components, repeated separators, and a trailing separator; free of `.` and `..` components; and free of
NUL and other C0 control bytes. Paths are never normalized into validity — a non-conforming path is
rejected with `BOOTSTRAP_INPUT_PATH_GRAMMAR`. Two declared paths differing only by case are rejected at
source validation.

### LF normalization

Each managed artifact is declared `text` or `binary`. A `text` artifact's normalized form requires the
bytes to decode as UTF-8, then replaces every CRLF with LF, then every remaining lone CR with LF, then
requires exactly one trailing LF — adding one if absent, collapsing a run to one. Mixed endings
normalize without error, because a checkout can produce them. Invalid UTF-8 in a declared text artifact
is `BOOTSTRAP_ARTIFACT_ENCODING`. A `binary` artifact is hashed exactly, with no normalization and no
encoding requirement.

Generated text is installed already normalized, so a fresh installation's on-disk bytes equal their
normalized form. Comparison normalizes on-disk bytes identically, so a `core.autocrlf=true` checkout
reports no false drift. Bootstrap installs no `.gitattributes`; `docs/delivery-workflow.md` recommends
`* text=auto eol=lf` as adopter-owned configuration.

### Other rules

- Symlinks are rejected anywhere in a hashed source or output tree.
- Only regular files are artifacts. Empty directories are outside the model; an absent file differs
  from an empty file, which hashes as SHA-256 of zero bytes.
- No Unicode normalization anywhere. Adopter bytes are preserved exactly; mechanical identifiers are
  ASCII, constrained by explicit character classes.
- `mode` reflects only the owner execute bit. Managed files install as exactly `0644` or `0755`
  independent of umask; comparison ignores group and other bits, matching git's index model.

### The one fingerprint

```text
LifecycleSourceEntry = {path, kind, mode, sha256}

SourceOwnership =
  { schema_version
  , lifecycle_paths: tuple[{path, kind, mode}]
  , snapshot_cleanup_paths: tuple[{path, kind}] }

template_source_fingerprint =
    tagged(b"template-source", canonical_json(sorted LifecycleSourceEntry values))
```

`.agentic-template/source-ownership.json` is the single ownership manifest for both retained lifecycle
source and initial snapshot-cleanup authority. It does not list itself inside `lifecycle_paths`; after
strict canonical decoding, the loader automatically injects its own observed path, mode, and byte hash
as a `LifecycleSourceEntry`. There is no recursive self-hash because the serialization contains no hash
of itself, while any change to either ownership set still changes the aggregate source fingerprint.
Every declared lifecycle entry must exist, no retained lifecycle path may be unlisted, and the two path
sets must be disjoint, unnested, and case-distinct.

The inventory includes exactly the behavior-affecting inputs both generation paths retain:

- the public bootstrap, template-validation, readiness, and repository-validation entry points;
- every shared functional-core and imperative-shell module they import;
- the capability catalog, profiles, core definitions, schemas, static blobs, render fragments, and
  stable-ID compatibility contract; and
- generated validation and gating policy data, required agent instructions, skills, and other retained
  static contracts checked by template validation.

`snapshot_cleanup_paths` is the finite source-only set excluded by Copier and removed or explicitly
retained by initial snapshot apply: source tests and fixtures, source-CI conformance data, historical
specs, and source development configuration. The cleanup-control inventory is not a lifecycle entry or
cleanup target because it authorizes expected identities and removes itself separately. Template
validation derives both ownership sets from this one manifest rather than maintaining a second list. A
source fixture perturbs every lifecycle entry and the ownership serialization and proves the fingerprint
changes, then adds an unlisted retained import and proves validation fails.

The manifest persists the sorted entries as `SourceBaseline.entries` as well as their aggregate hash.
That duplication is intentional: the hash provides quick equality while the entries provide exact
changed-path diagnostics. For a GitHub snapshot, initial apply additionally requires every lifecycle
source entry to match `HEAD`, then records that reachable commit as `SourceBaseline.snapshot_commit`.
Copier projects record no source commit because Copier, not Git history, supplies their update lineage.

## Render boundary

```text
render_managed : RenderInput -> TemplateBlobMap -> Result[ManagedRender, RenderError]
```

`RenderInput` carries decoded structures and renderable bodies, never identities. Revision 4 carried
tree hashes for capability definitions, core inputs, and document fragments; a hash cannot be rendered
into output bytes, so the declared purity was fictional and the renderer would have had to read ambient
blobs.

```text
RenderInput
  render_input_version              # integer; bumped when this schema changes
  generation_path                   # "copier" | "github"
  project{name, default_branch}
  licensing{mode, content_sha256?}
  profile{id, frozen: [CapabilityId]}
  additions: [CapabilityId]                              # CapabilityAdditions.requested
  effective: [CapabilityId]         # closure, sorted
  definitions: {CapabilityId -> CapabilityDefinition}   # decoded, effective only
  core: CoreDefinition                                   # decoded
  settings: {CapabilityId -> {name -> value}}            # normalized merge of initial and addition settings
  contributions: [ResolvedContribution]                  # final resolved order
  documents: {path -> [FragmentBody]}                    # bodies, not identities
  maintenance{status, retained_paths}                    # retained paths affect document text
  slots: {slot -> {mode, content_sha256?}}
```

`TemplateBlobMap` supplies retained static payloads by content address. `AdopterBlobMap` is deliberately
not accepted by `render_managed`: seed-once and legal bytes enter only `compile_initial`, which places
them in the complete initial plan without making them managed output. Every referenced blob must be
present and digest-valid before compilation.

`maintenance.retained_paths` is part of the input because a skipped cleanup transfers those paths to
adopter ownership, which changes what `docs/template-updates.md` says. Revision 4 passed only the
status, so two projects with identical selections and different retained paths would have rendered
different documents from identical inputs.

The renderer contract is self-contained here. Definitions decode to these closed shapes:

```text
CoreDefinition =
  { artifacts: tuple[ArtifactDefinition]
  , slots: tuple[SlotDefinition]
  , contributions: tuple[ContributionDefinition] }

CapabilityDefinition =
  { id, dependencies: tuple[CapabilityId], settings: tuple[SettingDefinition]
  , artifacts: tuple[ArtifactDefinition]
  , contributions: tuple[ContributionDefinition]
  , document_fragments: tuple[DocumentFragmentDefinition]
  , external_requirements, fixture_cases }

ArtifactDefinition = {path, kind: Text | Binary, install_mode, template_blob, substitutions}
SlotDefinition =
  { id, owner_artifact, context: Yaml | Toml | Json | Shell | Markdown
  , cardinality: ExactlyOne | ZeroOrOne | Many, separator, allowed_contribution_kind }
ContributionDefinition =
  { id, slot, order: integer, kind, body_blob, substitutions }
ResolvedContribution =
  { slot, owner: Core | CapabilityId, contribution_id, order, kind, rendered_body }
```

IDs are non-empty canonical ASCII tokens. Artifact paths are fixed by the core or selected capability
definition; no setting or contribution chooses a path. Within its owner, artifact IDs, setting names,
slot IDs, contribution IDs, and document-fragment IDs are unique. Globally, an artifact path has exactly
one owner; a core artifact may expose slots but a capability never owns or replaces that artifact.

Resolution is normative:

1. Validate unique IDs, path ownership, referenced blobs, slot references, setting declarations, and
   dependency acyclicity before selection.
2. Compute the dependency closure, then order capabilities by a topological sort with capability ID as
   the tie-breaker. Normalize every setting, including defaults, before rendering.
3. Render core contributions and contributions from the effective capabilities. Contribution identity
   is `(slot, owner, contribution_id)`; a duplicate identity is a contract error, never last-writer-wins.
4. For each slot, sort by `(order, owner-order, owner-id, contribution-id)`, where `Core` precedes
   capability owners and capability owner-order is the closure order. Enforce `ExactlyOne`,
   `ZeroOrOne`, or `Many` after selection. Wrong kind, missing slot, or cardinality failure is a distinct
   `InvalidTemplate` reason.
5. Encode substituted scalars with the slot or artifact's declared YAML, TOML, JSON, shell, or Markdown
   context encoder; normalized booleans alone control whole optional sections. Join a `Many` slot with
   its declared constant separator.
6. Render every whole artifact, reject any path collision or undeclared output, and return
   `ManagedRender` sorted by canonical path bytes.

No expression evaluation, code import, shell, ambient read, capability-chosen output path, implicit
dictionary order, or override precedence exists. A capability whose output depends on another
capability's contributions is deterministic because the entire effective contribution set is resolved
before any containing artifact is rendered.

### What must be persisted

So that `add`, `restore`, `reconcile`, status, and equivalent `apply` verification work: persist
immutable `InitialAnswers` including per-slot, initial-setting, and licensing digests;
`CapabilityAdditions`; generation and maintenance provenance;
`ManagedInventory`; and `SourceBaseline`. Do not persist `RenderInput`, a render identity, adopter prose,
or old source bytes. Every render uses the current retained template package, while operation-specific
preconditions compare it with the recorded managed and source inventories.

| Operation | Inputs | Sufficient? |
| --- | --- | --- |
| equivalent `apply` | Recorded values plus the supplied bundle for field-wise input comparison; current template for managed-render verification | Yes; seed/legal bytes are compared by digest, not rewritten |
| `restore` | Current template + recorded state -> render requested managed projection -> require equality with those inventory entries | Yes; writes only already certified requested bytes |
| `add` | First render the old selection and require complete inventory equality; then render additions-expanded selection | Yes; separates renderer regression from legitimate shared-output changes |
| `reconcile` | Verify observed old managed files against old inventory; render new template from recorded state | Yes; new-source output is a candidate, never compared with old render hashes |

## Project manifest

`.agentic-template/project.json` contains only primary recorded fields plus its checksum; it has no
derived block.

```text
{
  "schema_version": 1,
  "answers": {                          # primary: recorded intent
    "project": {"name", "default_branch"},
    "profile": {"id", "requested"},     # requested is exact for custom, else the frozen expansion
    "settings": {...},                    # settings for the initial closure only
    "licensing": {"mode", "content_sha256"},   # digest only; never legal prose
    "slots": {"<slot>": {"mode", "content_sha256"}}
  },
  "additions": {                       # primary: append-only CapabilityAdditions
    "requested": [...],                # explicit IDs, sorted
    "settings": {"<capability-id>": {...}}  # settings first introduced by add
  },
  "provenance": {                       # primary: historical facts
    "generation_path",
    "maintenance": {"status", "retained_paths"},
    "source_baseline":                  # tagged sum, selected by generation path
      {"kind": "github", "fingerprint", "entries", "snapshot_commit"}
      | {"kind": "copier", "fingerprint", "entries"}
  },
  "managed": [                          # primary: bootstrap-managed output only
    {"path", "kind", "mode", "sha256"}
  ],
  "checksum": "..."                     # tagged over canonical_json(document minus checksum)
}
```

**Validity is parse, schema, and checksum.** Nothing else. Revision 4 recomputed the closure, the
render identity, and the expected inventory on every read and rejected the manifest on mismatch, which
made legitimate template updates indistinguishable from corruption. Those recomputations still happen —
but as *classification facts and operation preconditions*, where a mismatch has a specific meaning and
a specific next action.

The effective closure is recomputed from `profile.requested` plus `CapabilityAdditions.requested`
against the current
catalog. The stable-ID contract forbids changing a capability's dependencies, so a closure change under
a nominally compatible catalog is a compatibility violation, reported as such rather than as manifest
corruption.

`CapabilityAdditions.requested` is the set of IDs explicitly introduced after bootstrap;
`CapabilityAdditions.settings` contains the complete normalized setting map, including deterministic
defaults, for every capability first introduced through an add operation, whether requested directly or
resolved as a dependency. `effective_settings` is the disjoint union of initial
`answers.settings` and addition settings. An add request naming an already effective capability may
repeat settings only when its complete normalized map equals the persisted effective map; it changes no
state. No setting moves between the two owners, so initial input identity remains immutable while
additive state remains reconstructable.

The manifest is excluded from `managed`; a self-referential hash is unsatisfiable. Its integrity
rests on the checksum, which detects truncation and casual editing and is not a security control.

The manifest never contains product prose or legal text, input source paths, repository owner or name,
timestamps, machine-specific absolute paths, secrets or secret-presence claims, live GitHub state, any
claim about a seed-once file's current content, or a hash that would make seed-once content managed.

On Copier projects, version and lineage stay in `.copier-answers.yml`. GitHub snapshots record the
source identity and reachable baseline commit required for repair, but no template repository owner,
name, tag, or update lineage.

### Corrupt or unreadable manifest

An invalid manifest is a closed `ManifestError` variant and exits 2. It never suggests `restore`, which
depends on trusted manifest state. A valid pending journal is classified before the manifest and names
`recover`; an invalid journal produces `InvalidJournal`/`StateRootInvalid` evidence and preserves it.
Without a journal,
guidance is `git restore .agentic-template/project.json` when a tracked good version exists, or
regenerate the project and move adopter-owned content. Re-running initial apply is allowed only when
the complete target still matches a recognized generated scaffold. There is no manifest reconstruction,
legacy adoption, or guessed recovery path.

### Schema lifetime

Every v1 engine reads every valid schema-version-1 manifest. Compatible updates may add optional fields
with deterministic defaults but may not reinterpret existing fields or require a new field from an old
manifest. An unknown newer schema fails before any write.

## Legal-state and transition algebra

Classification is staged so invalid combinations are unrepresentable. Observation failures are not
smuggled into a partially populated facts record.

### Staged project state

```text
TargetEnvironment =
    UnsupportedGitTarget(TargetReason)
  | SupportedWorktree(WorktreeContext)

WorktreeContext = {target_identity, state_root, target_protection}

TargetProtection = OrdinaryProject | CanonicalTemplateSource(RemoteEvidence)

OrdinaryWorktree = WorktreeContext(target_protection = OrdinaryProject)
ProtectedWorktree = WorktreeContext(target_protection = CanonicalTemplateSource)

JournalObservation =
    NoJournal
  | StaleJournalWrite(PendingIdentity)
  | RecoverableJournal(ValidatedJournal)
  | JournalTargetMismatch(ValidatedJournal, TargetIdentity)
  | InvalidJournal(JournalError)
  | RecoveryEvidenceInvalid(ValidatedJournal, EvidenceError)
  | OrphanTransactionState(OrphanEvidence)

CleanupObservation =
    NoSnapshotCleanup
  | CleanupContractValid(CleanupContract)
  | CleanupContractMismatch(CleanupMismatch)

ManagedObservation = ManagedVerified | ManagedDrift(PathDelta)

SnapshotCondition =
    SnapshotSourceSame(ManagedObservation)
  | SnapshotSourceChanged(SourceDelta, SnapshotRepair, ManagedObservation)
  | SnapshotSourceUnrecoverable(SourceDelta, Reason, ManagedObservation)

CopierCondition =
    CopierConflicted(PathDelta)
  | CopierSourceSame(ManagedObservation)
  | CopierSourceChanged(SourceDelta, ManagedObservation)

ExistingProjectState =
    UnsafeExistingProject(RecordedProjectState, TopologyError, TargetSnapshot)
  | IncompatibleExistingProject(RecordedProjectState, ClosureError, TargetSnapshot)
  | SnapshotExistingProject(RecordedProjectState, SnapshotCondition, TargetSnapshot)
  | CopierExistingProject(RecordedProjectState, CopierCondition, TargetSnapshot)

ManifestFreeShape = EmptyManifestFree | PopulatedManifestFree

ProjectObservation =
    RecognizedScaffold(GenerationPath, CleanupObservation, TargetSnapshot)
  | UnsupportedManifestFree(ManifestFreeShape, TargetSnapshot)
  | InvalidManifest(ManifestError, TargetSnapshot)
  | ExistingProject(ExistingProjectState)

SystemState =
    TargetUnavailable(UnsupportedGitTarget)
  | StalePendingWrite(WorktreeContext, PendingIdentity)
  | JournalPending(WorktreeContext, ValidatedJournal)
  | JournalAtDifferentTarget(WorktreeContext, ValidatedJournal, TargetIdentity)
  | StateRootInvalid(WorktreeContext,
        InvalidJournal | RecoveryEvidenceInvalid | OrphanTransactionState)
  | ProtectedTargetAvailable(ProtectedWorktree, ProjectObservation)
  | ProjectAvailable(OrdinaryWorktree, ProjectObservation)
```

The shell first establishes `TargetEnvironment`, then observes the one canonical journal location. A
present but invalid journal, orphan, target mismatch, or stale pending write can never become
`NoJournal`. Only exact `NoJournal` permits manifest inspection. The decoder constructs
`ProjectObservation` only after schema and checksum handling, so an absent manifest cannot coexist with
recorded answers, source comparison, or managed drift. For an absent manifest, the generation-path
recognizer is a total two-way decoder: an exact scaffold constructs `RecognizedScaffold`; every other
empty or populated shape constructs `UnsupportedManifestFree` with its explicit shape. No arbitrary
empty target is inferred to have generation provenance.

Journal observation first decodes schema/checksum and authenticates every state-root backup and
preparation record that the phase requires; only fully valid evidence proceeds to target-identity
comparison. `JournalTargetMismatch` therefore means valid recovery evidence bound to another target,
while any coexisting evidence defect is structurally `RecoveryEvidenceInvalid` and exits 2.

Existing-project classification is structural, not precedence over a Cartesian product. Topology is
classified first, then catalog compatibility, then the recorded generation path selects exactly one of
`SnapshotCondition` or `CopierCondition`; only the Copier branch can contain conflicts. Source condition
then carries its managed observation, so source drift and managed drift may coexist without matching two
rows. Public factories do not expose constructors that could pair snapshot provenance with a Copier
condition. Decoder and property fixtures prove those illegal combinations cannot be constructed.

### Coherent project observation

No command decodes a `SystemState` from a one-pass mixture of tree and journal bytes. The shell's
`collect_observation_pass` captures the target root identity; the exact state-root entry names, kinds,
modes, and hashes; and the ordered identity plus required bytes of every bounded target path used by
classification, planning, readiness, or source comparison. It performs two complete passes and returns
`StableRawProjectObservation` only when their canonical observations are identical. Semantically
irrelevant access-time metadata is excluded; content, kind, mode, device/inode anchors, directory
entries, journal presence, and journal bytes participate.

On mismatch the shell discards both passes and retries, for at most three complete pairs. A third
mismatch returns `ObservationError(ConcurrentTargetChange)` with the next action to wait for the other
writer and retry; no partial `SystemState`, status view, or plan is produced. A valid journal observed in
both passes decodes normally as journal state rather than project state. Equality after an intervening
change is acceptable only when every observed semantic identity has returned to the same value.

This protocol is non-mutating and is used by status and every planning/mutating command's initial
observation. A mutating command additionally acquires the exclusive lock, performs the same coherent
observation again, and requires the recompiled plan receipt and target identity to match. Thus status
does not need a race-prone lock probe, while an in-progress journal creation, `MUTATING` write,
`RESTORED` or `SEALED` cleanup, journal removal, or ordinary concurrent adopter edit is either observed
as one stable state or reported explicitly as concurrent change.

`TargetProtection` is defense in depth for mutation, not repository authentication. The observer reads
all configured fetch and push remote URLs and normalizes GitHub HTTPS, `ssh://`, and scp-like forms to
lowercase `host/owner/repository`, with default ports removed and one trailing `.git` removed. Userinfo
does not participate. A match for
`github.com/knirski/agentic-template` yields `CanonicalTemplateSource`. Inspection remains legal;
mutation refuses. Unknown hosts and malformed remotes do not match. Positive and negative fixtures pin
the normalization contract.

Source comparison uses `SourceBaseline.entries`, so `SourceDelta` always names exact paths. A snapshot
repair is `RestoreSnapshotSource(commit, paths)` only when the recorded commit is still reachable and
the paths at that commit match the recorded entries. Otherwise the only honest next action is
regeneration. Copier source change never creates a Git repair decision.

### Closed intent and decision families

```text
BundleIntent = InitBundle(InitOptions)

ProjectIntent =
    InspectStatus(StatusOptions)
  | PlanApply(ApplyPlanOptions)
  | PlanAdd(AddOptions)
  | PlanRestore(RestoreOptions)
  | PlanReconcile(ReconcileOptions)
  | Apply(ApplyOptions)
  | Add(AddOptions)
  | Restore(RestoreOptions)
  | Reconcile(ReconcileOptions)
  | Recover(RecoverOptions)

Intent = BundleIntent | ProjectIntent

BundleState = OutputAvailable | OutputLocationOccupied

CommandDecision =
    BundleDecision(WriteBundle | RefuseBundle)
  | StatusDecision(DescribeStatus(StatusView) | RefuseStatus(CommandError, PartialStatusView))
  | PlanningDecision(CompileCandidate | RefusePlan)
  | MutationDecision(InitialInstall | EquivalentVerification | AddCapabilities
                     | RestoreManaged | ReconcileTemplate | RefuseMutation)
  | RecoveryDecision(DiscardStalePending | DiscardPreparation | RollBack
                     | FinishRollbackCleanup | FinishForward
                     | NoRecoveryNeeded | RefuseRecovery)
```

Every constructor carries the data required by its next pure stage. There is no operation-neutral
`ApplyDecision`, `NotApplicable` fact, or adapter-specific reinterpretation.
`decide_bundle : BundleIntent × BundleState -> BundleDecision` and
`decide_project : ProjectIntent × SystemState -> StatusDecision | PlanningDecision | MutationDecision |
RecoveryDecision` are separately total; init never receives a meaningless project state. Static
exhaustiveness, generated transition tests, and one maintained preimage witness for every leaf decision
constructor prove both that all legal inputs are handled and that no constructor is dead or shadowed.

### Normative intent/state transitions

The table is exhaustive over the structural constructors above. “Describe” returns a `StatusView`;
“refuse” returns a typed diagnostic and no plan. Within a combined plan/mutation column the two actions
are named separately whenever they differ.

| System/project state | `status` | `plan apply`/`apply` | `plan add`/`add` | `plan restore`/`restore` | `plan reconcile`/`reconcile` | `recover` |
| --- | --- | --- | --- | --- | --- | --- |
| Git unavailable, bare, or non-worktree | Describe unsupported target | Refuse target | Refuse target | Refuse target | Refuse target | Refuse target |
| Stale `journal.pending`, no authoritative journal | Describe pending cleanup | `RecoveryRequired` | `RecoveryRequired` | `RecoveryRequired` | `RecoveryRequired` | `DiscardStalePending`, verify absence, exit 0 |
| Valid pending journal | Describe phase and operation | `RecoveryRequired` | `RecoveryRequired` | `RecoveryRequired` | `RecoveryRequired` | Phase-specific recovery |
| Valid journal bound to another target identity | Describe mismatch | `RecoveryTargetMismatch` | `RecoveryTargetMismatch` | `RecoveryTargetMismatch` | `RecoveryTargetMismatch` | `RecoveryTargetMismatch`, exit 1; preserve evidence |
| Invalid journal/evidence or orphan transaction state | Describe evidence and exit 2 | `InvalidJournal`/`InvalidStateRoot`, exit 2 | Same | Same | Same | Refuse, exit 2, preserve evidence |
| Canonical template source, no journal, any project observation | Describe with protected-target notice | Refuse protected target | Refuse protected target | Refuse protected target | Refuse protected target | `NoRecoveryNeeded` |
| Recognized scaffold | Describe uninstalled scaffold | Valid cleanup: compile; mismatch: compile only with `--leave-maintenance-artifacts`, otherwise `CleanupContractInvalid` | Refuse: no manifest | Refuse: no manifest | Refuse: no Copier lifecycle | `NoRecoveryNeeded` |
| Unsupported manifest-free target, empty or populated | Describe unsupported greenfield state | Refuse; generate a fresh scaffold through GitHub or Copier | Refuse | Refuse | Refuse | `NoRecoveryNeeded` |
| Invalid manifest | Describe invalid state, exit 2 | Refuse invalid manifest | Refuse | Refuse | Refuse | `NoRecoveryNeeded` |
| Existing unsafe topology | Describe exact unsafe path | Refuse topology | Refuse | Refuse | Refuse | `NoRecoveryNeeded` |
| Existing, incompatible closure | Describe incompatibility | Refuse upstream contract defect | Refuse | Refuse | Refuse | `NoRecoveryNeeded` |
| Existing Copier conflicts | Describe paths | Refuse until resolved | Refuse until resolved | Refuse until resolved | Refuse until resolved | `NoRecoveryNeeded` |
| Existing snapshot source changed, repairable | Describe exact source delta and command | Refuse until source repair | Refuse | Refuse | Refuse: snapshots never reconcile | `NoRecoveryNeeded` |
| Existing snapshot source changed, unrecoverable | Describe exact delta and regeneration step | Refuse | Refuse | Refuse | Refuse | `NoRecoveryNeeded` |
| Existing Copier source changed, managed verified | Describe template delta | Plan/apply refuse `TemplateChanged` | Plan/add refuse until reconcile | Plan/restore refuse until reconcile | Plan compiles; reconcile compiles candidate | `NoRecoveryNeeded` |
| Existing Copier source changed with managed drift | Describe both deltas | Plan/apply refuse `TemplateChanged` | Plan/add refuse | Plan/restore refuses source mismatch | Plan compiles only with `--overwrite-drift`; reconcile requires its matching receipt | `NoRecoveryNeeded` |
| Existing same source with managed drift | Describe drift | Plan refuses; apply returns `ManagedDrift` | Plan/add both refuse until restore | Plan/restore compile requested certified repair | Plan/reconcile both refuse because source is unchanged | `NoRecoveryNeeded` |
| Existing same source, verified managed output | Describe healthy mechanical state | Plan/apply compare supplied bundle: `EquivalentVerification` or `InputChanged` | Plan/add compile valid additive request or report already selected | Plan/restore produces empty repair or refuses unmanaged path; restore verifies equivalence | Plan/reconcile both refuse because source is unchanged or path is snapshot | `NoRecoveryNeeded` |

For plan commands, “compile” produces a plan without interpretation; “refuse” produces no plan and exits
1. `plan restore` is the repair preview, and `plan reconcile --overwrite-drift` is the only plan that
authorizes destructive overwrite. Other plan commands report the blocking drift but do not pretend to
have an executable candidate.
`status` does not require a mutating precondition and never runs render, gate, or hook.

### Operation-specific render oracle

`ManagedInventory` is an oracle only under the source and selection for which it was recorded:

- **`EquivalentVerification`:** render the complete recorded selection and require exact key, kind, mode, and
  hash equality with the complete managed inventory.
- **Restore:** render the recorded selection, then require equality only for every requested managed
  path before writing that certified projection. Unrequested pre-existing drift may remain and status
  continues to report it.
- **Add:** first render the old selection and require complete equality with the complete managed
  inventory. Then render the additions-expanded selection; differences in shared outputs are legitimate
  candidate changes attributable to the add.
- **Reconcile:** verify observed old files against the old managed inventory. Render the new source as
  the candidate; never compare its hashes with old render hashes.

`RenderContractViolation` is a typed `ContractError`, not a project-state constructor. It is reachable
only when unchanged source and selection fail the applicable old-render comparison: equivalent apply,
restore's requested projection, or add's complete old selection. It never arises from a new-source
reconcile.

## Operation semantics

Normative. Every state transition, manifest update, diagnostic, and test must agree with this table.

| Operation | Initial answers | Capability additions | Source baseline | Maintenance | Managed inventory | Render behavior |
| --- | --- | --- | --- | --- | --- | --- |
| `init` | No target state | — | — | — | — | No managed render |
| `status` | Read | Read | Compare entries and hash | Read | Compare observed files | No render |
| Plan commands | Read or proposed | Read or proposed | Compare | Read/proposed initial outcome | Verify/derive candidate | Render only when required by the intent |
| Initial `apply` | **Set** | Set empty | **Set** | **Set** | **Set** | Compile complete initial plan |
| `EquivalentVerification` | Unchanged | Unchanged | Unchanged | Unchanged | Unchanged | Verify complete recorded render |
| `add` | Unchanged | **Extend requested IDs and normalized settings** | Must match; unchanged | Unchanged | **Update** | Verify old complete render, then render expanded selection |
| `restore` | Unchanged | Unchanged | Must match; unchanged | Unchanged | **Unchanged** | Render and certify requested managed projection |
| `reconcile` | Unchanged | Unchanged | **Advance entries and hash** | Unchanged | **Update** | Render new source as candidate |
| `recover` from `PLANNED` | Keep pre-state | Keep pre-state | Keep pre-state | Keep pre-state | Keep pre-state | No render; discard preparation |
| `recover` from `MUTATING` | Restore pre-state | Restore pre-state | Restore pre-state | Restore pre-state | Restore pre-state | No render; idempotent rollback |
| `recover` from `RESTORED` | Keep pre-state | Keep pre-state | Keep pre-state | Keep pre-state | Keep pre-state | No render; verify pre-state and finish rollback cleanup |
| `recover` from `SEALED` | Keep candidate | Keep candidate | Keep candidate | Keep candidate | Keep candidate | No render; finish cleanup forward |

`restore` records nothing. It cannot introduce an unrecorded byte or a mixed requested projection. A
targeted repair makes no whole-render claim about unrequested paths and may intentionally leave unrelated
pre-existing drift.

`add` requires the current template-source fingerprint to equal the recorded one, persists every
normalized setting for capabilities first introduced by the operation, and names
`reconcile` when it does not, so a capability addition cannot silently absorb a template update.

## Readiness and gating

### Structured readiness result

`check-project-readiness.py` and the engine share one contract, so gating comparison is structural
rather than textual.

```text
MechanicalReadinessResult
  schema_version
  findings: [Finding]                # sorted; see below

Finding
  code        # stable identifier, e.g. READINESS_PRD_HEADING_MISSING
  subject_at  # Path p | Repository
  subject     # the specific thing at fault: slot id, heading title, requirement id,
              # capability id, artifact path, or workflow job id
  rule        # the specific check, stable across message rewording
  severity    # blocking | informational
  message
  next_action # typed NextAction; rendered to text only at the presenter
```

**Finding identity is `(code, subject_at, subject, rule)`**, and comparison is over **multisets**, so a
finding occurring twice is not collapsed and an increased count is detectable. Revision 3 compared
`(code, path)` sets, which could not distinguish two missing headings from one.

`subject_at` is a sum type. Revision 4 allowed `path: ""` for repository-level findings, which violates
the canonical path grammar's non-empty requirement.

Findings sort by `(code, subject_at rendered as "" for Repository else the path bytes, subject, rule)`,
so the order is normative and diffable.

`severity: informational` never makes a project unready and never gates a transaction.

### Gating

```text
gate : Operation
    -> MechanicalReadinessResult   -- baseline, captured before staging
    -> MechanicalReadinessResult   -- expected, computed from ExpectedTarget
    -> MechanicalReadinessResult   -- observed, after installation
    -> GateResult
```

Three comparisons, each proving one thing, evaluated in order:

1. **Artifact verification.** Every planned file's observed raw installed bytes, normalized identity,
   kind, and install mode must equal the plan's new values; every planned directory operation must have
   its declared result. No exemption applies.
2. **Template-contract evaluation must succeed.** The shell does not spawn `validate-template.py`
   inside the transaction. It observes the post-install inputs and calls the same pure rules used by
   that CLI. No exemptions.
3. **Readiness comparison**, by operation:

| Operation | Rule |
| --- | --- |
| `InitialInstall` | `observed` blocking multiset must **equal** `expected` blocking multiset, and `expected` must contain exactly the placeholder findings predicted for the bundle's declared `scaffold` slots. Equality, not containment; pre-install findings are not inherited |
| `EquivalentVerification` | No filesystem change occurred, so the complete observed result must equal baseline; this is validation, not a transaction gate |
| `add`, `restore`, `reconcile` | Over the **blocking projection only**, for every finding identity, `count(observed) ≤ count(baseline)`. Genuinely pre-existing blocking findings are retained; none may be introduced or worsened |

Gating decides rollback. The canonical command decides the exit code. These are separate throughout.

The `add`/`restore`/`reconcile` rule is what makes those operations usable on an incomplete project: a
project whose PRD is still a placeholder is unready, and adding a capability to it must remain possible.

## Template evolution compatibility

A schema-v1-compatible template update **may not**:

- add a required seed-once path;
- add a blocking readiness rule over an adopter-owned path;
- make an existing informational rule blocking; or
- otherwise introduce a blocking obligation that an existing v1 manifest cannot satisfy through
  `add`, `restore`, or `reconcile`.

Anything in that list is not a compatible v1 update. It requires a separately approved future
lifecycle with preview, collision detection, and explicit ownership transfer; v1 defines no migration
mechanism.

This closes a real dead end rather than relaxing the gate. Without the rule, an update that adds a
required seed-once file has no good outcome: if the new checker reports it in both baseline and
observed, reconciliation gate-passes into permanent unreadiness; if the obligation activates only after
the new manifest is installed, the finding is observed-only and reconciliation rolls back. Neither
creates the file, because `reconcile` may not write seed-once paths. The previous review correctly
identified that the multiset rule is not the cause and must not be weakened to compensate.

Readiness rules are declarative values, not arbitrary Python callbacks:

```text
ReadinessRuleDefinition =
    { identity: (code, subject_kind, rule)
    , severity
    , owned_path_class
    , satisfier: InitialPlan | ManagedRender | AdopterEdit | ExternalAction
    , predicate: PredicateKind
    , parameters: canonical immutable values }
```

`PredicateKind` is a closed union implemented by total pure evaluators. Tightening a predicate requires
changing its canonical definition. `validate-template.py` compares complete canonical definitions with
the frozen schema-v1 baseline and rejects a new or changed blocking definition over adopter-owned state,
an informational-to-blocking transition, a new required seed-once path, or a blocking rule whose
declared satisfier is unavailable to every legal operation.

A compatibility corpus additionally contains representative old conforming `TargetSnapshot` values,
including all adopter-owned predicate boundaries. Every new checker evaluates the corpus and must not
produce a new blocking multiset. The definition comparison provides structural coverage; the corpus
guards evaluator semantics. Predicate-kind semantics, the adopter-facing baseline, and its corpus are
immutable for manifest schema v1: reconcile additionally requires those specific
`SourceBaseline.entries` to retain their recorded hashes. New managed-output rules are allowed only when
their satisfier is the candidate managed render and the expected target proves the obligation satisfied.
Both structural and behavioral gates must pass.

## Input boundary

Three disjoint classes. Revision 4 violated this by putting `source-ci-allowlist.json` in all three at
once — fingerprinted, validated by generated-project template validation, and excluded by Copier while
also deleted by snapshot install — so a Copier project could never match its own recorded fingerprint
and a snapshot could fail its own installation gate.

| Class | Members | Retained in generated projects? | In `template_source_fingerprint`? | Validated by |
| --- | --- | --- | --- | --- |
| Generated-lifecycle | `source-ownership.json` plus every `lifecycle_paths` entry: entry points, shared core and shell modules, catalog, definitions, blobs, schemas, profiles, stable-ID fixture, readiness-rule baseline and compatibility corpus, and policy data | Yes, both paths | **Yes** | Generated template-contract core; source perturbation fixtures |
| Source-only snapshot-cleanup target | Exactly `snapshot_cleanup_paths`: source tests and workflow fixtures, source `pyproject.toml` and `uv.lock`, `source-ci-allowlist.json`, historical specs, and source development data | No | No as entries; the authorizing ownership-manifest bytes are fingerprinted | Source-only fixtures in the template repository |
| Snapshot-cleanup control | `maintenance-artifacts.json` | No — removed after use | **No** | Source-only fixtures plus runtime agreement with the fingerprinted ownership manifest |

The fingerprint therefore contains only inputs that both generation paths actually retain, which is the
property revision 4 lacked.

`maintenance-artifacts.json` is decoded into an ephemeral `CleanupInventory`; it does not list itself.
The fingerprinted `SourceOwnership.snapshot_cleanup_paths` independently contains the finite set of
paths deletion may target. The pure `CleanupContract` is the exact agreement of those two sources plus
observed path shape and hashes. Any missing, extra, overlapping, unsafe, or mismatching entry returns
`CleanupContractInvalid` and deletes nothing unless the adopter chooses
`--leave-maintenance-artifacts`. Snapshot install removes verified entries, then removes the inventory
itself last. Copier excludes both the entries and inventory statically.

## Bootstrap input bundle

```json
{
  "schema_version": 1,
  "project": {"name": "example", "default_branch": "main"},
  "profile": {"id": "integrated"},
  "content": {
    "prd": {"mode": "file", "path": "content/prd.md"},
    "readme": {"mode": "file", "path": "content/readme.md"},
    "validation_hook": {"mode": "scaffold"},
    "security_policy": {"mode": "scaffold"},
    "contributing": {"mode": "scaffold"}
  },
  "licensing": {"mode": "provided-project-license", "path": "content/license.txt"},
  "capability_settings": {"cachix-publish": {"cache_name": "example"}}
}
```

For `custom`, `profile.capabilities` is mandatory; other profiles reject that field. Project name and
default branch are constrained to explicit ASCII classes. Repository owner and name are absent, because
GitHub exposes repository identity at runtime and persisted slugs go stale after forks, transfers, and
renames.

### Content modes

Each slot takes `{"mode": "file", "path": "..."}` or `{"mode": "scaffold"}`. `scaffold` keeps bootstrap
from being an authoring gate: an adopter selects a profile, compiles real CI, and starts working, while
readiness continues to fail and name the unreplaced slots. This preserves REQ-001.

Licensing has no scaffold mode. A licence file invented by a tool is worse than none.

### Declared placeholder markers

Slot completion is derived from the current files, never from the manifest.

| Slot | Installed path | Marker | Detection |
| --- | --- | --- | --- |
| `readme` | `README.md` | `<!-- agentic-template:placeholder:readme -->` | UTF-8 text search |
| `prd` | `docs/prd.md` | `<!-- agentic-template:placeholder:prd -->` | UTF-8 text search |
| `security_policy` | `SECURITY.md` | `<!-- agentic-template:placeholder:security -->` | UTF-8 text search |
| `contributing` | `CONTRIBUTING.md` | `<!-- agentic-template:placeholder:contributing -->` | UTF-8 text search |
| `validation_hook` | `scripts/validate-project` | `agentic-template:unconfigured:validate-project` | Raw-byte substring search |

The hook sentinel is an ASCII byte substring found in raw bytes, never by decoding, because the hook may
be a compiled binary or use any encoding; requiring decodable UTF-8 would contradict toolchain
neutrality. The four document slots are already required to be valid UTF-8.

`init` and `apply` reject a `file` input containing any declared marker, with
`BOOTSTRAP_INPUT_RESERVED_MARKER`; otherwise adopter content could impersonate a placeholder and
permanently suppress its own readiness finding.

The manifest's `answers.slots` records what was applied. It is consumed only by the `answers` fact and
is never a claim about the current tree, so an adopter replaces a scaffolded file by editing it in
place and nothing transitions.

### Content constraints

README, PRD, SECURITY, `CONTRIBUTING.md`, and supplied legal text must be valid UTF-8. The validation
hook may be any regular executable file, copied byte-for-byte with mode `0755`. Referenced paths are
relative to `bootstrap.json`, must satisfy the path grammar, must remain inside the bundle after
normalization, must be regular files, and may not traverse a symlink.

Licensing modes: `retain-apache-2.0` with no adopter path; `provided-project-license` with required
legal text; `private` with a required private notice.

### Additive capability input

```json
{"schema_version": 1, "add_capabilities": ["nix", "cachix-publish"], "capability_settings": {}}
```

Settings may be supplied only for newly requested capabilities and newly resolved dependencies. A
setting for an existing capability must match the complete persisted normalized value or the operation
fails. The decoder fills deterministic defaults, requires every required setting in the expanded new
closure, and compiles `CapabilityAdditions` containing the explicit requested IDs plus complete settings
for every newly effective capability. It never mutates `InitialAnswers`.

## Profiles and capabilities

| Profile | Snapshot expansion |
| --- | --- |
| `portable` | Core only |
| `release-automated` | `semantic-release` |
| `nix-enabled` | `nix` |
| `integrated` | `semantic-release`, `nix`, `cachix-publish`, `pr-agent-gemini` |
| `custom` | Exact list supplied in `bootstrap.json` |

A capability declares a stable ID and description; dependency IDs; settings typed `string`, `boolean`,
or `enum`; validation constraints for every string used in a structured output context; external
activation requirements; exclusively owned output paths each declared `text` or `binary`; contributions
to named typed slots; document fragments; fixture cases; and, when needed, non-secret runtime dependency
declarations with supported Python range and invocation metadata. Definitions are data: no command
execution, no Python object loading, no network, no environment reads, no arbitrary target paths.
Settings and dependency credentials must be declared non-secret. Bootstrap renders dependency metadata but
does not install packages or execute package setup code.

### Stable-ID compatibility

Within v1 an existing capability ID may update artifacts and documentation but may not silently add or
remove a dependency, remove a setting, change a setting's type or meaning, make an optional setting
required, change external-prerequisite semantics incompatibly, or transfer ownership of an existing
path. Adding an optional setting with a deterministic default is compatible. A frozen fixture records
the v1 surface; `validate-template.py` compares the live catalog against it. A closure change under a
nominally compatible catalog surfaces as `CatalogIncompatible`.

`pr-agent-gemini` encodes the backend in the ID, because changing a setting is reconfiguration, which
v1 does not support; a separate ID per backend keeps "add a new capability" available.

| Capability | Principal managed output | External activation |
| --- | --- | --- |
| `semantic-release` | `.releaserc`, reusable release workflow, gated release job contribution | None beyond normal token permissions |
| `nix` | `flake.nix`, `flake.lock`, Nix setup action, Nix CI check contribution | None |
| `cachix-publish` | Cachix configuration and publish contributions; depends on `nix`; requires a non-secret cache-name setting | Existing cache plus `CACHIX_AUTH_TOKEN`; Cachix work skips when unavailable while Nix continues uncached |
| `pr-agent-gemini` | `.pr_agent.toml`, review and trusted-command workflows, activation preflights, setup documentation | `GEMINI_API_KEY` |

## File ownership

| Class | Members |
| --- | --- |
| Generated-lifecycle source | `source-ownership.json` and its declared public entry points, shared core and shell modules, catalog, render sources including audit-approved legal/provenance blobs, validators, schemas, policy and static contracts; Copier updates and merges these |
| Bootstrap-managed output | Generated-project `pyproject.toml`, with selected capability runtime dependencies added conditionally, compiled CI, selected capability artifacts, durable operational documents; exact hashes enforced; `restore` repairs them |
| Manifest | `.agentic-template/project.json`; transaction-owned primary state, not managed render output, and excluded from `ManagedInventory` |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, `CONTRIBUTING.md`, root `LICENSE`, generated `NOTICE.md`, preserved `LICENSES/Apache-2.0.txt`, and project-validation workflow; installed once, never regenerated in v1 |
| Adopter files | Product code and documentation, `.gitattributes`, `.gitignore`, unrelated workflows, everything outside declared ownership |
| Template-maintenance artifacts | Source-only snapshot-cleanup targets and their ephemeral cleanup control from the input boundary |

No path belongs to two classes; source validation rejects duplicate, nested, and case-colliding
declarations. `CONTRIBUTING.md` and `.gitattributes` are adopter-owned because both are ordinary
adopter configuration. The four `docs/*.md` operational documents are managed because they describe
template mechanics the adopter does not author.

## Generation paths

Copier excludes bootstrap-managed output, seed-once output, source-only snapshot-cleanup targets, and
the cleanup-control inventory.
There is no `_skip_if_exists` hook rule: the canonical extensionless hook is seed-once output, and one
path must not have two ownership mechanisms. Stale excludes matching no declared ownership path are
rejected.

GitHub's template operation copies the source tree unchanged, so initial install replaces seed
placeholders, removes unselected capability artifacts, replaces source CI with compiled CI, removes
source-only snapshot-cleanup targets, and finally removes the cleanup inventory itself.

Recognized scaffold, per path:

- **Copier:** `.copier-answers.yml` present, no manifest, every seed-once path absent or byte-identical
  to the template's scaffold content.
- **GitHub:** no `.copier-answers.yml`, no manifest, and every seed-once path matches the scaffold. Its
  cleanup observation is classified separately as `CleanupContractValid` or
  `CleanupContractMismatch`; the latter remains a recognized scaffold precisely so explicit
  `--leave-maintenance-artifacts` can retain rather than delete the finite declared paths.

Anything else classifies as `UnsupportedTarget`. Cleanup mismatch without the leave option refuses
initial apply and deletes nothing. Unexpected bytes at any seed-once path proposed for replacement
block the whole mutation; bootstrap never treats "looks like a template file" as evidence.

`docs/template-updates.md` states plainly that a GitHub-generated project receives no template updates
to generated-lifecycle source or managed artifacts. V1 provides no conversion into Copier lineage.

## Transaction interpreter

The guarantee is **recoverable planned-path transactionality**: after any ordinary error or supported
crash point, every planned file and directory can be returned to its exact raw pre-operation bytes and
mode, or recovery stops without overwriting a third state and preserves its evidence. Bootstrap does
not claim atomic multi-file visibility or whole-repository rollback.

### Typed operations and identities

```text
PosixMode = Integer(0o0000..0o7777)
InstallFileMode = 0644 | 0755
InstallDirectoryMode = 0755

FileContentIdentity =
  { kind, normalized_sha256, raw_sha256, size }

FileState = FileAbsent | FilePresent(FileContentIdentity, PosixMode)
ObservedFile = FileAbsent | ObservedFilePresent(FileContentIdentity, PosixMode, device, inode)
PlannedFileState = FileAbsent | PlannedFilePresent(FileContentIdentity, InstallFileMode, content_id)

FileOperation = CreateFile | ReplaceFile | DeleteFile
  { path, expected_old: ObservedFile, planned_new: PlannedFileState }

TreeEntry =
    DirectoryEntry(relative_path, PosixMode)
  | FileEntry(relative_path, FileContentIdentity, PosixMode)

DirectoryState =
    DirectoryAbsent
  | EmptyDirectory(PosixMode)
  | MaterializedTree(root_mode: PosixMode, entries: tuple[TreeEntry], raw_tree_sha256)

ObservedDirectory =
    DirectoryAbsent
  | ObservedDirectoryPresent(DirectoryState, device, inode)

PlannedMaterializedTree =
  { identity: MaterializedTree
  , file_content: {relative_path -> content_id} }
  # every file mode is InstallFileMode; every directory mode is InstallDirectoryMode

DirectoryOperation =
    CreateTree {root, expected_old: DirectoryAbsent,
                planned_new: PlannedMaterializedTree}
  | RemoveEmptyDirectory {path,
                          expected_old: ObservedDirectoryPresent(EmptyDirectory),
                          planned_new: DirectoryAbsent}

ObservedPathState = ObservedFile | ObservedDirectory

OperationPlan =
  { plan_schema, operation_kind, target_identity, generation_path
  , source_before, source_after, manifest_before, manifest_after
  , ordered_operations: tuple[FileOperation | DirectoryOperation]
  , blob_store: VerifiedBlobStore
  , gate_specification }

PlanReceipt = erase_bytes(OperationPlan)
  # replaces TargetIdentity with TargetBinding; preserves all other identities, modes, topology,
  # source/manifest binding, and gate specification
  # contains no adopter, legal, generated, or backup bytes

TargetBinding =
  hex(tagged(b"target-binding",
      u64be(len(root_os_bytes)) || root_os_bytes || u64be(device) || u64be(inode)))

PreparationIdentity =
  { transaction_id, operation_index, role: Stage | Backup | Rollback
  , ownership_token_sha256, expected_kind, expected_raw_sha256, expected_mode: PosixMode }
```

Normalized identity is used for managed drift. Raw identity and exact mode are used for transaction
preconditions, backup authentication, and exact rollback. Device and inode exist only on observed old
values to detect replacement between observation and mutation; `content_state(observed)` deliberately
forgets those locators because an atomic restore creates a new inode, while
`planned_state(planned_new)` forgets only blob-store locators. Creates and deletions encode
absence explicitly. A materialized tree identity contains every relative entry, raw file identity, and
exact directory mode in canonical parent-before-child order. The planner expands cleanup directory
trees into explicit file deletions and bottom-up empty-directory removals; it never journals an opaque
recursive delete.

Planned generated files use only `InstallFileMode` and planned directories use only
`InstallDirectoryMode`. Observed pre-state files and directories accept the complete supported
permission/special-bit domain `PosixMode`, and raw backups plus rollback stages preserve that exact
value. File kind is validated separately; no non-regular file becomes representable merely because its
mode integer is in range.

When a new file's parent already exists, its stage is adjacent to that parent. Files under a wholly new
directory hierarchy are staged as one `CreateTree` adjacent to the nearest existing ancestor and the
highest absent directory is installed by one rename. This permits same-filesystem replacement without
creating target parents before `MUTATING`. Directory modes and every contained file are explicit.

### State-root layout

The verified per-worktree administrative path is a directory:

```text
<state-root>/
  lock
  journal.json
  journal.pending                  # transient atomic-write path; never authoritative
  transactions/<transaction-id>/backups/<operation-index>
```

Durable backups live under the Git administrative state and therefore survive `git clean -fdx`.
Same-filesystem staging lives inside a reserved sibling preparation directory under the destination
parent. A staged file or tree can be atomically renamed out of that directory. Each preparation
directory contains an engine marker binding a fresh 256-bit `os.urandom` ownership token to its
`PreparationIdentity`; the journal records only the token hash. Transaction IDs and preparation tokens
are lowercase 256-bit hex values. The journal records every exact staging and backup location and
expected identity before either is created.

Recovery removes preparation only after descriptor-relative validation of the reserved-name derivation,
marker token hash, transaction ID, operation index, role, kind, and expected identity. A marked
preparation may contain a partial child from an interrupted write and is still engine-owned. A missing
stage is an idempotent cleanup no-op—`git clean -fdx` may remove disposable adjacent staging—while
administrative backup absence in `MUTATING` remains `BackupInvalid`. A mismatching marker, an unexpected
child, or a collision is a third state: recovery preserves it and
returns `RecoveryThirdState`. A crash after the exclusive directory create but before its marker may
therefore require manual inspection; it never authorizes deletion of an ambiguous path.

`journal.json` is the only authoritative record. A leftover regular no-follow `journal.pending` is
never removed by status, planning, or an unrelated mutation. When `journal.json` exists, recovery treats
the pending file as an incomplete later journal rewrite and removes it only while following the valid
authoritative phase. When no journal exists and no other transaction artifact exists, it decodes as
`StalePendingWrite`; only `recover` may verify and discard it. Preparation could not legally have begun.
Any other state-root shape is `OrphanTransactionState`, not cleanup.

The shell creates or opens `state-root` descriptor-relatively with mode `0700`, rejects a symlink or
non-directory final component, and performs lock, journal, and backup operations relative to the held
directory descriptor. Unsupported locking, atomic rename, or directory-fsync semantics fail before
mutation; the design does not promise crash durability on filesystems that do not supply them.

### Phases and pure recovery reducer

| Phase | Durable meaning | Target paths possibly changed | Recovery decision |
| --- | --- | --- | --- |
| `PLANNED` | Complete plan and all reserved preparation identities recorded; any subset of marked stages/backups may exist | None | Remove only identity-verified preparation; ambiguity blocks without deletion |
| `MUTATING` | Every required backup verified; installation or rollback may be partial | Any planned path | Apply the idempotent rollback reducer to every operation |
| `RESTORED` | Rollback completed and every planned path was verified at pre-state; cleanup evidence may be partially removed | All planned paths have pre-state | Reverify pre-state and finish rollback cleanup; never reinstall |
| `SEALED` | Candidate installed, post-state verified, and gate passed | All planned paths have candidate state | Finish cleanup forward; never roll back |

Rollback visits operations in the exact reverse of the plan's dependency order, so removed parent
directories are restored before their children and created children disappear before a created parent.
For each file operation, rollback is a total pure function of journaled old/new identity and current
observation:

```text
rollback_file_step(expected_old, planned_new, current) =
    AlreadyRestored
      if content_state(current) == content_state(expected_old)
  | RestoreOldFile
      if content_state(current) == planned_state(planned_new)
  | ThirdState(current)
      otherwise

rollback_directory_step(operation, current) =
    AlreadyRestored
      if directory_state(current) == directory_state(operation.expected_old)
  | RemoveCreatedTreeAtomically
      if operation is CreateTree
         and directory_state(current) == operation.planned_new.identity
  | RestoreEmptyDirectoryAtomically
      if operation is RemoveEmptyDirectory
         and directory_state(current) == DirectoryAbsent
  | ThirdState(current)
      otherwise

sealed_step(planned_new_state, current) =
    AlreadyCandidate  if current == planned_new_state
  | ThirdState(current) otherwise
```

`RestoreOldFile` verifies the raw backup digest and exact mode before use, copies it to a new marked
adjacent rollback preparation, fsyncs it, and atomically replaces the candidate. For an originally
absent file it removes the unchanged planned-new value. `RemoveCreatedTreeAtomically` never recursively
mutates the target tree: after verifying every entry against `MaterializedTree`, it atomically renames
the whole tree into the child of a marked adjacent rollback container and fsyncs both parents. The
target is then durably absent; later cleanup may recursively delete only that identity-proved container.
`RestoreEmptyDirectoryAtomically` builds the exact-mode empty directory inside a marked adjacent
rollback container and renames it into place. A crash before either rename leaves the target candidate;
a crash after it leaves the target restored and an independently recognizable cleanup container, so
the same reducer is idempotent.

Before rollback cleanup, the interpreter persists `RESTORED` only after every reverse-order step returns
`AlreadyRestored` and the complete pre-state is reverified. `RESTORED` recovery repeats that pure
verification but never reapplies a candidate; missing cleanup evidence is legal, while any evidence
that remains must still match its preparation identity.

For `SEALED`, the pure forward reducer visits every operation and requires its complete current file or
directory state to equal the planned candidate. It performs no target mutation. Only after every step
returns `AlreadyCandidate` may cleanup discard stages, verified backups, rollback containers, and the
journal. A third state in any reducer is never overwritten: recovery returns
`RecoveryThirdState`, exits 1, retains the journal and remaining evidence, and names the path. Journal
removal is legal only after every operation observes its phase-specific terminal state.

The interpreter itself is an explicit Mealy-style state machine rather than a procedural function with
hidden branches:

```text
TransactionMachineState =
    NeedLock(CompiledTransaction)
  | NeedRevalidation(LockedTransaction)
  | NeedPlannedJournal(ValidatedLockedTransaction)
  | Preparing(PlannedTransaction, PreparationCursor)
  | NeedMutatingJournal(PlannedTransaction)
  | Installing(MutatingTransaction, OperationCursor)
  | Verifying(MutatingTransaction)
  | RollingBack(MutatingTransaction, RollbackCursor)
  | NeedRestoredJournal(VerifiedRestoredTransaction)
  | NeedSealedJournal(GatedCandidateTransaction)
  | CleaningForward(SealedTransaction, CleanupCursor)
  | CleaningRollback(RestoredTransaction, CleanupCursor)
  | Completed(ExecutionTrace)
  | Stopped(ExecutionTrace, EffectError | TransitionError)

EffectRequest = AcquireLock | ObserveAgain | PersistJournal(JournalPhase) | PrepareOne | ApplyOne
              | ObservePostState | CleanOne | AttemptRollbackOne | ReleaseLock

EffectRequestKind =
    AcquireLockKind | ObserveAgainKind | PersistJournalKind | PrepareOneKind | ApplyOneKind
  | ObservePostStateKind | CleanOneKind | AttemptRollbackOneKind | ReleaseLockKind

JournalPhase = PlannedPhase | MutatingPhase | RestoredPhase | SealedPhase
RollbackEffectResult = RollbackAlreadyRestored | RollbackRestoredNow

EffectObservation =
    LockAcquired
  | LockRefused(TransitionError(LockHeld))
  | Reobserved(TargetSnapshot)
  | JournalPersisted(JournalPhase)
  | PreparationCompleted(PreparationIdentity)
  | OperationApplied(operation_index, ObservedPathState)
  | PostStateObserved(TargetSnapshot)
  | CleanupCompleted(cleanup_index)
  | RollbackStepCompleted(operation_index, RollbackEffectResult)
  | LockReleased
  | EffectFailed(EffectRequestKind, EffectError)

TransactionEvent = Start | ObservedEffect(EffectObservation)

step_transaction : TransactionMachineState × TransactionEvent
                -> TransactionInstruction(EffectRequest, TransactionMachineState)
                 | TransactionTerminal(Completed | Stopped)
```

Each nonterminal constructor admits exactly the effect requests shown by the transition table tested in
batch 5; only `NeedLock` accepts `Start`, and an effect observation is accepted only by the continuation
that requested it. The continuation also requires the observation constructor and index belonging to
that request; a mismatched success observation is `InternalFailure`, not an ignored event. `EffectFailed`
uses the exact request kind and the already closed `EffectError` family. The shell loop
executes one `EffectRequest`, converts every ordinary OS result into a typed `EffectObservation`, and
feeds it back. It never selects a phase, rollback direction, gate outcome, or next operation itself.
ty exhaustiveness plus Hypothesis stateful traces cover every constructor and every
`TransactionPrimitiveFailed` branch.

The journal transitions are therefore states rather than interpreter conditionals:
`NeedPlannedJournal --PlannedPhase--> Preparing`,
`NeedMutatingJournal --MutatingPhase--> Installing`,
`NeedRestoredJournal --RestoredPhase--> CleaningRollback`, and
`NeedSealedJournal --SealedPhase--> CleaningForward`. `Verifying` may enter
`NeedSealedJournal` only on gate pass; every refusal enters `RollingBack`, whose only successful terminal
transition is `NeedRestoredJournal`. No shell callback selects one of these edges.

### Interpreter ordering

1. Acquire the canonical lock.
2. Re-observe and re-decide under the lock; require the same plan and target identity.
3. Allocate an unpredictable 256-bit transaction ID plus independent 256-bit ownership tokens and
   derive every reserved path and `PreparationIdentity`.
4. Persist the complete `PLANNED` journal through the fixed engine-owned `journal.pending` path by
   exclusive no-follow create, file fsync, rename to `journal.json`, and state-root fsync.
5. Create any subset of recorded preparation directories and administrative backup containers with
   exclusive, no-follow opens; write and fsync the ownership marker before child content; then create,
   write, and fsync the child. Fsync every affected parent. Verify every backup's raw digest and mode.
6. Advance atomically to `MUTATING` and fsync the state root.
7. Re-resolve each parent, verify the exact old raw identity, apply operations in plan order, and fsync
   every file and affected parent directory.
8. Observe the post-state, verify the complete plan, evaluate template contract and readiness through
   the pure core, then evaluate `gate`.
9. On any pre-seal failure, execute the rollback reducer. Preserve `MUTATING` evidence if rollback is
   incomplete; after complete pre-state verification, persist and fsync `RESTORED` before removing any
   backup or rollback preparation, then finish cleanup and remove the journal last.
10. On gate pass, atomically advance to `SEALED` and fsync the state root.
11. Remove adjacent stages and fsync their parents; remove administrative backups and transaction
    directory; remove `journal.json` **last** and fsync the state root; release the lock.
12. For commands whose decision requests it, attempt the adopter hook and report point-in-time evidence.

A crash after step 4 always has a journal naming every possible preparation file. Before step 4 only a
partial `journal.pending` may exist; with no final journal it is safe for `recover` to remove after
verifying that exact state-root path is a regular no-follow file, because preparation has not begun. Any
staging or transaction entry found without a final journal is an invariant violation: the shell preserves it, refuses mutation with
`BOOTSTRAP_TRANSACTION_ORPHAN_UNKNOWN`, and gives a bounded manual inspection action. It never guesses
that an unjournaled path is safe to delete.

### Lock and state resolution

`state-root/lock` is a never-unlinked regular file opened `O_CREAT | O_RDWR | O_NOFOLLOW`, without
`O_EXCL`, then acquired with nonblocking `flock`. Every mutating command and `recover` holds it from
observation through cleanup. PID, operation, and target identity are informational lock contents;
flock ownership is authoritative. A dead process releases the flock, so its existing inode is reused.

State resolution is exactly:

1. Try `git -C <verified-target> rev-parse --path-format=absolute --git-path agentic-template`.
2. If and only if Git reports that `--path-format` is unsupported, retry
   `git -C <verified-target> rev-parse --git-path agentic-template` and resolve a relative result against
   the verified worktree root.
3. Independently obtain `git -C <verified-target> rev-parse --absolute-git-dir`, resolve it without
   following symlinks, and require the state-root result to equal its `agentic-template` child.
4. Re-verify both paths descriptor-relatively. Every other Git error is a typed target error.

Linked worktrees therefore have independent state roots; a submodule uses its own administrative path;
bare repositories, non-worktrees, and unavailable Git are unsupported. Target identity is the verified
absolute worktree root plus its device and inode. A mismatch makes automatic recovery unavailable and
preserves the journal.

### Path safety and threat model

Every staging, replacement, backup read, and rollback is anchored to a held verified root or state-root
descriptor. The shell walks every component with `dir_fd`, `O_DIRECTORY`, and `O_NOFOLLOW`; opens files
with `O_NOFOLLOW`; rejects non-regular files and files with link count other than one; re-resolves the
parent immediately before mutation; and verifies device, inode, raw
hash, and exact mode against the plan. A mismatch returns a typed trace step and triggers rollback once
`MUTATING`.

These measures defend against accidental symlinks, stale plans, concurrent bootstrap commands, and
interrupted operations. They do not defend against a local adversary concurrently mutating the same
target with the same privileges. A malicious template distribution is also outside v1's trust model;
signed release provenance remains future work. Pre-existing malformed state and accidental local
modification remain in scope and fail closed.

## Restore, add, and reconcile

### `restore`

The intent-specific decision requires:

- a supported target with no journal; the shell acquires the lock and re-observes before interpretation;
- the manifest parses, its schema is known, and its checksum verifies;
- topology is safe;
- a `CopierSourceSame` or `SnapshotSourceSame` condition; a Copier update names reconcile, while a snapshot source modification names the exact
  baseline-commit repair or regeneration action;
- the recorded closure resolves exactly against the current catalog;
- every requested path appears in `ManagedInventory`; and
- for every requested path, the re-rendered `{kind, sha256, mode}` equals its recorded entry.

The last precondition is the safety property: restore writes only bytes the requested inventory
projection already certifies and records nothing. It may leave unrelated pre-existing drift. A
mismatch is `BOOTSTRAP_RENDER_CONTRACT`, exit 2.

`restore --path` is refused when a named path is not managed, and touches no seed-once or adopter path.

### `add`

Requires `CopierSourceSame` or `SnapshotSourceSame`, a resolvable closure, verified managed output, and
no journal. It first renders
the recorded selection and requires complete equality with `ManagedInventory`; only then does it extend
`CapabilityAdditions.requested`, resolves again, validates and stores complete normalized settings for
every newly effective capability, and renders the expanded selection. The candidate may legitimately
update shared contribution outputs. It advances only `CapabilityAdditions` and managed inventory.
Existing settings must match; removal, replacement, and reconfiguration requests return typed
unsupported-lifecycle errors.

### `reconcile`

Available only on the Copier path. Separated into five stages, so no stage depends on bytes that are no
longer available:

1. **Verify the old contract.** Manifest parses, schema known, checksum verifies, managed inventory verified
   against observed bytes — or drift explicitly accepted, below.
2. **Recognize the new source.** Compute the current source inventory and fingerprint; require the
   recorded closure to remain resolvable without adding or removing an ID.
3. **Compile candidate output.** Render from the new template plus recorded `InitialAnswers` and
   `CapabilityAdditions`.
4. **Apply drift policy.** Blocked on drift unless `--overwrite-drift` with a valid plan digest.
5. **Accept.** Install, gate, and record the new source baseline and managed inventory.

Nothing in this sequence reads old source bytes. It may not re-expand a profile, change
`InitialAnswers` or `CapabilityAdditions`, modify seed-once or adopter paths, select a template version,
merge drift, or perform
ownership transfer.

### Drift policy by operation

| Operation | With managed drift present |
| --- | --- |
| `status` | Reports it; never blocked |
| `plan apply`, `plan add` | Refuse with exit 1 and the `restore` next action; no executable plan exists |
| `plan restore` | Produces the exact repair plan |
| `plan reconcile` | Refuses unless source changed and `--overwrite-drift` was explicit; that form produces the destructive receipt |
| `recover` | Proceeds; it restores planned paths regardless |
| `apply` | `ManagedDrift`; next action `restore` |
| `add` | Blocked; next action `restore` |
| `restore` | Its purpose |
| `reconcile` | Blocked unless `--overwrite-drift` with a valid plan digest |

## Plan digest

`reconcile --overwrite-drift` destroys adopter edits to managed files, so it is bound to the preview
that authorized it. There is no interactive confirmation path, so the contract is identical in a
terminal and in automation.

`plan reconcile --overwrite-drift --out FILE` writes the canonical `PlanReceipt`, never the in-memory
plan's file bytes. Its digest therefore binds operation kind; the non-reversible target binding;
generation path; source baseline before and after;
manifest checksum before and after; gate specification; and every ordered operation's path, operation
kind, file kind, normalized and raw old/new hashes, modes, absence, and directory topology, plus

```text
plan_digest = tagged(b"reconcile-plan", canonical_json(plan_receipt_without_digest))
```

`reconcile --overwrite-drift --plan FILE` strictly decodes the receipt and recomputes its digest,
rejecting any mismatch; verifies the target identity; recompiles the full byte-carrying plan from current
state; erases its bytes; requires exact receipt equality; and only then proceeds. `--overwrite-drift`
without `--plan` is a usage error. The serialized `TargetBinding` is re-derived from the verified
current target; the absolute root remains only in the in-memory plan and journal. No plan file contains
an absolute machine path, adopter prose, or legal prose.

## The adopter hook

The hook is adopter-owned, may be any executable, and is invoked directly rather than through Python.

**Invocation rule.** The shell attempts the hook at most once per uninterrupted command invocation,
only after a mutating command has gated and removed its journal, or after successful equivalent
verification. It makes zero attempts on refusal, rollback, `recover`, planning, status, or init.
Exactly-once execution across a process crash is neither promised nor implementable for an arbitrary
external executable. Recovery never invokes or replays the hook. Because journal cleanup precedes the
hook and hook evidence is not persisted, a later invocation cannot distinguish a crash before, during,
or after the hook. No command claims that distinction: `status` and the installed documentation always
name the canonical validator as the way to establish new point-in-time readiness evidence.

`HookExited(0, streams)` is hook success. A normal nonzero status, `HookSignalled`, or
`HookLaunchFailed` is a hook failure and produces exit 1 with the installation retained, reported as
"bootstrap files were installed; the repository is not locally ready". Signal evidence records the
positive signal number; launch evidence contains only a closed process-error reason, never an exception
representation.

```text
project_readiness(mechanical, hook) =
    Ready(mechanical, hook)       if mechanical has no blocking finding and hook is HookExited(0, _)
  | NotReady(mechanical, hook, reasons) otherwise
```

This is the only value called `ProjectReadinessOutcome`. The transaction gate consumes only
`MechanicalReadinessResult`; an empty mechanical finding set never implies that the hook ran. Hook
evidence is **point-in-time evidence**: never written to the manifest, never cached, never replayed.
`status` does not execute it and claims no outcome, reporting mechanical readiness and then
`adopter hook: not evaluated; run python3 scripts/validate-repository.py`.

## CLI contract

```text
python3 scripts/bootstrap-project.py [global-output-options] init
    --output PATH [--from FILE | --interactive]

python3 scripts/bootstrap-project.py [global-output-options] status [--target PATH]

python3 scripts/bootstrap-project.py [global-output-options] plan apply
    --bundle PATH [--target PATH] [--leave-maintenance-artifacts] [--out FILE]
python3 scripts/bootstrap-project.py [global-output-options] plan add
    --input FILE [--target PATH] [--out FILE]
python3 scripts/bootstrap-project.py [global-output-options] plan restore
    [--path PATH]... [--target PATH] [--out FILE]
python3 scripts/bootstrap-project.py [global-output-options] plan reconcile
    [--target PATH] [--overwrite-drift] [--out FILE]

python3 scripts/bootstrap-project.py [global-output-options] apply
    --bundle PATH [--target PATH] [--leave-maintenance-artifacts]
python3 scripts/bootstrap-project.py [global-output-options] add
    --input FILE [--target PATH]
python3 scripts/bootstrap-project.py [global-output-options] restore
    [--path PATH]... [--target PATH]
python3 scripts/bootstrap-project.py [global-output-options] reconcile
    [--target PATH] [--overwrite-drift --plan FILE]
python3 scripts/bootstrap-project.py [global-output-options] recover [--target PATH]

global-output-options :=
    [--format text|json] [--color auto|always|never] [--explain] [--quiet]
```

`--target` is accepted by every command that inspects or mutates a project; `init` accepts none. There
is no `--state-dir`: state location is a pure function of the verified target.

Commands are thin adapters. Parsing returns one `Intent` variant; the total transition algebra decides
what that intent permits. The parser has no callbacks that mutate state and no command catches a domain
error merely to reinterpret it.

`init` writes a complete reviewable bundle, using a temporary sibling and installing only after
validation.

`status` reports generation path, frozen profile, additions, effective closure, unreplaced slots derived
from file markers, every drifted managed and source path, recorded and current source fingerprints, maintenance status
with retained paths, activation requirements, and any pending journal. It does not acquire or probe the
live transaction lock: a lock observation would be race-prone rather than durable lifecycle state, and
the next mutating command reports `LockHeld` if acquisition actually fails.

Argument invariants are decoded before target observation:

- `init` requires exactly one of `--from` or `--interactive`; interactive mode requires a TTY and text
  presentation and is the only command that prompts;
- `--target` defaults to the invocation's current directory after absolute worktree verification; no
  environment variable or saved setting changes it;
- restore with no `--path` selects every currently drifted managed path; repeated paths are rejected
  after canonicalization rather than silently deduplicated;
- `--overwrite-drift` is legal only for reconcile planning or with a matching `--plan` receipt during
  reconcile; there is no interactive confirmation fallback;
- `--out` uses exclusive sibling staging and refuses an existing destination or `-`; without `--out`,
  JSON presentation carries the canonical receipt inside the command envelope; and
- JSON presentation rejects color and interactive options, always emits its envelope, and therefore
  rejects `--quiet`; `--explain` is legal and adds the typed decision trace.

`--leave-maintenance-artifacts` is the supported override for a cleanup inventory that no longer
matches. It skips every cleanup deletion. Retained paths are derived from fingerprinted
`SourceOwnership.snapshot_cleanup_paths` plus the inventory path itself when present, never from untrusted
extra inventory entries. It records those retained paths and transfers them to adopter ownership; no
later cleanup command exists, because bootstrap may not later remove adopter-owned files. Readiness reports the
skip as `informational`. The outcome enters `RenderInput`, so it also changes what the documentation
says.

### Rich deterministic presentation

Default text output is concise and human-oriented: command outcome first, then ordered changes or
findings, then exactly one reachable next action per actionable diagnostic. ANSI styling is presentation
only, disabled when non-TTY or `NO_COLOR` is present, and never changes words or ordering. `--quiet`
suppresses successful prose but never errors. `--explain` adds the decoded state constructor, decision
constructor, failed/satisfied preconditions, and prospective state without exposing secrets, absolute
machine paths, or Python representations.

`--format json` emits exactly one canonical JSON `CommandEnvelope` on stdout and no decorative stderr:

```text
CommandEnvelope =
  { schema_version, command, outcome_class, exit_code
  , state, decision, changes, findings, diagnostics, hook_evidence }
```

Every field has a closed schema; absent concepts use tagged variants rather than null-filled records.
Text and JSON are two pure renderers of the same `CommandOutcome`, and golden tests prove semantic
parity. Plan files always use canonical JSON regardless of presentation format.

### Exit semantics by command family

One global rule contradicted `status`, so semantics are defined per family.

| Family | Commands | 0 | 1 | 2 |
| --- | --- | --- | --- | --- |
| Mutating | `apply`, `add`, `restore`, `reconcile` | The requested transition installed and the point-in-time canonical validation succeeded | User-correctable refusal, unmet precondition, expected scaffold, or installed-but-not-ready hook result | Usage/input, contract, manifest, render-contract, transaction, or internal failure |
| Recovery | `recover` | No journal existed, or the phase-specific recovery completed and verified | Automatic recovery is blocked by a target mismatch or third state; evidence retained | Invalid journal/evidence, usage, or internal failure |
| Inspection | `status` | A valid decodable supported or unsupported state was described | *Never returned* | Invalid/unreadable state root, journal, manifest, observation, or internal state; structured evidence is still shown |
| Planning | `plan apply`, `plan add`, `plan restore`, `plan reconcile` | A plan was produced, including an empty one | Preconditions unmet, so no plan exists | Usage, contract, or internal |
| Bundle | `init` | Bundle written | Valid input but output location non-empty | Usage, input/schema/path/marker/digest, observation, or internal failure |

## Diagnostics

```text
BOOTSTRAP_INPUT_*      BOOTSTRAP_TARGET_*      BOOTSTRAP_TRANSACTION_*   BOOTSTRAP_LICENSE_*
BOOTSTRAP_PROFILE_*    BOOTSTRAP_TEMPLATE_*    BOOTSTRAP_RECOVERY_*      BOOTSTRAP_MANIFEST_*
BOOTSTRAP_CAPABILITY_* BOOTSTRAP_DRIFT_*       BOOTSTRAP_ACTIVATION_*    BOOTSTRAP_RENDER_*
BOOTSTRAP_LOCK_*       BOOTSTRAP_INTERNAL_*

Diagnostic =
  { code, category, severity, subject, summary, details, next_action }

NextAction =
    RunCommand(CommandInvocation)
  | EditPath(RelativePath, Instruction)
  | RestoreSnapshotSource(CommitId, tuple[RelativePath])
  | ResolveCopierConflicts(tuple[RelativePath])
  | RegenerateProject(Instruction)
  | ReportTemplateDefect(Instruction)
  | NoAutomaticAction(Instruction)

OutcomeClass =
    Succeeded          # exit 0
  | ActionRequired     # exit 1
  | InvalidRequest     # exit 2
  | ContractFailure    # exit 2
  | RecoveryFailure    # exit 2
  | InternalFailure    # exit 2
```

Outcome mapping is normative:

- `Succeeded`: requested transition or inspection completed, including idempotent recover with no
  journal;
- `ActionRequired`: a valid, non-corrupt state needs adopter action—unreplaced scaffold, hook failure,
  input delta, managed/source drift, Copier conflict, valid pending journal, unsupported greenfield target, held lock, or a
  recovery third-state/target mismatch whose evidence remains valid;
- `InvalidRequest`: CLI usage, input schema, path, marker, or supplied-digest error;
- `ContractFailure`: invalid manifest/template/catalog/cleanup/render contract or an observation that
  prevents trustworthy decoding;
- `RecoveryFailure`: invalid journal/state-root shape, invalid/missing backup evidence, preparation
  whose ownership cannot be proved, or transaction primitive failure; and
- `InternalFailure`: an impossible core case or unclassified exception at the outer boundary.

The command-family table controls the few context-sensitive cases above; no individual adapter chooses
an exit code independently.

Every user-correctable diagnostic names the affected input, capability, or repository-relative path and
one typed next action. The text presenter renders it as a command or instruction only at the edge.
**Every next action must exist and be reachable for the observed generation path and evidence**; a
source fixture enumerates the transition and diagnostic algebras and executes or validates every
machine-actionable variant. Snapshot repair is emitted only with a verified recorded commit; otherwise
the action is regeneration, never an ineffective plain `git restore`.

Diagnostics never include secrets, supplied prose, environment values, absolute machine paths, raw
exception representations, or unbounded subprocess output. Independent decode and preflight errors are
accumulated applicatively where checks are independent and sorted normatively. Decision, mutation, and
recovery stop at the first failure where continuing could mutate state or destroy evidence.

## Users and workflows

### US-1: Prepare a reviewable input bundle

- `init` supports interactive collection and a pre-seeded non-interactive input, and accepts no
  `--target`.
- It requires explicit profile selection, an explicit decision for every content slot, and an explicit
  licensing decision with no default and no scaffold.
- It copies referenced bytes into a self-contained bundle with relative references.
- It rejects a `file` input containing any declared placeholder marker.
- It mutates no project and performs no external operation.
- It refuses a non-empty output location.

### US-2: Bootstrap a generated project deterministically

- `plan apply` reports the exact file and directory operations without mutation.
- `apply` installs only from a scaffold recognized for the target's generation path. An arbitrary empty
  or populated manifest-free target is an unsupported greenfield state whose only v1 next action is a
  fresh scaffold generated through GitHub or Copier; no legacy or adoption path is named.
- Gating requires the shared pure template-contract rules to succeed, every planned artifact to verify exactly, and the
  observed blocking findings to equal exactly those predicted for declared `scaffold` slots.
- The hook is attempted at most once after a gated installation; neither its failure nor an expected
  scaffold finding rolls back.
- Exit 0 only when the complete canonical command would succeed, so any `scaffold` slot yields exit 1
  naming the remaining slots.
- An `EquivalentVerification` from `apply` changes no file, still runs the mechanical-readiness boundary
  and attempts the hook once, and carries the same exit meaning — so an all-`scaffold` equivalent
  `apply` also exits 1.
- Any exit-1 outcome after installation states that files were installed and the project is not yet
  locally ready.
- The hook is installed at `scripts/validate-project` with mode `0755`.
- The result does not depend on Nix unless `nix` is selected.
- Every decision names a next action reachable for the generation path.

### US-3: Select an intent-based snapshot profile

- V1 defines `portable`, `release-automated`, `nix-enabled`, `integrated`, `custom`.
- A named profile expands once; the expansion is persisted as `answers.profile.requested`.
- `custom` requires an exact list.
- No operation re-expands a stored profile name.
- A profile definition change affects only later bootstraps.

### US-4: Materialize only the effective capabilities

- Each profile selects exactly its documented set; `cachix-publish` resolves `nix`.
- Unselected capability artifacts and CI jobs are absent.
- Cycles, output collisions, unknown settings, and undeclared ownership fail before mutation.

### US-5: Preserve product, licensing, and provenance ownership

- README, PRD, hook, SECURITY, `CONTRIBUTING.md`, root licence, and the project-validation workflow
  become adopter-owned after installation.
- The manifest holds normalized state and digests, and no legal prose.
- Licensing is mandatory and explicit; the supplied bytes are covered by `answers.licensing.content_sha256`.
- Bootstrap authors no legal terms and makes no validity claim.
- Apache-2.0 text and bundled-skill provenance remain available in every mode.
- The audit completes before any licence-writing implementation, for every mode.

### US-6: Add capabilities without changing profile provenance

- `plan add` previews; `add` applies transactionally.
- Dependencies resolve into the closure; requested additions and all newly introduced normalized
  settings are recorded separately from immutable initial answers.
- The frozen profile expansion is unchanged.
- Existing settings cannot change; a satisfied request is a no-op only when settings do not conflict.
- Removal or replacement fails naming the deferred lifecycle.
- `add` requires an unchanged source baseline and drift-free managed output. It verifies the complete
  old managed render before compiling the expanded selection, and updates only
  `CapabilityAdditions`—explicit IDs plus complete normalized new settings—and `ManagedInventory`.

### US-7: Configure external integrations without secrets

- Bootstrap never accepts or persists secret values; the manifest records requirements, not status.
- Missing secrets produce successful skips with actionable summaries.
- A read-only preflight determines availability before any write-permissioned job starts.
- The preflight is a fixed trusted job with no checkout, no third-party actions, no repository scripts,
  no untrusted expressions, no shell tracing, and no secret-bearing persisted output.
- Its only outputs are a literal availability boolean and constant guidance.
- It reports availability, or unavailability with likely causes for the event type, and never claims to
  know whether a secret is configured.

### US-8: Reconcile derived artifacts after Copier update

- The sequence is `copier update`, `plan reconcile`, `reconcile`, canonical validation.
- Copier selects and merges inputs; reconciliation compiles derived outputs.
- The closure and settings are preserved exactly.
- `reconcile` is the only operation that advances `SourceBaseline`, per the
  operation-semantics table.
- It adds and removes no capability, changes no setting, re-expands no profile, and merges no file.
- Copier conflict evidence or an incompatible catalog blocks all writes.
- Drift blocks it unless `--overwrite-drift` is given with the digest from
  `plan reconcile --overwrite-drift`, which `reconcile` revalidates.
- **`reconcile` is unavailable on the GitHub path.** A snapshot source delta names exact paths and uses
  targeted restore from the verified recorded commit when reachable; otherwise it names regeneration.

### US-9: Extend the capability catalog declaratively

- A capability declares dependencies, settings, external requirements, owned artifacts with declared
  kind, contributions, document fragments, and fixtures.
- Definitions execute nothing; settings are declared non-secret.
- A new compatible capability requires no capability-specific branch in the resolver, renderer, or
  transaction shell.
- Source validation checks every catalog entry, including unselected ones.
- Compatibility fixtures reject breaking changes to stable IDs, and the readiness-rule baseline rejects
  new unsatisfiable obligations.

### US-10: Retain durable adopter documentation

- Bootstrap produces `docs/delivery-workflow.md`, `docs/template-updates.md`, `docs/capabilities.md`,
  and `docs/github-setup.md`.
- Their fragment bodies and the retained-path list are part of `RenderInput`.
- Additions and reconciliation update them in the same recoverable planned-path transaction as code and
  workflow artifacts.
- Direct edits are drift, reported by `status` and readiness, repaired by `restore`.
- Each header names the document managed and points to `CONTRIBUTING.md` and the README.

### US-11: Extend project validation without editing managed CI

- Bootstrap seeds `.github/workflows/project-validation.yml`, then treats it as adopter-owned.
- Its initial form exposes `workflow_call` and runs `python3 scripts/validate-repository.py`.
- Managed CI calls it as a stable `Project validation` job, passing no secrets, granting
  `contents: read`, and waiting for the complete called workflow.
- Selected release automation depends on it and on all selected managed checks.
- The readiness checker performs bounded standard-library structural and security-policy checks and does
  not claim to be a YAML semantic validator.

### US-12: Recover interrupted mutations

- Every mutation and `recover` acquire the same per-target lock before staging.
- The journal is written and fsynced in `PLANNED` before any replacement, and every transition is an
  atomic replacement.
- The journal records target identity, typed file/directory operations, normalized drift identity,
  raw old/new hashes, exact pre-operation mode, backup identity, and absent sides explicitly.
- Recovery is phase-dependent: `PLANNED` discards staging, `MUTATING` rolls back, `RESTORED` verifies
  pre-state and finishes rollback cleanup, and `SEALED` verifies candidate state and finishes installed
  cleanup. No phase both rolls back and preserves the candidate.
- A gating failure rolls back immediately, before cleanup and before the hook.
- A pending journal blocks later mutations; `recover` refuses a mismatched target identity.
- Recovery evidence survives `git clean -fdx`.
- A live writer cannot race recovery and two recoveries cannot race.
- Hook-created artifacts outside the planned set are not removed.
- The guarantee is recoverable planned-path transactionality, not atomic multi-file visibility.

### US-13: Resolve managed drift

- `status` reports every drifted managed path without mutation and without executing the hook.
- `plan restore` shows exact paths, kinds, modes, and old/new hashes; `restore` applies transactionally.
- `restore` requires a `CopierSourceSame` or `SnapshotSourceSame` condition and every requested
  re-rendered artifact to equal its recorded managed
  inventory entry.
- `restore` records nothing and touches no seed-once or adopter path.
- A Copier source mismatch names `reconcile`; a snapshot mismatch names baseline repair or regeneration;
  a requested render/inventory mismatch is `BOOTSTRAP_RENDER_CONTRACT`.
- `restore --path` restores a subset and cannot change any recorded field.
- Drift blocks neither `status`, `plan restore`, an explicitly destructive changed-source
  `plan reconcile --overwrite-drift`, nor `recover`; it correctly prevents unrelated plan commands from
  claiming an executable candidate.

## Decision record

| Topic | V1 decision | Future change, if viable |
| --- | --- | --- |
| Recorded identity | Answers as values; path-level source and managed inventories; one aggregate source fingerprint; no render identity | None; explicit values are the simplification |
| Render oracle | Operation-specific projections of `ManagedInventory` | None |
| Classification | Staged legal-state sums and total intent-specific transitions | None |
| Script architecture | Shared immutable functional core with thin imperative entry points and typed outcomes | A hermetic executable may justify selected runtime libraries later |
| Bootstrap result | Installation and locally ready reported separately; exit 0 requires both | Staged readiness reporting |
| Content completeness | Adopter file or explicit `scaffold` | Inline prose fields |
| Slot completion | Derived from declared markers | Structured metadata if derivation fails |
| Hook sentinel | Byte-level detection | Declarative command hooks |
| Profile semantics | One-time snapshots | Live profiles or override policies |
| Lifecycle | Install, additive change, same-contract repair, Copier reconciliation | Removal, replacement, reconfiguration |
| Destructive reconciliation | Bound to a recomputed plan digest | None |
| Gating | Scoped to introduced findings; exact scaffold equality on install | Opt-in strict mode gating on the hook |
| Hook evidence | Point-in-time; never persisted or replayed | Cached evidence with explicit invalidation |
| Template evolution | Compatible v1 updates may not add unsatisfiable obligations | A separately approved future lifecycle with preview and ownership transfer |
| Target | A git working tree is required | Reinstate non-git targets with a state-namespacing rule |
| Path safety | Root-anchored no-follow walk; narrow threat model | Platform-specific hardening |
| Snapshot updates | None, including local reconciliation | A separately designed conversion only if a real adopter need emerges |
| Populated manifest-free projects | Unsupported; no legacy population or compatibility release exists | Adoption only after a concrete non-legacy use case is approved |
| Secret diagnosis | Available, or unavailable with likely causes | Authoritative diagnosis in a GitHub doctor |
| Licensing | Explicit; digest fingerprinted; audit gates all modes | SPDX, SBOM, richer automation |
| Workflow validation | Shared pure bounded checks in the generated project; a real parser only in source fixtures | A portable structured parser |
| Dependencies | uv-managed source and generated-project dependencies; pinned ty, pytest, Hypothesis, Ruff, and PyYAML for source assurance | Hermetic distribution, dependency provenance, and the same core/shell conformance suite |
| Delivery | One public release; integration branch, one activation merge | Independent lifecycle releases |

## GitHub workflow architecture

### Project-validation boundary

Managed CI calls `.github/workflows/project-validation.yml` as a stable `Project validation` job,
declaring `contents: read`, passing no named or inherited secrets, and using no privileged environment.
The seeded adopter workflow declares `on.workflow_call`, checks out without persisted credentials, runs
on the supported GitHub-hosted runner, invokes `python3 scripts/validate-repository.py`, and uses no
secret and no write-capable permission.

Adopters may add jobs, matrices, and toolchain setup inside it. GitHub constrains reusable-workflow
permissions so they can be maintained or reduced through the call chain, not elevated.

### Secret-dependent capability jobs

A read-only preflight determines availability; a privileged job starts only when preflight returned
available and normal event trust conditions pass.

The preflight is a **fixed trusted job**: no `actions/checkout` and no repository content; no `uses:`
at all; no repository script execution; no untrusted expression interpolation, so event data is never
inlined; no `set -x` or command echoing; the secret referenced exactly once, compared for emptiness,
and never printed, written, or placed in an artifact; and only a literal boolean `available` plus
constant guidance as outputs.

| State | Condition | Guidance |
| --- | --- | --- |
| Available | The secret resolves non-empty | Proceed |
| Unavailable in this run | Anything else | Constant text listing likely causes for the event type, linking `docs/github-setup.md` |

Two states, not three. An empty secret cannot prove "not configured": GitHub withholds Actions secrets
from fork pull requests and from Dependabot-triggered runs, policy can restrict them further, and a
configured secret may legitimately be empty. Authoritative diagnosis belongs to the proposed doctor.

Two tests protect this: a **structural policy test** asserting no checkout, no `uses:`, no repository
path reference, no untrusted expression, no tracing, and exactly one secret reference; and a **local
canary** that runs the preflight script outside GitHub with a non-secret sentinel and asserts the
sentinel appears in no stdout, stderr, step output, job output, summary, or written file. The canary
must run locally, because GitHub masks registered secret values in logs, which makes log absence
inside Actions near-vacuous evidence.

The PR Agent review and trusted-comment workflows apply this to `GEMINI_API_KEY`. The Cachix path skips
Cachix-specific setup and publishing when `CACHIX_AUTH_TOKEN` is unavailable, letting Nix validation
continue uncached; when available, publishing is additionally gated on the default-branch event and
successful validation, and an invalid configured cache fails as an activation error rather than silently
disabling Nix validation.

### Release graph

With `semantic-release` selected, release runs only on the configured default branch after the complete
adopter project-validation workflow, every selected managed capability check, and any core
delivery-contract job the generated graph requires. The release job retains its last-moment branch-tip
eligibility check. Without `semantic-release`, no release workflow or job is emitted.

### Template-source CI conformance

The template source is effectively an `integrated`-profile project, and its hand-written
`.github/workflows/ci.yml` will drift from the compiled render. A source-only fixture renders
`integrated` CI and compares it with the source workflow under a defined normalization.

**Workflow and graph normal form:** workflow name; trigger events and filters, preserving the distinction
between scalar, list, mapping, and invalid/null forms; `workflow_call` inputs, outputs, and secrets;
top-level `env`, permissions, `defaults.run`, concurrency group, and cancel-in-progress; job IDs with
sorted `needs`; effective per-job permissions and environment after workflow defaults; job-level `env`,
outputs, defaults, strategy including matrix/fail-fast/max-parallel, `uses`, complete called-workflow
`with` and `secrets` including `inherit`, `runs-on`, container and services, `if`, timeout, and
continue-on-error. Matrices are also expanded into the concrete generated job set for graph comparison.

**Step normal form**, with stable identity and order: each step's identity is its zero-based index
within its job plus its `name` when present, and steps compare in that order. For a `uses` step: the
action reference and its 40-character SHA where present, and the
**complete canonical `with` map**. For a `run` step: the shell and a stable hash of the command text
after normalizing line endings and stripping trailing whitespace. For both: `if`, the **complete
canonical `env` map including values**, `working-directory`, `timeout-minutes`, and
`continue-on-error`. Presentation-only `name` participates in stable step identity but does not replace
the zero-based position.

Because `SafeLoader` discards comments, action tag comments are checked by a separate raw-source lexical
fixture that binds each comment to the immediately preceding immutable action SHA. Comments are not
claimed to exist in the semantic YAML normal form.

Revision 4 compared only `env` key names and five security-relevant `with` keys, which permits
security-relevant drift while conformance stays green.

**Trust predicates.** For every job that holds a write permission or reads a secret, the fixture
asserts the exact expected event and actor predicate — event name, `github.event.pull_request.head.repo.fork`
where applicable, association requirements for comment-triggered jobs, and the branch condition for
publishing jobs. A privileged job whose predicate differs from its declared expectation fails.

**Allowlist.** Source-only differences are permitted only through explicit entries in
`.agentic-template/source-ci-allowlist.json`, each carrying the job or step identity, the reason, an
owner, and a review-by date. The fixture fails on an uncovered difference and on an entry that no
longer corresponds to a real difference. Self-expiry removes **stale** entries; it does not prevent
accumulation of genuine differences. The fixture reports the current entry count so growth is visible
and attributable.

**Parser.** This source-only fixture uses PyYAML from the pinned uv development environment established
in batch 1. Generated-project runtime may use declared uv-managed dependencies; this source-CI parser is
not automatically part of that runtime contract.

The loader contract is specified, because default PyYAML semantics are not GitHub Actions semantics:
`yaml.SafeLoader` with a custom Actions resolver; duplicate keys rejected before construction; merge
keys rejected; only `true` and `false` resolved as booleans; `on`, `off`, `yes`, and `no` remain strings
in every location; timestamps and sexagesimals disabled. `on: push`, `on: [push]`, and
`on: {push: null}` normalize to the same single-event semantic form, while a bare `on:` has a null value
and is rejected rather than treated as `push`. Parser fixtures pin every YAML 1.1/1.2 edge named here.
`actionlint` continues to lint the source and
every generated workflow fixture. No claim is made that a standard-library checker can generally parse
Actions YAML; `check-project-readiness.py`'s checks remain deliberately bounded — presence, recognizable
`workflow_call`, canonical command, absence of secret passing and privileged environment declarations,
and the managed caller's exact hash — and are documented as bounded rather than semantic.

## Validation boundaries

### `scripts/validate-template.py`

Its shell observes the lifecycle-source and declared ownership paths; its pure decoder and rules
validate reusable machinery without assuming a bootstrapped instance: bundle, addition, plan, and manifest
schemas; the `RenderInput` schema and renderer purity; profiles and the complete capability catalog;
dependency topology; setting declarations and defaults; output ownership, declared kinds, and slots;
canonical path grammar; lifecycle-source membership and fingerprint; complete readiness-rule definitions
and compatibility corpus; and the stable-ID compatibility fixture. It returns structured diagnostics in
the shared schema, uses only declared generated-project dependencies, executes no capability content, and
never executes the adopter hook.

It does **not** validate source-only inputs. Revision 4 required it to validate the source-CI allowlist,
a file no generated project retains.

### `scripts/check-project-readiness.py`

Its shell reads only the readiness observation specification; its pure core emits a
`MechanicalReadinessResult`.
Without a manifest it behaves as today and reports the project
unbootstrapped at `informational` severity. With a manifest it additionally checks schema, checksum, and
internal topology; the frozen expansion, additions, and closure; managed artifact modes and normalized
hashes; the licensing decision and required preserved provenance; required durable documentation; hook
presence and mode at the canonical path; the seeded workflow's bounded contract; activation
declarations; retained maintenance paths, informationally; and the absence of declared placeholder
markers in any slot.

A source mismatch is reported as "reconcile required" on the Copier path. On a snapshot it reports the
exact changed paths and either a verified baseline-commit restore or regeneration. A managed inventory
mismatch is drift, with `restore` as the next action.

### `scripts/validate-project` and `scripts/validate-repository.py`

`scripts/validate-project` is the canonical adopter executable, invoked directly. Native Windows
execution is not a v1 guarantee.

`scripts/validate-repository.py` remains the canonical ordered boundary: template contract, project
readiness, adopter project validation. A pure `ValidationProgram` decides the next stage from typed
`StageObservation` values; the shell only launches the selected executable and captures its result.
Stages 1 and 2 expose the same pure rules used by bootstrap gating; stage 3 is adopter-owned, and its
failure means the project is not locally ready without meaning the installation was wrong. The
aggregate command preserves the adopter hook's normal nonzero status after successful earlier stages. Source-only
fixtures and matrix suites are not added to this portable boundary.

### Shared validator CLI

All three template-owned validation entry points accept the same presentation options as bootstrap:
`--format text|json`, `--color auto|always|never`, `--explain`, and `--quiet`, with the same compatibility
rules. They accept no positional arguments and derive their repository root from the entry point's
verified location; library tests call the pure cores directly rather than giving production commands a
hidden target mode.

Template-contract and readiness commands return 0 for no blocking finding, 1 for blocking findings, and
2 for usage, observation, contract-decoding, or internal failure. Aggregate validation returns the first
normal nonzero stage status exactly, including an adopter hook's nonstandard 1..255 status; signal and
launch mappings are defined below.

The aggregate shell captures each process stage into:

```text
StageObservation =
    StagePassed(exit=0, stdout, stderr)
  | StageFailed(exit=1..255, stdout, stderr)
  | StageSignalled(signal, stdout, stderr)
  | StageLaunchFailed(ProcessError)

CapturedStream = {total_bytes, sha256, prefix_base64, truncated}
```

Each prefix is capped at 1 MiB while the full stream is counted and hashed; truncation is explicit.
`prefix_base64` is RFC 4648 standard base64 with padding, so canonical JSON preserves arbitrary bytes.
The text presenter never writes captured bytes directly: it decodes valid printable UTF-8 but escapes
C0, DEL, ESC, bidi controls, and undecodable bytes with deterministic ASCII escapes. There is no raw
passthrough option. Text and JSON presenters render the same ordered `ValidationOutcome`.

Normal child exits 1 through 255 are preserved exactly by aggregate validation. A POSIX signal maps to
external status `128 + signal` when that is at most 255, otherwise 255, and remains structurally
distinguishable as `StageSignalled` in text/JSON. Launch failure maps to the aggregate's stable exit 2;
it is not a child exit. Adopter-hook output is untrusted opaque process output, not a template
diagnostic; it may contain values chosen by the adopter and is never persisted by validation. CI
supplies no secrets to that stage. This bounded capture gives JSON one valid envelope without allowing
arbitrary child output to corrupt it or inject terminal control sequences.

## Licensing and provenance

One explicit licensing choice, no default, no scaffold. For `retain-apache-2.0` the source Apache-2.0
text remains root `LICENSE`. For `provided-project-license` and `private` the adopter's text becomes
root `LICENSE`, `NOTICE.md` is kept, and the template Apache-2.0 text is retained at
`LICENSES/Apache-2.0.txt`.

The supplied bytes are covered by `answers.licensing.content_sha256`, so changing legal text is visible
to classification as an `InputChanged` field delta. The bytes themselves are never stored.

Every root or preserved legal/provenance file is seed-once adopter output. Template-owned source copies
live at distinct generated-lifecycle blob paths; Copier never owns the generated root paths, and
reconcile never rewrites them. This avoids making files that may require adopter notices or legal edits
drift-fatal. The audit may change exact paths or preservation rules, but it must leave every resulting
path in one ownership class and amend this design before implementation.

**The audit is a prerequisite to any licence-writing implementation** and gates every mode. It must
inspect every bundled skill's upstream licence and notice requirements; confirm whether the proposed
Apache and notice locations satisfy redistribution obligations; identify any notice that must remain
verbatim; define how adopter additions to notices are preserved; and amend this design and an ADR if
the required layout differs. `NOTICE.md:15` requires reviewing upstream licences before redistributing
the template, and every generation path redistributes those skills regardless of the root licence.

The audit may strengthen preservation requirements but may not authorize bootstrap to invent legal terms
or declare a project legally valid. This is a design gate, not a legal-validity opinion.

## Durable adopter documentation

Four managed documents rendered from core and capability fragment bodies:

- `docs/delivery-workflow.md`: canonical validation, CI and release gates, review flow, recovery, and
  the recommended adopter-owned `.gitattributes` configuration;
- `docs/template-updates.md`: generation path, Copier lineage or its absence, reconciliation, drift,
  `restore`, the statement that snapshots receive no managed updates and cannot reconcile, and the
  unsupported manifest-free contract;
- `docs/capabilities.md`: frozen expansion, additions, closure, displayable settings, dependencies; and
- `docs/github-setup.md`: required secrets, the two preflight states with likely causes including fork
  and Dependabot runs, Actions and ruleset steps, and the distinction between release and merge gates.

Each header names the document managed and directs project-specific prose elsewhere. Additions and
reconciliation update them in the same recoverable planned-path transaction as related artifacts. Direct
edits are drift repaired by `restore`.

## Cleanup inventory

`.agentic-template/maintenance-artifacts.json` declares the source-only paths that a GitHub snapshot
must remove: source test suites, the Copier smoke workflow, the source `pyproject.toml` and `uv.lock`,
the source-CI allowlist, the readiness-rule fixtures, and historical specs. Each entry records the path,
its expected source hash or tree hash, and whether it is a regular file or a directory tree. Entries may
not overlap any other ownership class, and the inventory does not list itself.

- Copier excludes the declared paths and the inventory by static configuration.
- Fingerprinted `SourceOwnership.snapshot_cleanup_paths` independently declares the finite deletion
  target set. Snapshot install proceeds only when it equals the decoded inventory path set and all
  complete bytes and shapes match, then removes the inventory itself as the final cleanup operation.
- A modified, missing-with-children, unsafe, or partially matching entry blocks cleanup, reports the
  exact path, and names `--leave-maintenance-artifacts`.
- A skipped cleanup records the retained paths and transfers them to adopter ownership.
- No later operation uses the inventory, which no longer exists in the generated project.

## Greenfield activation

No projects have been generated from the pre-bootstrap template. V1 therefore establishes one contract
without compatibility machinery:

- activation replaces the source scaffold's `.py` hook with the extensionless
  `scripts/validate-project` path in the same single release;
- Copier configuration, readiness, template validation, aggregate validation, fixtures, workflows, and
  documentation recognize only the extensionless path;
- no legacy alias, dual-path ambiguity rule, migration note, compatibility tag, prior-release fixture,
  adoption command, or ownership-transfer mechanism is implemented; and
- any unrecognized empty or populated manifest-free target is unsupported because it is outside the
  population this release creates, not because it belongs to a maintained legacy state.

The activation release notes record the exact release identifier and manifest schema 1 as the first
generated-project compatibility baseline. Compatibility begins when that release is published, not at
an ambiguous future population count. Later v1-compatible updates honor the schema and readiness rules
defined here; an incompatible future lifecycle requires its own approved design, but no pre-bootstrap
path or migration is thereby created.

If a real populated-project adoption need appears later, it requires its own approved design with
preview and collision semantics. V1 carries no dormant compatibility branch for that hypothetical case.

## Implementation batches

**One public release.** Development happens on an integration branch, `bootstrap-v1`, and reaches the
default branch through a **single activation merge**. Intermediate batches are review boundaries on that
branch and never touch the default branch.

Revision 4 claimed intermediate merges to the default branch were inert. They were not: batch 4 changed
Copier configuration and validation boundaries, both of which are public entry points, and
`.agentic-template/` content plus engine modules would ship into any snapshot created between batches
and stay frozen there. An integration branch removes the obligation to prove inertness rather than
attempting to satisfy it.

**Nine review boundaries.** Each boundary leaves the integration branch internally testable, but none
is a supported generated-project release.

| # | Contents | Evidence before merge to the integration branch |
| --- | --- | --- |
| 1 | Tooling and algebra foundations: explicit Python 3.14 lane; uv and pinned ty, pytest, Hypothesis, Ruff, and PyYAML; `Ok`/`Err`; frozen value conventions; diagnostics and CLI envelope; determinism primitives and schemas | Strict type check; exhaustive-union canary; lint/format checks; property-test canary; schema round-trips; primitive boundary and rejection fixtures |
| 2 | Staged observation sums; family-specific total decisions; operation semantics; readiness rule definitions; source/ownership declarations | Static exhaustiveness; generated complete bundle/project intent-state matrices; no illegal constructor fixture; a preimage witness for every leaf decision; every diagnostic next action reachable |
| 3 | Shared template-contract, readiness, and aggregate-validation cores; thin adapters replacing existing mixed scripts | Existing fixture parity; pure-core tests without filesystem/process access; stage-fold properties; canonical text/JSON parity |
| 4 | Resolver, typed slots, `render_managed`, verified blob maps, complete initial compiler, `ExpectedTarget`, and planner | Byte-identical render; missing-blob failures; semantically relevant input perturbation; complete seed/legal/manifest/cleanup plan; collision and plan ordering |
| 5 | Transaction interpreter: state root, lock, typed file/directory operations, raw backups, phases, idempotent rollback, recovery | Injected failure at every step; Hypothesis crash sequences; third-state recovery conflict; directory trees; git-clean survival; worktree/submodule/path safety |
| 6 | CLI adapters and generation paths: `init`, `status`, `plan apply`, `apply`, scaffold recognition, cleanup contract, core CI | Both paths install portable from supplied/scaffold bundles; complete CLI golden matrix; reserved marker and cleanup disagreement rejection |
| 7 | Catalog, profiles, four capabilities, contributions, compiled CI, secret preflights, compatibility definitions and corpus | Full profile matrix; actionlint; semantic readiness compatibility; structural preflight and local canary |
| 8 | Durable documentation plus `add`, `restore`, `reconcile`, source baseline repair, and destructive plan binding | Lifecycle sequences; operation-specific oracle; source-delta diagnostics; digest re-derivation; snapshot reconcile refusal |
| 9 | Greenfield activation: extensionless hook, Copier configuration, workflows, all boundaries, final cross-document consistency, release notes, and published adopter/maintainer documentation | Complete release gate; authoritative documents and ADRs already govern their dependent batches; no runtime, generated contract, fixture expectation, or user diagnostic names the `.py` hook or a legacy/migration lifecycle |

### Pre-runtime gates

- The owner-approved design, `docs/prd.md`, and `CONTEXT.md` govern batch 1. They are not deferred to
  activation.
- The functional-core/domain/ownership ADR is approved before batch 3 changes existing runtime
  behavior.
- ADR 0001 is updated before batch 6 integrates either generation path.
- The licensing and provenance audit completes before batch 4 defines licence-writing plans.

### Release gate

Both generation paths pass the full profile matrix; Copier update coverage proves seed-once preservation
and derived reconciliation; the transaction, lock,
recovery, and path-substitution suites pass; `actionlint` passes on the source and every generated
workflow fixture; source-CI conformance passes with no stale allowlist entry; preflight structural and
canary tests pass; the diagnostic reachability check passes; the readiness-rule baseline check passes;
every leaf decision constructor retains a generated preimage witness;
the licensing audit is complete and reflected in the installed layout; the PRD, `CONTEXT.md`, and ADR
0001 reflect the approved boundary; repository formatting, linting, tests, builds, and source fixtures
pass under both the uv-enabled dev shell and the explicit Python 3.14 lane; strict ty passes with no unknown or
unchecked core definition; deterministic Hypothesis properties pass and exploratory failures have a
recorded seed plus a promoted regression example; no runtime,
generated contract, fixture expectation, or user diagnostic names the `.py` hook or a legacy/migration
lifecycle; and verification-before-completion and substantive code review find no unresolved required
issue.

## Verification strategy

### Unit coverage

- Canonical JSON: strict decoding, duplicate keys, exact types including boolean-versus-integer, float
  and NaN rejection, integer range, **surrogate rejection**.
- Path grammar: absolute, `.`, `..`, backslash, repeated separator, trailing separator, empty component,
  NUL, non-UTF-8, case collision.
- LF normalization: CRLF, lone CR, mixed endings, absent final newline, multiple trailing newlines,
  invalid UTF-8 in a text artifact, exact hashing of binary artifacts.
- Entry and tree hashing, **tested in isolation** with a path containing a newline and a control
  character, because the grammar rejects such paths at input; the encoding must still be unambiguous.
  A separate fixture asserts the grammar rejects them.
- Domain-tag separation across every tagged construction.
- Absent versus empty file; explicit directory-operation topology; symlink rejection; normalized
  execute-bit comparison versus exact transaction-mode restoration.
- Deep immutability: no list, dict, path object, iterator, exception, or shell handle crosses into a core
  value; attempts to mutate nested values fail; byte graphs intern content in one bounded
  `VerifiedBlobStore`.
- Resource limits: exact and one-over cases for paths, components, depth, file count, operation count,
  single-file bytes, aggregate unique bytes, and diagnostic count; limit failure produces no partial
  decision or plan.
- `Result` composition and applicative error accumulation; expected failures do not raise; exhaustive
  matches contain `assert_never` and the static checker fails when a canary constructor is added.
- Every `ProcessError`, `RenderError`, `EffectRequest`, and `EffectObservation` constructor has exactly
  one admissible continuation and diagnostic/outcome mapping; mismatched request/observation pairs fail
  closed, and a constructor-addition canary fails static checking.
- Coherent observation accepts two byte-identical bounded passes, retries a changed pair, and returns
  `ConcurrentTargetChange` without decoding after the third changed pair.
- `RenderInput` perturbation: every field declared semantically output-affecting changes output or is
  rejected; `maintenance.retained_paths` and `default_branch` are covered; schema-version dispatch and
  non-affecting fields have separate tests; an unselected capability definition has no effect.
- Renderer purity: rendering succeeds with no filesystem, environment, clock, or network access, and a
  missing blob fails before rendering.
- `MechanicalReadinessResult` identity, normative sort order, and multiset comparison including a repeated finding
  and a worsened count.
- Manifest: round-trip, strict tagged source-baseline variants, managed-only inventory, checksum over
  payload excluding checksum, and no derived-recomputation validity gate.
- Decision algebra: every legal `BundleIntent × BundleState` and `ProjectIntent × SystemState` pair
  yields exactly one decision; illegal state combinations cannot be decoded or constructed through
  public factories; every leaf decision has a preimage witness.
- Journal phase transitions, corrupt/unknown journal handling, raw backup verification, idempotent
  rollback reducer, preparation ownership markers, lock acquisition/release, and complete plan-digest
  rejection. Every filesystem primitive and sanitized errno class maps to its exact typed failure.
- Presenter parity: text and JSON render the same `CommandOutcome`; color and TTY facts affect styling
  only; no secret or absolute path enters either representation; arbitrary stream bytes round-trip from
  base64 JSON and render as terminal-safe text.

### Tiered fixtures

Each batch runs what exists at that point; the tiers describe the released steady state.

**Pull-request tier**, a few minutes: both paths across `portable` and `integrated`;
`retain-apache-2.0` and `provided-project-license`; one all-`scaffold` and one fully supplied bundle;
drift and restore; one injected interruption and recovery; `actionlint`.

**Pre-release tier**: both paths across all five profiles; custom empty, single, dependent, and
multi-capability sets; all three licensing modes; every required setting variation; unavailable and
available activation structures without real secrets.

Runtime budgets are recorded when fixtures land; a tier exceeding its budget is split rather than
silently slowed.

### Lifecycle coverage

Classification and identity:

- Every row of the operation-semantics table: assert exactly which recorded values each operation
  changes, and that `restore` changes none.
- Every sequence: `apply`; `apply → add → apply` reaching `EquivalentVerification`; `apply → add → reconcile → apply`;
  `apply → reconcile → add`; `apply → restore → add`.
- `apply` after a Copier update with identical answers and healthy inventory reaches `TemplateChanged`,
  not `InvalidManifest` and not `EquivalentVerification`.
- `BOOTSTRAP_RENDER_CONTRACT` is reachable separately for equivalent apply, requested restore
  projection, and add's old complete render; new-source reconcile never produces it.
- `UnsupportedTarget`: an arbitrary empty or populated manifest-free target is refused with the
  fresh-scaffold action and never mentions a legacy path, adoption, or migration.
- `CatalogIncompatible`: a catalog whose dependency edges changed is reported as such, not as manifest
  corruption.
- A pending journal on a project whose recorded fingerprint no longer matches reports `RecoveryRequired`,
  not `InvalidManifest`.
- Changing only the supplied licence bytes yields `InputChanged` naming the licensing field.
- `InputChanged` names the specific changed field for a mechanical change and for a content change.

Gating and scaffold:

- An all-`scaffold` install is retained, gate-passes, and exits 1 naming exactly the scaffolded slots.
- An all-`scaffold` equivalent **`apply`** also exits 1, runs the mechanical-readiness boundary, and
  attempts the hook at most once.
- The install exemption is exact: a placeholder finding for an undeclared slot, or any extra blocking
  finding, gate-fails and rolls back.
- Artifact verification precedes exemptions: corrupt one planned artifact post-install and prove the gate
  fails despite a valid scaffold exemption.
- `add`, `restore`, and `reconcile` succeed on a project whose PRD is still a placeholder.
- A mutation that newly breaks readiness gate-fails even when an unrelated placeholder finding existed.
- A mutation that increases an existing finding's count gate-fails, which a set comparison would miss.
- The complete readiness-rule definition comparison and old-state corpus reject a new required
  seed-once path, informational-to-blocking change, stricter same-ID predicate, or rule with no legal
  satisfier.
- A `file` input containing a reserved marker is rejected; a non-UTF-8 binary hook is accepted and its
  sentinel detected at byte level.

Transaction and recovery:

- Injected failure before the journal, after the journal and before each preparation, in each phase,
  during gating, cleanup, rollback, and rollback recovery.
- For every preparation role: collision before create, crash after directory create but before marker,
  crash during marker/child write, valid partial marked content, mismatching token, and unexpected child;
  only identity-proved preparation is deleted.
- Gating failure rolls back before cleanup and before the hook.
- A crash during gating leaves `MUTATING`, and `recover` rolls back — proving ungated output cannot
  survive.
- A crash after complete rollback but during evidence cleanup leaves `RESTORED`; recovery verifies
  pre-state and continues cleanup without requiring a removed backup or reinstalling the candidate.
- A `SEALED` journal is completed forward by `recover`, never rolled back.
- Two concurrent mutations, and a mutation concurrent with `recover`: the second is refused by the lock.
- Unlocked status and plan observations racing journal creation, a `MUTATING` path change, `RESTORED`
  or `SEALED` cleanup, journal removal, and an adopter edit return either one double-collected stable state or
  `ConcurrentTargetChange`, never a mixed status or plan.
- An abandoned lock file from a killed process is acquired normally rather than blocking forever.
- `recover` refuses a target whose identity does not match.
- A corrupt/truncated/unknown-version journal and missing or hash-mismatched backup enter
  `StateRootInvalid`, preserve evidence, and never permit another mutation.
- The rollback reducer is idempotent for every create/replace/delete/directory operation in reverse
  dependency order; `CreateTree` rollback remains resumable on both sides of its atomic rename;
  `RemoveEmptyDirectory` restores exact mode; a third state blocks without overwrite; raw CRLF bytes and
  exact old modes are restored.
- The `SEALED` forward reducer verifies every file and directory candidate before removing any durable
  evidence; a post-seal third state retains backups and the journal.
- Ancestor substitution: replace an intermediate directory with a symlink between planning and install
  and prove the operation aborts and never follows it.
- Parent rename: move a planned path's parent between planning and install and prove re-resolution
  detects it.
- Recovery evidence survives `git clean -fdx`.
- Linked worktree independence; submodule uses its own administrative path; bare repository refused;
  non-git target refused.
- Existing-parent staging and new-tree staging are same-filesystem, verified on a target containing a
  nested mount without requiring a privileged mount in ordinary CI; platform-privileged coverage is an
  optional additional lane.

Hook and status:

- A failing hook leaves the installation and exits 1.
- `status` never executes the hook and reports "not evaluated" rather than any past outcome.
- The hook is attempted at most once after a gated install and on `EquivalentVerification`, and zero times on
  refusal, rollback, `recover`, every plan command, `status`, and `init`; a crash after journal removal
  may yield zero attempts and recovery never replays it.

Exit semantics:

- One fixture per command family asserting the family's 0, 1, and 2 conditions, including that `status`
  never returns 1.

### Workflow and security coverage

- `actionlint` on the source and every generated workflow fixture.
- The managed caller passes no secrets and has read-only permissions; the seeded workflow invokes the
  canonical boundary with no privileged environment; release depends on the full call and selected
  checks.
- Unavailable Gemini and Cachix secrets produce successful skip guidance naming the fork and Dependabot
  causes; privileged jobs cannot start when preflight is false.
- Preflight structural policy and local canary.
- Source-CI conformance: complete declared workflow/job/step semantic fields; effective environment,
  defaults, strategy, outputs, `with`, secrets, and permissions; step identity/order; separate raw pin
  comment check; trust predicates for every privileged job; stale and uncovered allowlist differences;
  PyYAML rejection of duplicates, merge keys, and bare-null `on`; Actions boolean fixtures.
- Every diagnostic's next action exists for the relevant generation path.
- Persisted checkout credentials and credential-looking values are absent.

## Compatibility and the PRD

| Requirement | Change |
| --- | --- |
| REQ-001 detect incomplete setup | Retained and extended: readiness names unreplaced slots, derived from declared markers |
| REQ-002 one validation command | Retained; greenfield activation establishes `scripts/validate-project` as the only hook path, with no compatibility alias or migration note |
| REQ-003 gate releases on project validation | Retained; the gate is a compiled contribution present only with `semantic-release` |
| REQ-004 verify generated behavior from source | Extended to the tiered matrix and both paths across profiles |
| REQ-005 preserve generation-path ownership | Extended with disjoint ownership classes, source baselines, operation-specific drift, and explicit refusal of unrecognized manifest-free targets |
| REQ-006 portable, least-privileged template validation | Retained; generated runtime dependencies are explicit, uv-managed, and least-privileged, while pinned ty, pytest, Hypothesis, Ruff, and PyYAML provide source assurance |
| REQ-007 deterministic bootstrap | The compiler, its input contract, greenfield target boundary, and byte-for-byte output guarantees |
| REQ-008 capability selection and addition | Profiles, catalog, normalized additive settings, and the absence of unselected artifacts |
| REQ-009 ownership and identity | Disjoint ownership classes, primary manifest state, managed inventory, and source baseline |
| REQ-010 closed lifecycle | Total status/plan/apply/add/restore/reconcile/recover behavior and operation-specific inventory oracles |
| REQ-011 recoverable mutation | Lock, journal phases, exact rollback or forward cleanup, and third-state preservation without atomic multi-file visibility |
| REQ-012 installation and readiness | Mechanical gating and point-in-time hook evidence remain distinct; a completed installation whose hook fails exits 1 |
| REQ-013 evolution compatibility | Stable definitions and behavioral corpus prevent compatible updates from creating unsatisfiable obligations |
| REQ-014 typed CLI | Functional core, total transition algebra, rich text/JSON outcomes, and explicit sad paths |
| REQ-015 durable extensibility | Managed operational documentation, adopter-owned validation extension, and declarative capability growth |

### Domain-language alignment

This revision incorporates the following changes into `CONTEXT.md`:

- **Project bootstrap** gains the distinction between a completed installation and a locally ready
  project.
- **Project readiness** keeps its meaning, including successful hook completion, and gains that
  unreplaced slots are derived from declared markers; **mechanical readiness** is the explicitly
  separate pre-hook finding result.
- **Bootstrap-managed artifact** gains `restore` as the remedy and `ManagedInventory` as the
  operation-specific oracle.
- **Project-validation hook** is defined only at `scripts/validate-project`.
- New terms: **bootstrap installation**, **mechanical readiness**, **managed inventory**, **source
  baseline**, **capability additions**, **managed drift**, **unrecognized manifest-free target**,
  **point-in-time hook evidence**, **source ownership**, and **cleanup contract**.
- The example dialogue gains an exchange distinguishing "bootstrap installed the files" from "the
  repository is locally ready", and one explaining why a GitHub snapshot cannot reconcile.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A required workflow is unreachable through classification | Exhaustive bundle/project transition functions, static checking, generated matrix properties, and per-constructor preimage witnesses |
| Manifest validation rejects a legitimate template update | Validity is parse, schema, and checksum only |
| A render-contract violation is undetectable or falsely raised during reconcile | Operation-specific managed-inventory projections |
| Initial installation needs ambient adopter bytes | `VerifiedBundle` contains `AdopterBlobMap`; one complete pure plan owns every write |
| A source fingerprint silently stops covering behavior | One exhaustive lifecycle-source ownership manifest plus per-entry perturbation fixtures |
| A generated project fingerprints a file it never received | The three-way input boundary |
| An operation changes identity it should not | The operation-semantics table, asserted row by row |
| A repair silently upgrades the template | `restore` writes only certified bytes and records nothing |
| Ungated output survives a crash | Gating inside `MUTATING`; rollback persists `RESTORED`, while only a passed gate permits `SEALED` |
| An interrupted rollback completes forward | Phase-dependent recovery with no phase doing both |
| A torn or manually damaged journal is treated as absent | Atomic transitions plus explicit invalid-journal and recovery-blocked states |
| Normalized drift identity cannot restore raw pre-state | Separate raw backup digest and exact mode, with an idempotent rollback reducer |
| New parent directories escape the plan | Typed `CreateTree` and explicit bottom-up directory removal |
| An abandoned lock blocks forever, or lock domains split | A never-unlinked inode, no `O_EXCL`, `flock` for liveness |
| State location varies and hides pending recovery | A git working tree is required; location is a pure function of the target |
| Replacement crosses a filesystem boundary | Existing-parent staging and new-tree staging adjacent to the relevant existing ancestor |
| An ancestor is substituted between check and use | Root-anchored per-component walk and re-resolution |
| A security guarantee exceeds its primitives | The threat model is stated narrowly and excludes a concurrent local adversary |
| A compatible update tightens a same-ID readiness predicate | Canonical complete rule definitions plus the old-conforming-state corpus |
| Snapshots acquire an update lifecycle by accident | `reconcile` is unavailable; source inventory names baseline repair or regeneration only |
| Hypothetical legacy support creates dead branches | Greenfield activation contains one hook and manifest contract with no compatibility machinery |
| An intermediate merge changes behavior | Integration branch with one activation merge |
| A defective install hides behind the scaffold exemption | Artifact verification precedes exemptions; the install rule is equality |
| A repeated or worsened finding goes undetected | Multiset comparison over four-part identity |
| Adopter content impersonates a placeholder | Reserved markers rejected in `file` inputs |
| A non-text hook breaks detection | Byte-level sentinel search |
| Security-relevant CI drift stays green | Complete declared workflow/job/step normal form, raw pin-comment check, and trust predicates |
| A canary gives false assurance | Run locally with a non-secret sentinel across all channels |
| A YAML parser's defaults misread Actions | An Actions resolver, duplicate/merge rejection, null-trigger distinction, and parser fixtures |
| The Python floor or sum exhaustiveness is unproved | Python 3.14 lane, strict ty, and a constructor-addition canary from batch 1 |
| False drift from line endings or umask | Specified normalization and execute-bit-only comparison |
| An ownership class traps ordinary configuration | `CONTRIBUTING.md` and `.gitattributes` are adopter-owned |
| Bootstrap becomes an authoring gate | `scaffold` compiles a real project before prose exists |
| A destructive overwrite runs unreviewed | Bound to a recomputed plan digest and target identity |
| Human and JSON CLI paths disagree | Two pure renderers over one typed `CommandOutcome`, with parity fixtures |
| A secret leaks through the preflight | Fixed trusted job, structural test, local canary |
| Licence obligations are lost | Conservative preservation plus an audit gating every mode before licence writing |
| One change contains the whole system | Nine review boundaries on an integration branch |

## Proposed future changes

**Experience:** one-command initialize-and-apply over the same engine; inline prose fields with
escaping; guided PRD authoring; stack presets without an implicit default; opt-in regeneration of
seed-once files; `apply --strict` gating on the hook.

**Capability lifecycle:** a broader first-party catalog; third-party registries with signing and trust
policy; live profiles; removal, replacement, and reconfiguration; versioned capability IDs with
migrations between manifest-bearing bootstrap releases; managed document regions; a sandboxed plugin
model if declarative slots prove insufficient.

**Adoption and portability:** only after a concrete non-legacy use case exists, an adoption lifecycle
for arbitrary populated repositories with preview, collision handling, and ownership transfer; snapshot
conversion into Copier lineage; non-git targets with a state-namespacing rule;
declarative validation-command lists; interpreter adapters and native Windows support; a portable
structured workflow parser; hook sandboxing; a hermetic executable distribution that could justify
selected runtime CLI or validation libraries.

**GitHub and activation:** a read-only configuration doctor covering Actions availability, default
branch, authoritative secret configuration, workflow activation, rulesets, and required checks;
authenticated repository-identity and rename diagnostics; authorized configuration writes in a separate
operator tool.

**Distribution:** maintenance automation opening reviewable update PRs with reconciliation previews;
signed release provenance; SPDX and SBOM automation; Copier-native conditional rendering if one
generation path ever suffices; opt-in trusted Copier tasks.

Recommended order: deterministic bootstrap, then the configuration doctor, then maintenance automation.

## Rejected alternatives

Ordinal profiles such as minimal/default/full; an implicit engine profile default; re-expanding a stored
snapshot; accepting, persisting, or inferring secret values; claiming a secret is unconfigured from an
empty value; reading a secret in a job that also checks out the repository or runs repository scripts;
unapproved external configuration writes; persisting live activation status, or repository owner and
name; silently overwriting or merging managed drift; leaving drift with no remedy; letting a repair
advance identity; letting a partial repair update repository-wide state; recording a render identity
that must be re-derived from a changed source; validating derived manifest state before classification;
a renderer whose inputs are hashes; fingerprinting a file a generation path does not retain; declaring a
flat Cartesian facts record with impossible combinations; one operation-neutral decision interpreted
differently by each CLI adapter; exception-driven expected control flow; mutable nested core values;
runtime CLI/validation frameworks before hermetic distribution; shell-side writes outside the typed plan;
transaction committed before it is gated; a fourth transaction phase whose recovery duplicates another's;
combining `O_EXCL` with `flock`; unlinking and recreating a lock; deriving the lock location from a
user-supplied state directory; non-atomic journal transitions; a single staging directory for a target
spanning mounts; claiming atomic multi-file visibility; operating on planned paths by name after a
one-time check; claiming resistance to a concurrent local adversary; comparing readiness findings as
`(code, path)` sets; allowing an empty finding path; a `Finding` order left to implementation; one global
exit-code rule across inspection and mutation; claiming the hook runs once when refusals and rollbacks
run it zero times; gating the transaction on the hook; reporting success when the hook failed; treating
an equivalent `apply` as an unconditional exit-0 no-op; recording or replaying hook results; `status`
executing the hook; requiring complete prose before compiling; recording slot completion in the manifest;
requiring the hook to be decodable UTF-8; accepting adopter content containing a reserved marker; two
canonical hook paths; an adoption command without preview or collision rules; implying a rename bootstraps
a project; any v1 legacy hook alias or compatibility release; a manifest listed in its own inventory;
giving snapshots any update lifecycle; promising both a
v1 update and a pre-bootstrap pin; assuming Copier excludes transfer ownership without per-path evidence;
a migration fixture depending on live tag history; `git restore scripts/` as rollback; claiming
intermediate default-branch merges are inert; comparing only `env` key names; claiming stale-entry expiry
prevents allowlist accumulation; relying on GitHub log masking as canary evidence; using default PyYAML
semantics for Actions YAML; implying a standard-library checker can parse Actions YAML; treating capability
removal as reconciliation; a version-aware updater competing with Copier; parallel Copier and Python
rendering; mandatory trusted Copier tasks; requiring `--target` on `init`; legal boilerplate authored by
bootstrap; deferring the licensing audit for any mode; independently releasable slices with per-slice
manifest compatibility levels.

## Required follow-up documents

- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs on the Copier path only. **Pre-runtime gate.**
- An ADR for the functional-core architecture, the domain model, and the ownership boundary.
- The licensing and provenance audit record and any resulting ADR. **Prerequisite to batch 4.**
- `docs/project-readiness.md`, reflecting the canonical hook path, derived slot completion, `status`,
  `restore`, and the unrecognized manifest-free contract.
- Release notes for the one greenfield activation, its exact compatibility-baseline identifier,
  CLI/input schemas, generated-project prerequisites, and recovery guidance; no pre-bootstrap migration
  or compatibility path.
- Generated adopter documentation described above.
- Source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open. The Git-working-tree requirement and greenfield-only activation
are adopted boundaries.

The licensing and provenance audit gates every licensing mode and precedes batch 4. If it changes the
proposed `LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design must be amended and reconfirmed
before licence-writing implementation proceeds.

## References

- `docs/prd.md`; `CONTEXT.md`; `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md` remains as a separate active spec and is not one of
  this document's superseded revisions.
- This document's earlier discovery and revision drafts were consolidated here and are not retained in the
  active bootstrap spec directory.
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub: Dependabot on Actions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions)
- [Git: `git rev-parse`](https://git-scm.com/docs/git-rev-parse); [Git: `git clean`](https://git-scm.com/docs/git-clean)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/); [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
- [Python 3.14: `typing.assert_never`](https://docs.python.org/3.14/library/typing.html#typing.assert_never)
- [Astral `ty` documentation](https://docs.astral.sh/ty/)
- [Hypothesis: rule-based stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html)
- [pytest documentation](https://docs.pytest.org/en/stable/contents.html)
- [Ruff linter](https://docs.astral.sh/ruff/linter/); [Ruff formatter](https://docs.astral.sh/ruff/formatter/)
- [Typer dependencies](https://typer.tiangolo.com/); [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/)
