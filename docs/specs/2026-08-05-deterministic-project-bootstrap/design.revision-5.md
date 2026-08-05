# Deterministic Project Bootstrap with Capability Profiles

**Status:** Revision 5, assembled for independent approval review
**Date:** 2026-08-05
**Planning mode:** Spec-backed Plan
**Supersedes:** `design.discovery-draft.md` (revision 1), `design.revision-2.md`,
`design.revision-3.reconstructed.md`, `design.revision-4.md`

## Summary

Add a deterministic bootstrap compiler that turns either supported generated-repository shape into a
locally ready project from a reviewable input bundle. The compiler expands an explicitly selected
snapshot profile into an exact capability set, renders declared outputs from a pure function, installs
them through a recoverable transaction, and reports the result through the repository's canonical
validation boundary.

The first capability catalog covers the integrations already present in the template: semantic-release;
Nix; Cachix publishing, which depends on Nix; and Qodo PR Agent with a Gemini backend.

V1 is one public release, developed on an integration branch and activated by a single merge. It is a
breaking template-contract change for the current repository, released with migration instructions.

Revision 5 is a structural simplification, not an edit pass. Revisions 2 through 4 accumulated three
compounding errors: the manifest was made a reconstruction source, fingerprints stood in for
comparisons better expressed over values, and several guarantees were stated ahead of the primitives
that would deliver them. This revision removes one recorded value and two fingerprints, which
collectively resolves nine of the previous review's blocking findings.

This design extends `docs/prd.md`. Implementation must update the PRD, `CONTEXT.md`, and ADR 0001 as
pre-runtime gates.

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

## Scope reductions proposed in this revision

Both remove capability and are flagged for explicit assent. Each is drafted as adopted; reverting
either is a local change to the sections named.

| Reduction | What is removed | Why | To revert |
| --- | --- | --- | --- |
| **A git working tree is required** | `--state-dir`, non-git targets, and the in-tree lock | State location becomes a pure function of the verified target, which removes an entire class of mutual-exclusion, state-discoverability, and recovery-visibility defects. Revision 4 needed four separate rules to approximate what this makes true by construction | Reinstate `--state-dir` with a namespacing rule, and re-solve pending-journal discoverability |
| **Populated manifest-free projects stay on the pre-bootstrap release** | Any path from an existing project into v1 | Revision 4 promised both "update to the v1 tag" and "pin the last pre-bootstrap release", which is not a steady state, and it asserted rather than demonstrated that newly added Copier excludes transfer ownership safely | Define a named v1 compatibility release with operation-aware excludes and per-path ownership-transfer fixtures |

## Revision ledger

### Corrections to earlier ledgers

Revision 4's ledger contained factual errors. They are struck here rather than carried forward.

| Earlier claim | Status | Evidence |
| --- | --- | --- |
| "Revision 1 installed the hook at `scripts/validate-project.py`" | **False; struck** | `design.discovery-draft.md:112` already specifies the extensionless path. The breaking change is against the current repository, not against revision 1, and now appears only in the requirement delta and migration sections |
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
| `CONTRIBUTING.md` is bootstrap-managed output (`design.discovery-draft.md:403`) | Seed-once adopter output | A managed drift-fatal file that adopters are expected to edit blocks the repository |
| One `initial_input_fingerprint` | Normalized answers stored as values; **no input fingerprint at all** | A fingerprint is a lossy compression of a comparison; storing the values yields field-level diagnostics for free |
| `.agentic-template.json` | `.agentic-template/project.json` | One namespace; one character of separation was too little |
| `compiler_contract_version` in the manifest | Removed | `template_source_fingerprint` already covers engine and catalog identity |

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
| A legacy `.py` hook path and a half-specified `adopt` | One canonical path; adoption deferred |
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
| The journal entered COMMITTED before gating, so a crash preserved ungated output and an interrupted rollback completed forward | Three phases; gating inside `MUTATING`; `SEALED` only after gating passes |
| `O_CREAT \| O_EXCL` plus `flock` cannot detect an abandoned lock, and unlink-and-recreate splits lock domains | A never-unlinked lock inode opened without `O_EXCL`, then `flock(LOCK_EX \| LOCK_NB)` |
| Journal phase updates had no atomicity requirement, permitting torn JSON | Temp-write, fsync, rename, fsync parent |
| Differing `--state-dir` values could conceal a pending journal | `--state-dir` removed; state location is a pure function of the target |
| Staging was weakened to one directory "on the target's filesystem", which a repository spanning mounts defeats | Staging is adjacent to each destination parent |
| Target identity was no longer normatively defined | Defined as the verified absolute worktree root plus its device and inode |
| `O_NOFOLLOW` on the parent protects only the final component, and `fstat` does not prove continued attachment | Root-anchored per-component walk, re-resolution before mutation, and a **narrowed threat model** |
| A compatible v1 update could add a required seed-once path that no lifecycle could satisfy | A template-evolution compatibility rule, enforced by a frozen readiness-rule baseline |
| The migration promised both "update to v1" and "pin the pre-bootstrap release" | One steady state; see the scope reduction above |
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
| The dev shell's unversioned `python3` does not establish the 3.11 floor | An explicit 3.11 validation lane |

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

### Unchanged load-bearing decisions

Snapshot profiles freeze at creation; additions are recorded separately from the closure; secrets are
never accepted or persisted; repository owner and name are never persisted; transactions cover only
planned paths and never claim to roll back hook-created artifacts; the renderer cannot execute
capability-supplied code; generated-project validation is Python 3.11 standard library only.

Approaches B (mirrored Copier and Python rendering) and C (trusted Copier task) were considered and
rejected in revision 1; see `design.discovery-draft.md`. Approach A, one shared declarative
standard-library compiler, remains selected.

## Context and problem

The current template detects incomplete generated-project setup but does not perform it. A generated
repository inherits a fixed integration set and requires manual replacement of the README, PRD, and
validation hook. CI and the release graph assume Nix, Cachix, semantic-release, and Gemini review
whether or not an adopter wants them. This yields five problems: no reviewable transition from
scaffold to ready project; optional integrations coupled to the source tree; two generation paths
drifting into separate setup implementations; no strict file-ownership boundary; and durable
operational guidance lost to README customization.

## Goals

- Produce a locally ready repository from adopter content and explicit mechanical choices, without
  requiring that content to exist before the project can compile.
- Make rendering a pure function of explicit inputs, so identical inputs yield identical bytes.
- Require explicit intent-based profile selection and freeze its expansion at creation time.
- Support exact custom capability selection and additive post-bootstrap changes.
- Keep core validation independent of optional capabilities and external activation.
- Share one engine, one classifier, and one renderer across both generation paths.
- Give Copier and bootstrap non-overlapping update responsibilities.
- Preserve adopter-owned content, detect managed drift, and provide a supported remedy.
- Make every reachable project state map to exactly one classification.
- Make an interrupted mutation recoverable for every planned path.
- Make missing external secrets safe and actionable.
- Produce durable adopter-facing operational documentation.
- Allow new declarative capabilities without changing the resolver, renderer, or transaction shell.

## Non-goals

- Inventing or judging product requirements, README content, security policy, or legal terms.
- Judging whether the adopter's validation hook is adequate, or rolling back a valid installation
  because it failed.
- Claiming atomic visibility across multiple files.
- Accepting, storing, or writing secrets, or authoritatively diagnosing whether a secret is configured.
- Mutating GitHub repository settings, rulesets, branch protection, or external services.
- Capability removal, replacement, or reconfiguration in v1.
- Re-expanding a stored snapshot when a named profile changes later.
- Migrating incompatible capability or manifest schemas.
- Bootstrapping, adopting, or migrating a populated project that has no manifest.
- Giving GitHub snapshots any template update lifecycle, including local reconciliation.
- Reimplementing Copier's version selection, update merge, or conflict behavior.
- Operating on a target that is not a git working tree.
- Defending against a local adversary with concurrent write access to the target during a mutation.
- Providing native Windows execution guarantees.
- Providing a general-purpose template language, executable plugins, or trusted Copier tasks.
- Proving the semantic validity of an adopter-owned workflow from the generated-project boundary.
- Rolling back artifacts or external effects created by the adopter validation hook.

## Domain model

One canonical value per concept. Every value is immutable. `primary` is a recorded fact or intent;
`derived` is recomputable by a pure function; `observed` is read from the world by the shell;
`effectful` exists only at the boundary.

| Value | Kind | Contents |
| --- | --- | --- |
| `Intent` | primary | The decoded command and its arguments |
| `InitialAnswers` | primary | `project{name, default_branch}`, `profile{id, requested}`, `settings`, `licensing{mode, content_sha256?}`, `slots{slot -> {mode, content_sha256?}}` |
| `RecordedProjectState` | primary | `answers: InitialAnswers`, `additions: [CapabilityId]`, `provenance{generation_path, template_source_fingerprint, maintenance{status, retained_paths}}`, `installed: [InventoryEntry]` |
| `InventoryEntry` | primary | `{path, kind: text\|binary, mode, sha256}` — a record of what bootstrap wrote |
| `CurrentTemplate` | observed | Decoded catalog, profiles, core definitions, schemas, compatibility fixture, plus `BlobMap`, plus its computed `template_source_fingerprint` |
| `BlobMap` | observed | `sha256 -> bytes`, verified on load |
| `ObservedTarget` | observed | Journal phase if any; manifest status; per-path `{present, kind, mode, normalized_sha256}` for every declared-ownership path; scaffold recognition; Copier conflict evidence; topology facts |
| `Facts` | derived | The independently computed comparisons the classifier consumes |
| `ApplyDecision` | derived | Total sum type over `Facts` |
| `RenderInput` | derived | The complete structured input to rendering |
| `RenderResult` | derived | `path -> {kind, mode, bytes}` |
| `FilesystemPlan` | derived | Ordered operations with expected old and new `{sha256, mode}`, plus target identity |
| `ReadinessResult` | derived | Ordered findings with multiset-comparable identity |
| `GateResult` | derived | `Pass \| Fail [Finding]` |
| `TransactionPhase` | effectful | `PLANNED \| MUTATING \| SEALED` |
| `CommandResult` | effectful | `{exit_code, diagnostics, hook: NotRun \| Ran{status}}` |

### Pipeline

```text
decode(raw)            -> Intent                          [shell]
load(template dir)     -> CurrentTemplate, BlobMap        [shell]
inspect(target)        -> ObservedTarget                  [shell]

facts(Intent, ObservedTarget, CurrentTemplate)  -> Facts          [pure]
classify(Intent, Facts)                         -> ApplyDecision  [pure]
compile(ApplyDecision, ...)                     -> RenderInput    [pure]
render(RenderInput, BlobMap)                    -> RenderResult   [pure]
plan(RenderResult, ObservedTarget)              -> FilesystemPlan [pure]
readiness(ObservedTarget | RenderResult)        -> ReadinessResult[pure]
gate(op, baseline, expected, observed_after)    -> GateResult     [pure]

interpret(FilesystemPlan, gate) -> Installed | RolledBack | RecoveryRequired  [shell]
run_hook(Installed)             -> CommandResult                              [shell]
```

The functional core imports nothing from the shell. No core function reads the filesystem, the
environment, the clock, Git metadata, or process state.

### Why only one fingerprint remains

A fingerprint is a lossy compression of a comparison. It is justified only when the values compared
are too large to store or must not be stored.

| Comparison | Revision 4 | Revision 5 |
| --- | --- | --- |
| Did the answers change? | Two digests | Field-wise diff of stored `InitialAnswers`, yielding *which* field changed |
| Did the template change? | `template_source_fingerprint` | Unchanged — a template tree is too large to store |
| Does our render match what we installed? | `render_identity`, recomputed on every manifest read | Compare re-rendered bytes to the recorded `InventoryEntry` hash, at the point of use |

Deleting `render_identity` is the single change that makes `TemplateChanged` reachable: revision 4
recomputed it from persisted state plus the *current* template, so after any template update the
rebuild could not reproduce the recorded value and manifest validation failed before the classifier
could say "the template changed." Nothing in v1 needs to re-derive an old render from a new source.

Adopter-owned bytes — legal text and seed content — are the one place digests remain necessary, since
those bytes must not be copied into the manifest.

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
template_source_fingerprint = tree_hash(b"template-source", generated-lifecycle inputs)
```

It covers exactly the compiler inputs that both generation paths retain and that a generated project
needs for its own lifecycle: engine modules, the capability catalog, core definitions and their static
blobs, schemas, `profiles.json`, and the stable-ID compatibility fixture. See the input-boundary
section for what is deliberately excluded and why.

## Render boundary

```text
render : RenderInput -> BlobMap -> RenderResult
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
  additions: [CapabilityId]
  effective: [CapabilityId]         # closure, sorted
  definitions: {CapabilityId -> CapabilityDefinition}   # decoded, effective only
  core: CoreDefinition                                   # decoded
  settings: {CapabilityId -> {name -> value}}            # normalized, non-secret
  contributions: [ResolvedContribution]                  # final resolved order
  documents: {path -> [FragmentBody]}                    # bodies, not identities
  maintenance{status, retained_paths}                    # retained paths affect document text
  slots: {slot -> {mode, content_sha256?}}
```

`BlobMap` supplies static payloads by content address; the shell loads and verifies it. Every blob a
definition references must be present, or `compile` fails before rendering.

`maintenance.retained_paths` is part of the input because a skipped cleanup transfers those paths to
adopter ownership, which changes what `docs/template-updates.md` says. Revision 4 passed only the
status, so two projects with identical selections and different retained paths would have rendered
different documents from identical inputs.

**Renderer capability** is unchanged from prior revisions: validated scalar substitution into declared
typed contexts; whole optional sections controlled by normalized booleans; deterministic iteration over
sorted declared values; and contributions to named typed slots with declared ordering and cardinality.
No expression evaluation, no code import, no shell, and no capability-chosen output path. Values
entering YAML, TOML, JSON, shell, or Markdown use a declared context encoder or a constraint making
direct scalar insertion safe.

### What must be persisted

So that `add`, `restore`, `reconcile`, and reapply work after the bundle is gone: `InitialAnswers`
including per-slot and licensing digests; `additions`; `provenance`; and `installed`. Nothing else. No
`RenderInput`, no render identity, and no old source bytes, because every operation renders against the
**current** template and validates against the recorded inventory.

| Operation | Inputs | Sufficient? |
| --- | --- | --- |
| reapply | recorded answers vs bundle answers, field-wise | Yes |
| `restore` | current template + answers + additions → re-render → require hash equals inventory | Yes; this comparison *is* the render-contract check |
| `add` | answers + additions ∪ requested → re-render | Yes, with source unchanged |
| `reconcile` | new template + answers + additions → re-render | Yes; never reads old source |

## Project manifest

`.agentic-template/project.json` has three sections and no derived block.

```text
{
  "schema_version": 1,
  "answers": {                          # primary: recorded intent
    "project": {"name", "default_branch"},
    "profile": {"id", "requested"},     # requested is exact for custom, else the frozen expansion
    "settings": {...},
    "licensing": {"mode", "content_sha256"},   # digest only; never legal prose
    "slots": {"<slot>": {"mode", "content_sha256"}}
  },
  "additions": [...],                   # primary: explicit post-bootstrap additions
  "provenance": {                       # primary: historical facts
    "generation_path",
    "template_source_fingerprint",
    "maintenance": {"status", "retained_paths"}
  },
  "installed": [                        # primary: a record of what bootstrap wrote
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

The effective closure is recomputed from `profile.requested` plus `additions` against the current
catalog. The stable-ID contract forbids changing a capability's dependencies, so a closure change under
a nominally compatible catalog is a compatibility violation, reported as such rather than as manifest
corruption.

The manifest is excluded from `installed`; a self-referential hash is unsatisfiable. Its integrity
rests on the checksum, which detects truncation and casual editing and is not a security control.

The manifest never contains product prose or legal text, input source paths, repository owner or name,
timestamps, machine-specific absolute paths, secrets or secret-presence claims, live GitHub state, any
claim about a seed-once file's current content, or a hash that would make seed-once content managed.

On Copier projects, version and lineage stay in `.copier-answers.yml`. GitHub snapshots record content
identity only.

### Corrupt or unreadable manifest

Exit 2, with ordered guidance, and never a suggestion to run `restore` — `restore` reads the manifest
to decide what to write, so it cannot repair its own dependency. Guidance order: `git restore
.agentic-template/project.json` if tracked and a good version exists; `recover` if a journal is
pending — which the classifier already reported first; re-run `apply` from the original bundle only if
the project is still a recognized scaffold; otherwise reconstruct by hand using `plan` output.

### Schema lifetime

Every v1 engine reads every valid schema-version-1 manifest. Compatible updates may add optional fields
with deterministic defaults but may not reinterpret existing fields or require a new field from an old
manifest. An unknown newer schema fails before any write.

## Total classification

Facts are computed independently, then mapped by a total function. There is no first-match prose whose
earlier checks can shadow later branches.

```text
Facts = { journal    : Maybe TransactionPhase
        , manifest   : Absent | Unparseable | UnknownSchema | Present RecordedProjectState
        , topology   : Safe | Unsafe [Path]
        , protection : Ok | CanonicalTemplateRemote
        , scaffold   : Recognized GenerationPath | NotScaffold
        , conflicts  : None | CopierConflicts [Path]
        , answers    : NotApplicable | Same | Differs [FieldDelta]
        , source     : NotApplicable | Same | Changed
        , closure    : NotApplicable | Resolvable [CapabilityId] | Incompatible [Reason]
        , inventory  : NotApplicable | Verified | Drifted [Path] }
```

`inventory` compares observed normalized bytes and owner execute bits against recorded
`InventoryEntry` values. **It never renders.** That independence from `source` is what makes both
`TemplateChanged` and `ManagedDrift` reachable.

```text
ApplyDecision =
    RecoveryRequired          TransactionPhase
  | UnsafeTarget              [Path] | CanonicalTemplateRemote
  | UnsupportedTarget         Reason
  | ManifestInvalid           Reason
  | CatalogIncompatible       [Reason]
  | CopierConflictsPresent    [Path]
  | InitialInstall            GenerationPath
  | InputChanged              [FieldDelta]
  | TemplateChanged           GenerationPath
  | ManagedDrift              [Path]
  | Equivalent
```

`RenderContractViolation` is deliberately **not** a member. It is not a classification of observed
state but a failure discovered when a re-render disagrees with a recorded inventory hash under an
unchanged source. It arises inside `restore`, `add`, and `reconcile`, always exits 2, and is reachable —
unlike revision 4's B7, which the manifest-integrity rule consumed first.

### Precedence, with a preimage witness for each constructor

Precedence exists only where two facts could both be true; every constructor below has a nonempty
preimage, so none is shadowed.

| Order | Constructor | Witness |
| --- | --- | --- |
| 1 | `RecoveryRequired` | `journal = Just p`. Checked **before** the manifest is trusted, so an interrupted operation on a stale manifest reports `recover`, not corruption |
| 2 | `UnsafeTarget` | `topology = Unsafe ps` or `protection = CanonicalTemplateRemote` |
| 3 | `UnsupportedTarget` | `manifest = Absent, scaffold = NotScaffold` — populated and manifest-free |
| 4 | `InitialInstall` | `manifest = Absent, scaffold = Recognized p` |
| 5 | `ManifestInvalid` | `manifest ∈ {Unparseable, UnknownSchema}` |
| 6 | `CatalogIncompatible` | `closure = Incompatible rs` |
| 7 | `CopierConflictsPresent` | `conflicts = CopierConflicts ps` |
| 8 | `InputChanged` | `answers = Differs d` |
| 9 | `TemplateChanged` | `source = Changed`; reachable because `inventory` never depended on rendering |
| 10 | `ManagedDrift` | `source = Same, inventory = Drifted ps` |
| 11 | `Equivalent` | every applicable fact `Same`, `Verified`, or `Resolvable` |

### Decision to outcome

| Decision | Exit | Next action |
| --- | --- | --- |
| `RecoveryRequired` | 2 | `recover` |
| `UnsafeTarget` | 1 | The named paths, or operate outside the template repository |
| `UnsupportedTarget` | 1 | The migration contract; v1 does not bootstrap a populated project |
| `ManifestInvalid` | 2 | Manifest recovery guidance |
| `CatalogIncompatible` | 2 | The template broke its stable-ID contract; report upstream |
| `CopierConflictsPresent` | 1 | Resolve Copier conflicts, then retry |
| `InitialInstall` | per gate | Proceed |
| `InputChanged` | 1 | Mechanical field deltas name `add` or deferred reconfiguration; content field deltas name editing the installed file in place |
| `TemplateChanged` | 1 | Copier: `plan-reconcile`, `reconcile`. Snapshot: `git restore` the reported paths |
| `ManagedDrift` | 1 | `restore` |
| `Equivalent` | per gate | Proceed |

Because `InputChanged` carries field deltas rather than a digest comparison, the diagnostic names the
field that changed. Revision 4 needed two fingerprints to distinguish mechanical from content changes;
field deltas distinguish them and localize them.

`TemplateChanged` on a GitHub snapshot is a **local modification**, not an update. Snapshots have no
Copier lineage and no update lifecycle, so `reconcile` is unavailable to them and the only next action
is to restore the reported engine or catalog paths from git. Revision 4 offered snapshots `reconcile`
"to accept the modification deliberately", which silently created the local template-evolution lifecycle
that the snapshot boundary exists to forbid.

## Operation semantics

Normative. Every precondition, diagnostic, and test must agree with this table.

| Operation | `answers` | `additions` | `provenance.template_source_fingerprint` | `maintenance` | `installed` | Renders? |
| --- | --- | --- | --- | --- | --- | --- |
| `init` | — no target | | | | | No |
| `status` | read | read | read and compare | read | read and verify | No |
| `plan`, `plan-add`, `plan-restore`, `plan-reconcile` | read | read | read and compare | read | read and verify | Yes, discarded |
| `apply` → `InitialInstall` | **sets** | sets `[]` | **sets** | **sets** | **sets** | Yes |
| `apply` → `Equivalent` | unchanged | unchanged | unchanged | unchanged | unchanged | Yes, for verification |
| `add` | unchanged | **extends** | must equal; unchanged | unchanged | **updated** | Yes |
| `restore` | unchanged | unchanged | must equal; unchanged | unchanged | **unchanged** | Yes, must match inventory |
| `reconcile` | unchanged | unchanged | **advances** | unchanged | **updated** | Yes |
| `recover` | restored | restored | restored | restored | restored | No |

`restore` records nothing at all. It writes bytes whose hash and mode already appear in `installed`,
so the inventory is unchanged by construction and a single-path repair cannot certify a mixed state.

`add` requires the current template-source fingerprint to equal the recorded one, and names
`reconcile` when it does not, so a capability addition cannot silently absorb a template update.

## Readiness and gating

### Structured readiness result

`check-project-readiness.py` and the engine share one contract, so gating comparison is structural
rather than textual.

```text
ReadinessResult
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
  next_action
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
    -> ReadinessResult   -- baseline, captured before staging
    -> ReadinessResult   -- expected, computed from the render result
    -> ReadinessResult   -- observed, after installation
    -> GateResult
```

Three comparisons, each proving one thing, evaluated in order:

1. **Artifact verification.** Every planned path's observed normalized hash and owner execute bit must
   equal the plan's new values. No exemption applies, and this precedes all exemption logic, so a
   defective installation cannot hide behind a scaffold exemption.
2. **`validate-template.py` must succeed.** No exemptions.
3. **Readiness comparison**, by operation:

| Operation | Rule |
| --- | --- |
| `InitialInstall` | `observed` blocking multiset must **equal** `expected` blocking multiset, and `expected` must contain exactly the placeholder findings predicted for the bundle's declared `scaffold` slots. Equality, not containment; pre-bootstrap findings are not inherited |
| `Equivalent` | No filesystem change occurred, so `observed` must equal `baseline` |
| `add`, `restore`, `reconcile` | For every finding identity, `count(observed) ≤ count(baseline)`. Genuinely pre-existing findings are retained; none may be introduced or worsened |

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

Anything in that list requires a schema or major-version migration with preview, collision detection,
and explicit ownership transfer.

This closes a real dead end rather than relaxing the gate. Without the rule, an update that adds a
required seed-once file has no good outcome: if the new checker reports it in both baseline and
observed, reconciliation gate-passes into permanent unreadiness; if the obligation activates only after
the new manifest is installed, the finding is observed-only and reconciliation rolls back. Neither
creates the file, because `reconcile` may not write seed-once paths. The previous review correctly
identified that the multiset rule is not the cause and must not be weakened to compensate.

Enforcement: `validate-template.py` compares the live readiness rule set against a frozen v1 baseline
fixture recording each rule's identity, severity, and owned path class. A rule that becomes blocking,
or a new blocking rule over adopter-owned paths, fails source validation.

## Input boundary

Three disjoint classes. Revision 4 violated this by putting `source-ci-allowlist.json` in all three at
once — fingerprinted, validated by generated-project template validation, and excluded by Copier while
also deleted by snapshot install — so a Copier project could never match its own recorded fingerprint
and a snapshot could fail its own installation gate.

| Class | Members | Retained in generated projects? | In `template_source_fingerprint`? | Validated by |
| --- | --- | --- | --- | --- |
| Generated-lifecycle | Engine modules, catalog, core definitions and static blobs, schemas, `profiles.json`, compatibility fixture | Yes, both paths | **Yes** | `validate-template.py`, in the generated project |
| Source-only | Source test suites, workflow fixtures, `source-ci-allowlist.json`, historical specs, the readiness-rule baseline | No | **No** | Source-only fixtures, in the template repository |
| Cleanup-only | `maintenance-artifacts.json` | No — removed after use | **No** | Source-only fixtures |

The fingerprint therefore contains only inputs that both generation paths actually retain, which is the
property revision 4 lacked.

`maintenance-artifacts.json` does not list itself; a file cannot record its own hash. Snapshot install
consumes it, performs cleanup, and removes it unconditionally as the final cleanup operation. Copier
excludes it by static configuration.

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
setting for an existing capability must match the persisted value or the operation fails.

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
to named typed slots; document fragments; and fixture cases. Definitions are data: no command
execution, no Python object loading, no network, no environment reads, no arbitrary target paths.
Settings must be declared non-secret.

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
| Template inputs | Engine, catalog, render sources, validators, skills, static contracts, `NOTICE.md`; Copier updates and merges these |
| Bootstrap-managed output | Compiled CI, selected capability artifacts, durable operational documents; exact hashes enforced; `restore` repairs them |
| Manifest | `.agentic-template/project.json`; managed but excluded from its own inventory |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, `CONTRIBUTING.md`, root licence, project-validation workflow; installed once, never regenerated in v1 |
| Adopter files | Product code and documentation, `.gitattributes`, `.gitignore`, unrelated workflows, everything outside declared ownership |
| Template-maintenance artifacts | Source-only class from the input boundary |

No path belongs to two classes; source validation rejects duplicate, nested, and case-colliding
declarations. `CONTRIBUTING.md` and `.gitattributes` are adopter-owned because both are ordinary
adopter configuration. The four `docs/*.md` operational documents are managed because they describe
template mechanics the adopter does not author.

## Generation paths

Copier excludes bootstrap-managed output, seed-once output, source-only inputs, and cleanup-only inputs.
The current `_skip_if_exists: scripts/validate-project.py` entry is removed, since seed-once ownership
subsumes it and two mechanisms over one path give it two owners. The stale `tools` exclude, matching no
existing path, is removed.

GitHub's template operation copies the source tree unchanged, so initial install replaces seed
placeholders, removes unselected capability artifacts, replaces source CI with compiled CI, removes
source-only and cleanup-only inputs, and finally removes the cleanup inventory itself.

Recognized scaffold, per path:

- **Copier:** `.copier-answers.yml` present, no manifest, every seed-once path absent or byte-identical
  to the template's scaffold content.
- **GitHub:** no `.copier-answers.yml`, no manifest, every seed-once path byte-identical to a known
  scaffold hash for a released template version.

Anything else classifies as `UnsupportedTarget`. Unexpected bytes at any path proposed for replacement
or deletion block the whole mutation; bootstrap never treats "looks like a template file" as evidence.

`docs/template-updates.md` states plainly that a GitHub-generated project receives no template updates
to managed artifacts and that adopting Copier lineage is deferred work.

## Transaction interpreter

The guarantee is **recoverable planned-path transactionality**: every planned path can be returned to
its pre-operation state. Bootstrap does not provide atomic multi-file visibility — a concurrent reader
can observe a partially installed plan — and does not claim it. Documentation that previously said
managed documents update "atomically" now says "in the same recoverable planned-path transaction."

### Phases

Three phases. Gating happens **inside** `MUTATING`, so committed cannot precede gated.

| Phase | Durably recorded | Target paths possibly changed | Recovery |
| --- | --- | --- | --- |
| `PLANNED` | Journal with the full operation list and expected old and new hashes and modes | None | Discard staging; nothing to restore |
| `MUTATING` | Same, phase advanced | Any planned path | **Roll back every planned path** |
| `SEALED` | Same, phase advanced after gating passed | All planned paths installed and verified and gated | **Finish cleanup forward**; never roll back |

Revision 4 recorded `COMMITTED` before gating and mapped it to cleanup-only recovery, so a crash during
gating preserved an installation that never passed its gate, and an interrupted rollback completed
forward. No fourth phase is needed: an `INSTALLED_UNGATED` phase would have the same recovery action as
`MUTATING`.

### Ordering

1. Acquire the lock.
2. Classify, and validate inputs, definitions, topology, recorded hashes, and rendered bytes.
3. Stage every new file **adjacent to its destination parent**, inside the target tree. Write, fsync
   each file, fsync the staging directory.
4. Copy every replaced or deleted planned path into backups. Fsync each backup, then its directory.
5. Write the journal in `PLANNED` — temp file, fsync, rename, fsync parent. No target path touched yet.
6. Advance to `MUTATING` by the same atomic replacement.
7. Install each operation in deterministic order, fsyncing each replaced file and its parent.
8. Re-read and verify every planned path against the plan.
9. Run `gate`. **On failure, roll back immediately** — before any cleanup and before the hook.
10. Advance to `SEALED`.
11. Remove backups, remove the journal, fsync the state directory, release the lock.
12. Run the adopter hook once and report its point-in-time result.

Staging adjacent to each destination parent is required because a repository may span mount boundaries;
revision 4's single staging directory "on the target's filesystem" does not guarantee same-filesystem
replacement for every path.

Every journal transition is a complete record written to a temp file, fsynced, renamed, and followed by
a parent fsync. Revision 4's "update the journal and fsync" permits a torn document if implemented as
truncate-then-write. Creates and deletions represent their absent side explicitly, as `null`, rather
than by omission.

### Lock

The lock is a single **never-unlinked** file at the per-worktree administrative path. It is opened
`O_CREAT | O_RDWR | O_NOFOLLOW` — **not** `O_EXCL` — and then acquired with
`flock(LOCK_EX | LOCK_NB)`. It is acquired by every mutating command and by `recover`, before staging.

Revision 4 specified `O_CREAT | O_EXCL` plus an advisory flock, which cannot work: `O_EXCL` fails when
the file exists, so an abandoned lock file from a killed process is never opened and its flock is never
tested. It also permitted unlink-and-recreate, which yields two live lock domains on different inodes,
and placed the lock in-tree where `git clean -fdx` can unlink it while held.

Because a git working tree is required and `--state-dir` is removed, the lock's location is a pure
function of the verified target. Two invocations against the same target contend on the same inode by
construction.

The lock records holder PID, operation, and target identity. `status` reports a held lock. A stale
flock from a dead process is acquired normally, so an abandoned lock is self-healing.

### Journal and state location

State lives at the per-worktree administrative path, resolved from the **verified** target:

```text
git -C <verified target> rev-parse --path-format=absolute --git-path agentic-template
```

`--git-path` is worktree-aware, so linked worktrees neither serialize each other nor recover against
each other's plans. `--path-format=absolute` removes any dependence on the invoking working directory;
a relative result from an older git is resolved against the verified target and re-verified.

| Situation | Behavior |
| --- | --- |
| Primary worktree | Resolved administrative path |
| Linked worktree | Per-worktree path, independent of the primary |
| Submodule | The submodule's own administrative path; never the superproject's |
| Bare repository | `BOOTSTRAP_TARGET_BARE_REPOSITORY` |
| Not a git working tree, or git unavailable | `BOOTSTRAP_TARGET_NOT_GIT_WORKTREE` |

**Target identity** is normatively the verified absolute worktree root path together with that
directory's device and inode. The journal records it, and `recover` refuses a target whose identity
does not match.

Recovery evidence for tracked files also exists in git. When backups are missing or their hashes do not
match the journal, `recover` fails with `BOOTSTRAP_RECOVERY_EVIDENCE_MISSING` and directs the operator
to `git status` and `git restore` rather than guessing.

### Path safety and its threat model

Every backup, replacement, and rollback is anchored to the verified target root:

- open the target root, then **walk every path component** with descriptor-relative `openat`-style
  calls using `dir_fd`, `O_DIRECTORY`, and `O_NOFOLLOW`, so no ancestor may be a symlink;
- open target files with `O_NOFOLLOW`;
- immediately before each mutating step, **re-resolve the parent from the root** and compare its device
  and inode against the held descriptor; and
- verify the existing file's device, inode, and normalized hash immediately before replacing it, under
  the held descriptor.

Revision 4 opened only the planned path's parent with `O_NOFOLLOW`, which constrains that final
component alone and leaves every ancestor substitutable, and relied on `fstat` of a held descriptor,
which proves inode identity but not continued attachment at the intended path.

**Threat model, stated narrowly.** These measures defend against accidental symlinks, stale state,
concurrent bootstrap invocations, and interrupted operations. They do **not** defend against a local
adversary with concurrent write access to the target during a mutation. Such an adversary already holds
the privileges bootstrap is exercising, and Python 3.11 on Linux and macOS cannot provide a stronger
guarantee without platform-specific primitives outside this design's portability commitment. Any
mismatch aborts the transaction and, once past `PLANNED`, triggers rollback.

## Restore, add, and reconcile

### `restore`

Preconditions, all pure except the lock:

- the lock is held and no journal is pending;
- the manifest parses, its schema is known, and its checksum verifies;
- topology is safe;
- the current `template_source_fingerprint` equals the recorded one — otherwise refuse and name
  `reconcile`;
- the recorded closure resolves exactly against the current catalog;
- every requested path appears in `installed`; and
- for every requested path, the re-rendered `{sha256, mode}` **equals** the recorded `InventoryEntry`.

The last precondition is the safety property: `restore` can write only bytes the inventory already
certifies, so it cannot introduce content, and it records nothing, so it cannot create a mixed state.
A mismatch is `BOOTSTRAP_RENDER_CONTRACT`, exit 2 — the reachable render-contract check.

`restore --path` is refused when a named path is not managed, and touches no seed-once or adopter path.

### `add`

Requires the recorded fingerprint to equal the current one, the closure to resolve, no drift, and no
pending journal. Extends `additions`, re-renders, and updates `installed`. Advances no other recorded
value. Settings for existing capabilities must match; removal and replacement requests fail naming the
deferred lifecycle.

### `reconcile`

Available only on the Copier path. Separated into five stages, so no stage depends on bytes that are no
longer available:

1. **Verify the old contract.** Manifest parses, schema known, checksum verifies, `installed` verified
   against observed bytes — or drift explicitly accepted, below.
2. **Recognize the new source.** Compute the current fingerprint; require the recorded closure to
   remain resolvable without adding or removing an ID.
3. **Compile candidate output.** Render from the new template plus recorded answers and additions.
4. **Apply drift policy.** Blocked on drift unless `--overwrite-drift` with a valid plan digest.
5. **Accept.** Install, gate, and record the new fingerprint and inventory.

Nothing in this sequence reads old source bytes. It may not re-expand a profile, change answers or
additions, modify seed-once or adopter paths, select a template version, merge drift, or invoke a
migration.

### Drift policy by operation

| Operation | With managed drift present |
| --- | --- |
| `status`, every plan command | Reports it; never blocked |
| `recover` | Proceeds; it restores planned paths regardless |
| `apply` | `ManagedDrift`; next action `restore` |
| `add` | Blocked; next action `restore` |
| `restore` | Its purpose |
| `reconcile` | Blocked unless `--overwrite-drift` with a valid plan digest |

## Plan digest

`reconcile --overwrite-drift` destroys adopter edits to managed files, so it is bound to the preview
that authorized it. There is no interactive confirmation path, so the contract is identical in a
terminal and in automation.

`plan-reconcile --overwrite-drift --out FILE` writes a plan document containing the target identity,
the resolved operation list, each path's expected old and new hash and mode, and the source fingerprint
the plan was computed against, plus

```text
plan_digest = tagged(b"reconcile-plan", canonical_json(plan_document_without_digest))
```

`reconcile --overwrite-drift --plan FILE` re-reads the plan and recomputes its digest, rejecting any
mismatch; verifies the recorded target identity; recomputes the plan from current state and requires an
exact match; and only then proceeds. `--overwrite-drift` without `--plan` is a usage error.

## The adopter hook

The hook is adopter-owned, may be any executable, and is invoked directly rather than through Python.

**Invocation rule.** The hook runs exactly once, and only after a mutating command's gating validation
has succeeded, or on an `Equivalent` decision. It runs **zero** times on preflight or classification
refusal, on rollback, during `recover`, on any plan command, on `status`, and on `init`. Revision 4's
"exactly once per mutating invocation" was false in every refusal and rollback case.

A failing hook produces exit 1 with the installation retained, reported as "bootstrap files were
installed; the repository is not locally ready". Its result is **point-in-time evidence**: never written
to the manifest, never cached, never replayed. `status` does not execute it and claims no outcome,
reporting mechanical readiness and then `adopter hook: not evaluated; run python3
scripts/validate-repository.py`.

## CLI contract

```text
python3 scripts/bootstrap-project.py init --output PATH [--init-answers FILE]

python3 scripts/bootstrap-project.py status          [--target PATH]
python3 scripts/bootstrap-project.py plan            --answers PATH/bootstrap.json [--target PATH]
python3 scripts/bootstrap-project.py plan-add        --answers addition.json [--target PATH]
python3 scripts/bootstrap-project.py plan-restore    [--path PATH]... [--target PATH]
python3 scripts/bootstrap-project.py plan-reconcile  [--target PATH] [--overwrite-drift --out FILE]

python3 scripts/bootstrap-project.py apply     --answers PATH/bootstrap.json [--target PATH]
                                               [--leave-maintenance-artifacts]
python3 scripts/bootstrap-project.py add       --answers addition.json [--target PATH]
python3 scripts/bootstrap-project.py restore   [--path PATH]... [--target PATH]
python3 scripts/bootstrap-project.py reconcile [--target PATH] [--overwrite-drift --plan FILE]

python3 scripts/bootstrap-project.py recover   [--target PATH]
```

`--target` is accepted by every command that inspects or mutates a project; `init` accepts none. There
is no `--state-dir`: state location is a pure function of the verified target.

Commands are thin adapters. Each decodes an `Intent`, invokes the same `facts`/`classify`/`compile`
pipeline, and differs only in which decisions it accepts and what it is permitted to record.

`init` writes a complete reviewable bundle, using a temporary sibling and installing only after
validation.

`status` reports generation path, frozen profile, additions, effective closure, unreplaced slots derived
from file markers, every drifted managed path, recorded and current fingerprints, maintenance status
with retained paths, activation requirements, and any pending journal or held lock.

`--leave-maintenance-artifacts` is the supported override for a cleanup inventory that no longer
matches. It skips cleanup, records the retained paths, and transfers them to adopter ownership; no
later cleanup command exists, because removing an adopter-owned file needs none. Readiness reports the
skip as `informational`. The outcome enters `RenderInput`, so it also changes what the documentation
says.

### Exit semantics by command family

One global rule contradicted `status`, so semantics are defined per family.

| Family | Commands | 0 | 1 | 2 |
| --- | --- | --- | --- | --- |
| Mutating | `apply`, `add`, `restore`, `reconcile`, `recover` | The complete canonical command would now succeed | User-correctable: refused classification, unmet precondition, or an installed project that is not locally ready | Usage, contract, manifest, render-contract, internal, or recovery failure |
| Inspection | `status` | The project was described, whatever its state | *Never returned* | Cannot describe: unreadable manifest or invalid internal state |
| Planning | `plan`, `plan-add`, `plan-restore`, `plan-reconcile` | A plan was produced, including an empty one | Preconditions unmet, so no plan exists | Usage, contract, or internal |
| Bundle | `init` | Bundle written | Input invalid or output location non-empty | Usage or internal |

## Diagnostics

```text
BOOTSTRAP_INPUT_*      BOOTSTRAP_TARGET_*      BOOTSTRAP_TRANSACTION_*   BOOTSTRAP_LICENSE_*
BOOTSTRAP_PROFILE_*    BOOTSTRAP_TEMPLATE_*    BOOTSTRAP_RECOVERY_*      BOOTSTRAP_MANIFEST_*
BOOTSTRAP_CAPABILITY_* BOOTSTRAP_DRIFT_*       BOOTSTRAP_ACTIVATION_*    BOOTSTRAP_RENDER_*
BOOTSTRAP_LOCK_*       BOOTSTRAP_INTERNAL_*
```

Every user-correctable diagnostic names the affected input, capability, or repository-relative path and
one next action. **Every next action must name a command or step that exists and is reachable for the
target's generation path**; a source fixture enumerates the diagnostic table and asserts this, so no
diagnostic can recommend an unavailable operation — the defect that let revision 4 offer snapshots
`reconcile`. Diagnostics never include secret values. Independent preflight errors are reported together
in the normative finding order; mutation and recovery failures stop at the first point where continuing
could destroy evidence.

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

- `plan` reports the exact create, replace, and delete set without mutation.
- `apply` installs only from a scaffold recognized for the target's generation path, and classifies a
  populated manifest-free target as `UnsupportedTarget`, naming the migration contract.
- Gating requires `validate-template.py` to succeed, every planned artifact to verify exactly, and the
  observed blocking findings to equal exactly those predicted for declared `scaffold` slots.
- The hook then runs once; neither its failure nor an expected scaffold finding rolls back.
- Exit 0 only when the complete canonical command would succeed, so any `scaffold` slot yields exit 1
  naming the remaining slots.
- An `Equivalent` reapply changes no file, still runs the readiness boundary and the hook once, and
  carries the same exit meaning — so an all-`scaffold` reapply also exits 1.
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

- `plan-add` previews; `add` applies transactionally.
- Dependencies resolve into the closure; requested additions are recorded separately.
- The frozen profile expansion is unchanged.
- Existing settings cannot change; a satisfied request is a no-op only when settings do not conflict.
- Removal or replacement fails naming the deferred lifecycle.
- `add` requires the recorded template-source fingerprint to equal the current one, naming `reconcile`
  otherwise, and updates only `additions` and `installed`.

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

- The sequence is `copier update`, `plan-reconcile`, `reconcile`, canonical validation.
- Copier selects and merges inputs; reconciliation compiles derived outputs.
- The closure and settings are preserved exactly.
- `reconcile` is the only operation that advances `template_source_fingerprint`, per the
  operation-semantics table.
- It adds and removes no capability, changes no setting, re-expands no profile, and merges no file.
- Copier conflict evidence or an incompatible catalog blocks all writes.
- Drift blocks it unless `--overwrite-drift` is given with the digest from
  `plan-reconcile --overwrite-drift`, which `reconcile` revalidates.
- **`reconcile` is unavailable on the GitHub path.** A snapshot with a changed fingerprint is diagnosed
  as a local modification whose next action is `git restore`.

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
- The journal records target identity and every planned path's expected old and new hash and mode, with
  absent sides explicit.
- Recovery is phase-dependent: `PLANNED` discards staging, `MUTATING` rolls back, `SEALED` finishes
  cleanup forward. No phase both rolls back and finishes forward.
- A gating failure rolls back immediately, before cleanup and before the hook.
- A pending journal blocks later mutations; `recover` refuses a mismatched target identity.
- Recovery evidence survives `git clean -fdx`.
- A live writer cannot race recovery and two recoveries cannot race.
- Hook-created artifacts outside the planned set are not removed.
- The guarantee is recoverable planned-path transactionality, not atomic multi-file visibility.

### US-13: Resolve managed drift

- `status` reports every drifted managed path without mutation and without executing the hook.
- `plan-restore` shows the exact bytes; `restore` applies transactionally.
- `restore` requires the recorded fingerprint to equal the current one and every re-rendered artifact to
  equal its recorded inventory entry.
- `restore` records nothing and touches no seed-once or adopter path.
- A fingerprint mismatch refuses and names `reconcile`; an inventory mismatch is `BOOTSTRAP_RENDER_CONTRACT`.
- `restore --path` restores a subset and cannot change any recorded field.
- Drift blocks neither `status`, nor any plan command, nor `recover`.

## Decision record

| Topic | V1 decision | Future change, if viable |
| --- | --- | --- |
| Recorded identity | One fingerprint; answers stored as values; no render identity | None; deletion is the simplification |
| Render oracle | The recorded inventory | None |
| Classification | Total function over independent facts | None |
| Bootstrap result | Installation and locally ready reported separately; exit 0 requires both | Staged readiness reporting |
| Content completeness | Adopter file or explicit `scaffold` | Inline prose fields |
| Slot completion | Derived from declared markers | Structured metadata if derivation fails |
| Hook sentinel | Byte-level detection | Declarative command hooks |
| Profile semantics | One-time snapshots | Live profiles or override policies |
| Lifecycle | Install, additive change, same-contract repair, Copier reconciliation | Removal, replacement, reconfiguration |
| Destructive reconciliation | Bound to a recomputed plan digest | None |
| Gating | Scoped to introduced findings; exact scaffold equality on install | Opt-in strict mode gating on the hook |
| Hook evidence | Point-in-time; never persisted or replayed | Cached evidence with explicit invalidation |
| Template evolution | Compatible updates may not add unsatisfiable obligations | Migration with preview and ownership transfer |
| Target | A git working tree is required | Reinstate non-git targets with a state-namespacing rule |
| Path safety | Root-anchored no-follow walk; narrow threat model | Platform-specific hardening |
| Snapshot updates | None, including local reconciliation | Snapshot adoption into Copier lineage |
| Populated manifest-free projects | Stay on the pre-bootstrap release | A named v1 compatibility release |
| Secret diagnosis | Available, or unavailable with likely causes | Authoritative diagnosis in a GitHub doctor |
| Licensing | Explicit; digest fingerprinted; audit gates all modes | SPDX, SBOM, richer automation |
| Workflow validation | Bounded standard-library checks in the generated project; a real parser only in source fixtures | A portable structured parser |
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

**Graph normal form:** trigger events with their filters, sorted; concurrency group and
cancel-in-progress; job IDs with sorted `needs`; effective per-job permissions with workflow defaults
resolved in; `environment` references; `runs-on`, with matrices expanded into the concrete generated job
set; `container` and `services` images with pinned digests or tags; `if` conditions, whitespace
normalized; called-workflow references with their complete `with` inputs and `secrets` declarations,
including whether `secrets: inherit` appears; `timeout-minutes`; and `continue-on-error`.

**Step normal form**, with stable identity and order: each step's identity is its zero-based index
within its job plus its `name` when present, and steps compare in that order. For a `uses` step: the
action reference, its pin — the 40-character SHA where present, plus any tag comment — and the
**complete canonical `with` map**. For a `run` step: the shell and a stable hash of the command text
after normalizing line endings and stripping trailing whitespace. For both: `if`, the **complete
canonical `env` map including values**, and `working-directory`.

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

**Parser.** This is a source-only fixture, so it is not bound by the generated project's
standard-library constraint. It requires a real YAML parser, which the repository lacks: `flake.nix`
provides bare `python3` and `actionlint`, and bare `python3` has no PyYAML. The activation batch adds
`python3.withPackages (ps: [ ps.pyyaml ])` to the dev shell and the corresponding flake check.

The loader contract is specified, because default PyYAML semantics are not GitHub Actions semantics:
`yaml.SafeLoader` with duplicate mapping keys rejected by an explicit constructor override; the YAML 1.1
implicit boolean set treated as strings for `on`, `if`, and permission values, so `on: [push]` and
`on: {push: null}` and the bare `on:` key are normalized to one representation and `no`/`off`/`yes`
remain strings; and timestamps and sexagesimals disabled. `actionlint` continues to lint the source and
every generated workflow fixture. No claim is made that a standard-library checker can generally parse
Actions YAML; `check-project-readiness.py`'s checks remain deliberately bounded — presence, recognizable
`workflow_call`, canonical command, absence of secret passing and privileged environment declarations,
and the managed caller's exact hash — and are documented as bounded rather than semantic.

## Validation boundaries

### `scripts/validate-template.py`

Validates reusable machinery without assuming a bootstrapped instance: bundle, addition, and manifest
schemas; the `RenderInput` schema and renderer purity; profiles and the complete capability catalog;
dependency topology; setting declarations and defaults; output ownership, declared kinds, and slots;
canonical path grammar across every declared path; and the stable-ID compatibility fixture. Python 3.11
standard library only; executes no capability content and no adopter hook.

It does **not** validate source-only inputs. Revision 4 required it to validate the source-CI allowlist,
a file no generated project retains.

### `scripts/check-project-readiness.py`

Emits a `ReadinessResult`. Without a manifest it behaves as today and reports the project
unbootstrapped at `informational` severity. With a manifest it additionally checks schema, checksum, and
internal topology; the frozen expansion, additions, and closure; managed artifact modes and normalized
hashes; the licensing decision and required preserved provenance; required durable documentation; hook
presence and mode at the canonical path; the seeded workflow's bounded contract; activation
declarations; retained maintenance paths, informationally; and the absence of declared placeholder
markers in any slot.

A fingerprint mismatch is reported as "reconcile required" on the Copier path and as "local template
modification" on the GitHub path. An inventory mismatch is drift, with `restore` as the next action.

### `scripts/validate-project` and `scripts/validate-repository.py`

`scripts/validate-project` is the canonical adopter executable, invoked directly. Native Windows
execution is not a v1 guarantee.

`scripts/validate-repository.py` remains the canonical ordered boundary: template contract, project
readiness, adopter project validation. Stages 1 and 2 feed gating; stage 3 is the adopter's, and its
failure means the project is not locally ready without meaning the installation was wrong. Source-only
fixtures and matrix suites are not added to this portable boundary.

## Licensing and provenance

One explicit licensing choice, no default, no scaffold. For `retain-apache-2.0` the source Apache-2.0
text remains root `LICENSE`. For `provided-project-license` and `private` the adopter's text becomes
root `LICENSE`, `NOTICE.md` is kept, and the template Apache-2.0 text is retained at
`LICENSES/Apache-2.0.txt`.

The supplied bytes are covered by `answers.licensing.content_sha256`, so changing legal text is visible
to classification as an `InputChanged` field delta. The bytes themselves are never stored.

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
  populated manifest-free contract;
- `docs/capabilities.md`: frozen expansion, additions, closure, displayable settings, dependencies; and
- `docs/github-setup.md`: required secrets, the two preflight states with likely causes including fork
  and Dependabot runs, Actions and ruleset steps, and the distinction between release and merge gates.

Each header names the document managed and directs project-specific prose elsewhere. Additions and
reconciliation update them in the same recoverable planned-path transaction as related artifacts. Direct
edits are drift repaired by `restore`.

## Cleanup inventory

`.agentic-template/maintenance-artifacts.json` declares the source-only paths that a GitHub snapshot
must remove: source test suites, the Copier smoke workflow, the source-CI allowlist, the readiness-rule
baseline, and historical specs. Each entry records the path, its expected source hash or tree hash, and
whether it is a regular file or a directory tree. Entries may not overlap any other ownership class, and
the inventory does not list itself.

- Copier excludes the declared paths and the inventory by static configuration.
- Snapshot install removes only entries whose complete bytes match the declared shape, then removes the
  inventory itself as the final cleanup operation.
- A modified, missing-with-children, unsafe, or partially matching entry blocks cleanup, reports the
  exact path, and names `--leave-maintenance-artifacts`.
- A skipped cleanup records the retained paths and transfers them to adopter ownership.
- No later operation uses the inventory, which no longer exists in the generated project.

## Migration from the pre-bootstrap template

V1 changes the canonical hook path from `scripts/validate-project.py` to `scripts/validate-project` and
introduces the manifest. This is a breaking template-contract change against the **current repository**,
released with migration instructions, which `docs/prd.md` permits for a change that makes a conforming
project unready. Revision 1 already specified the extensionless path, so this is not a reversal of an
approved design decision.

### One steady state

Per the scope reduction above, a populated project that has no manifest **stays on the pre-bootstrap
lifecycle**:

- It keeps `scripts/validate-project.py`; the pre-bootstrap contract continues to accept it.
- It pins the last pre-bootstrap template release, named explicitly in the v1 release notes, and does
  not update past it.
- `validate-template.py`, `check-project-readiness.py`, and `validate-repository.py` continue to accept
  it, reporting it unbootstrapped at `informational` severity.
- V1 is for newly generated projects. An existing project that wants v1 generates a new project and
  moves its content, which is an ordinary repository migration the adopter controls.

Revision 4 instead told such projects to run `copier update --vcs-ref <v1 tag>` **and** to pin the
pre-bootstrap release, which is not a steady state, and asserted without evidence that newly added
static excludes transfer ownership of previously copied paths. Copier's documented behavior does not
support that assumption: `_exclude` is operation-aware and `_skip_if_exists` still ensures paths during
update, so a destination-side exclusion added in v1 is not by itself proof that an adopter's modified
copy of a now-seed-once path survives.

### If an adopter renames the hook anyway

The rename is a legitimate local change and the release notes describe it, but it must not be mistaken
for adoption:

```text
git mv scripts/validate-project.py scripts/validate-project
chmod +x scripts/validate-project
```

**It does** move the hook to the path v1 expects. **It does not** create a manifest, bootstrap the
project, select capabilities, compile CI, install documentation, make any bootstrap operation
available, or give a snapshot an update lifecycle. The result remains a populated manifest-free project
that `apply` classifies as `UnsupportedTarget`.

Preconditions: a clean working tree; `scripts/validate-project.py` exists as a regular file;
`scripts/validate-project` does not exist. If both exist, stop — the adopter chooses which is
authoritative and no tool guesses. Verify the owner execute bit afterwards, because some checkout and
archive paths do not preserve it. Then run `python3 scripts/validate-repository.py`.

Rollback affects exactly two paths:

```text
git restore --staged --worktree scripts/validate-project.py scripts/validate-project
```

Revision 4 said `git restore scripts/` — too broad, since it would also discard unrelated adopter work
in that directory. No bootstrap state is created, so nothing else needs undoing.

A committed, content-addressed archive of a previous-release generated project — not a live tag
checkout — backs the migration fixture, so the test does not depend on history being fetched in every
CI checkout.

## Implementation batches

**One public release.** Development happens on an integration branch, `bootstrap-v1`, and reaches the
default branch through a **single activation merge**. Intermediate batches are review boundaries on that
branch and never touch the default branch.

Revision 4 claimed intermediate merges to the default branch were inert. They were not: batch 4 changed
Copier configuration and validation boundaries, both of which are public entry points, and
`.agentic-template/` content plus engine modules would ship into any snapshot created between batches
and stay frozen there. An integration branch removes the obligation to prove inertness rather than
attempting to satisfy it.

**Nine review boundaries.** Revision 4 said six while tabulating nine.

| # | Contents | Evidence before merge to the integration branch |
| --- | --- | --- |
| 1 | Determinism primitives; canonical JSON with strict decoding and surrogate rejection; path grammar; LF normalization; entry and tree hashing; all schemas; the `RenderInput` schema; `ReadinessResult`; ownership declarations | Unit and boundary fixtures for every primitive; schema round-trips; rejection fixtures |
| 2 | `render(RenderInput, BlobMap)`; resolver; typed slots; planner | Byte-identical repeated renders; purity under no ambient access; every `RenderInput` field affects output; cycle, collision, type, and slot detection; plan ordering |
| 3 | `facts`, `classify`, `readiness`, `gate` — all pure | Every `ApplyDecision` constructor reached by a witness; every gate rule; multiset comparison including repeated and worsened findings |
| 4 | Transaction interpreter: lock, journal phases, atomic transitions, root-anchored path walk, backups, rollback, `recover` | Injected failure at every phase and at gating; interrupted rollback; abandoned lock; concurrent mutation and concurrent recovery; ancestor-symlink and parent-rename substitution; worktree and submodule independence; bare and non-git refusal |
| 5 | CLI adapters; `init`, `plan`, `apply`; generation-path integration; marker derivation; cleanup inventory; seed-once installation; core-rendered CI | Both paths install `portable` from a fully supplied and from an all-`scaffold` bundle; the full decision table; reserved-marker rejection; licensing-digest field delta |
| 6 | Catalog, four capabilities, five profiles, contributions, compiled capability CI, secret preflights, compatibility fixture, readiness-rule baseline | Full profile matrix; `actionlint`; preflight structural-policy and local canary; activation skips |
| 7 | Durable documentation rendering | Per-profile content; retained-path effect on document text; documentation drift and repair |
| 8 | `add`, `restore`, `reconcile`, plan digest, migration fixture | Additive lifecycle; restore preconditions and render-contract violation; reconcile stages; digest binding and rejection; snapshot reconcile refusal; previous-release migration archive |
| 9 | Activation: create `scripts/bootstrap-project.py`, wire the boundaries, Copier configuration, enforce new readiness requirements, add the PyYAML dev-shell package and the Python 3.11 lane, publish documentation | The complete release gate |

### Pre-runtime gates

- `docs/prd.md`, `CONTEXT.md`, and ADR 0001 are updated before batch 9 changes any runtime behavior.
- The licensing and provenance audit completes before batch 5, which installs licence files.

### Release gate

Both generation paths pass the full profile matrix; Copier update coverage proves seed-once preservation
and derived reconciliation; the previous-release migration fixture passes; the transaction, lock,
recovery, and path-substitution suites pass; `actionlint` passes on the source and every generated
workflow fixture; source-CI conformance passes with no stale allowlist entry; preflight structural and
canary tests pass; the diagnostic reachability check passes; the readiness-rule baseline check passes;
the licensing audit is complete and reflected in the installed layout; the PRD, `CONTEXT.md`, and ADR
0001 reflect the approved boundary; repository formatting, linting, tests, builds, and source fixtures
pass under both the dev shell and the explicit Python 3.11 lane; and verification-before-completion and
substantive code review find no unresolved required issue.

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
- Absent versus empty file; empty directory outside the model; symlink rejection; execute-bit-only mode
  comparison.
- `RenderInput` perturbation: every field changes the render result, including `maintenance.retained_paths`
  and `default_branch`; an unselected capability's definition does not.
- Renderer purity: rendering succeeds with no filesystem, environment, clock, or network access, and a
  missing blob fails before rendering.
- `ReadinessResult` identity, normative sort order, and multiset comparison including a repeated finding
  and a worsened count.
- Manifest: three-section round-trip, checksum over the payload excluding the checksum, and the absence
  of any derived-recomputation gate on validity.
- `classify`: a witness for every constructor, and a proof that no constructor is shadowed.
- Journal phase transitions, atomic replacement, lock acquisition and release, plan-digest computation
  and rejection.

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
- Every sequence: `apply`; `apply → add → apply` reaching `Equivalent`; `apply → add → reconcile → apply`;
  `apply → reconcile → add`; `apply → restore → add`.
- `apply` after a Copier update with identical answers and healthy inventory reaches `TemplateChanged`,
  not `ManifestInvalid` and not `Equivalent`.
- `BOOTSTRAP_RENDER_CONTRACT` is reachable: with the fingerprint matching, perturb the recorded
  inventory hash for one path and prove `restore` reports it at exit 2.
- `UnsupportedTarget`: a populated manifest-free target is refused and pointed at the migration
  contract, including one that has had the hook renamed.
- `CatalogIncompatible`: a catalog whose dependency edges changed is reported as such, not as manifest
  corruption.
- A pending journal on a project whose recorded fingerprint no longer matches reports `RecoveryRequired`,
  not `ManifestInvalid`.
- Changing only the supplied licence bytes yields `InputChanged` naming the licensing field.
- `InputChanged` names the specific changed field for a mechanical change and for a content change.

Gating and scaffold:

- An all-`scaffold` install is retained, gate-passes, and exits 1 naming exactly the scaffolded slots.
- An all-`scaffold` **reapply** also exits 1, runs the readiness boundary, and runs the hook once.
- The install exemption is exact: a placeholder finding for an undeclared slot, or any extra blocking
  finding, gate-fails and rolls back.
- Artifact verification precedes exemptions: corrupt one planned artifact post-install and prove the gate
  fails despite a valid scaffold exemption.
- `add`, `restore`, and `reconcile` succeed on a project whose PRD is still a placeholder.
- A mutation that newly breaks readiness gate-fails even when an unrelated placeholder finding existed.
- A mutation that increases an existing finding's count gate-fails, which a set comparison would miss.
- The readiness-rule baseline rejects a catalog update that adds a required seed-once path or makes an
  informational rule blocking.
- A `file` input containing a reserved marker is rejected; a non-UTF-8 binary hook is accepted and its
  sentinel detected at byte level.

Transaction and recovery:

- Injected failure before the journal, in each phase, during gating, and during rollback.
- Gating failure rolls back before cleanup and before the hook.
- A crash during gating leaves `MUTATING`, and `recover` rolls back — proving ungated output cannot
  survive.
- A `SEALED` journal is completed forward by `recover`, never rolled back.
- Two concurrent mutations, and a mutation concurrent with `recover`: the second is refused by the lock.
- An abandoned lock file from a killed process is acquired normally rather than blocking forever.
- `recover` refuses a target whose identity does not match.
- Ancestor substitution: replace an intermediate directory with a symlink between planning and install
  and prove the operation aborts and never follows it.
- Parent rename: move a planned path's parent between planning and install and prove re-resolution
  detects it.
- Recovery evidence survives `git clean -fdx`.
- Linked worktree independence; submodule uses its own administrative path; bare repository refused;
  non-git target refused.
- Staging occurs adjacent to each destination parent, verified on a target containing a nested mount.

Hook and status:

- A failing hook leaves the installation and exits 1.
- `status` never executes the hook and reports "not evaluated" rather than any past outcome.
- The hook runs exactly once after a gated install and on `Equivalent`, and **zero** times on refusal,
  rollback, `recover`, every plan command, `status`, and `init`.

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
- Source-CI conformance: full `env` and `with` comparison; step identity and order; trust predicates for
  every privileged job; a stale allowlist entry fails; an uncovered step-level difference fails; the
  entry count is reported; the PyYAML loader rejects duplicate keys and normalizes `on`.
- Every diagnostic's next action exists for the relevant generation path.
- Persisted checkout credentials and credential-looking values are absent.

## Compatibility and the PRD

| Requirement | Change |
| --- | --- |
| REQ-001 detect incomplete setup | Retained and extended: readiness names unreplaced slots, derived from declared markers |
| REQ-002 one validation command | Retained; the canonical hook path becomes `scripts/validate-project`, a **breaking change** against the current repository requiring migration notes |
| REQ-003 gate releases on project validation | Retained; the gate is a compiled contribution present only with `semantic-release` |
| REQ-004 verify generated behavior from source | Extended to the tiered matrix and both paths across profiles |
| REQ-005 preserve generation-path ownership | Extended with the ownership classes, the drift contract, and the populated manifest-free contract |
| REQ-006 portable, least-privileged template validation | Retained; the generated boundary stays standard-library only, while source-only fixtures may use dev-shell tools |
| New: deterministic bootstrap | The compiler, its input contract, and byte-for-byte output guarantees |
| New: capability selection | Profiles, catalog, and the absence of unselected artifacts |
| New: total classification | Every reachable state maps to exactly one decision with a reachable next action |
| New: recorded inventory as render oracle | Managed integrity and the render-contract check |
| New: recoverable planned-path transactionality | Lock, phases, and rollback, without atomic multi-file visibility |
| New: installation distinct from readiness | A completed installation whose hook fails exits 1 |
| New: template evolution limits | Compatible updates may not create unsatisfiable obligations |
| New: activation is not readiness | Two-state preflight in a fixed trusted job |

### CONTEXT.md changes required

- **Project bootstrap** gains the distinction between a completed installation and a locally ready
  project.
- **Project readiness** keeps its meaning, including successful hook completion, and gains that
  unreplaced slots are derived from declared markers.
- **Bootstrap-managed artifact** gains `restore` as the remedy and the recorded inventory as the oracle.
- **Project-validation hook** changes path to `scripts/validate-project`.
- New terms: **recorded inventory**, **apply decision**, **managed drift**, **populated manifest-free
  project**, **point-in-time hook evidence**, **cleanup inventory**.
- The example dialogue gains an exchange distinguishing "bootstrap installed the files" from "the
  repository is locally ready", and one explaining why a GitHub snapshot cannot reconcile.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A required workflow is unreachable through the classifier | A total function with a witness per constructor and no shadowing |
| Manifest validation rejects a legitimate template update | Validity is parse, schema, and checksum only |
| A render-contract violation is undetectable | The recorded inventory is the oracle, checked at point of use |
| The renderer needs bytes it was not given | `render(RenderInput, BlobMap)` with decoded definitions and fragment bodies |
| A fingerprint silently stops covering an input | Answers are stored as values; the render result is checked against recorded hashes |
| A generated project fingerprints a file it never received | The three-way input boundary |
| An operation changes identity it should not | The operation-semantics table, asserted row by row |
| A repair silently upgrades the template | `restore` writes only certified bytes and records nothing |
| Ungated output survives a crash | Gating inside `MUTATING`; `SEALED` only after it passes |
| An interrupted rollback completes forward | Phase-dependent recovery with no phase doing both |
| A torn journal is unreadable | Atomic replacement for every transition |
| An abandoned lock blocks forever, or lock domains split | A never-unlinked inode, no `O_EXCL`, `flock` for liveness |
| State location varies and hides pending recovery | A git working tree is required; location is a pure function of the target |
| Replacement crosses a filesystem boundary | Staging adjacent to each destination parent |
| An ancestor is substituted between check and use | Root-anchored per-component walk and re-resolution |
| A security guarantee exceeds its primitives | The threat model is stated narrowly and excludes a concurrent local adversary |
| A compatible update creates an unsatisfiable obligation | The template-evolution rule and the frozen readiness-rule baseline |
| Snapshots acquire an update lifecycle by accident | `reconcile` is unavailable on the GitHub path; `TemplateChanged` names `git restore` |
| The migration has no steady state | One contract: stay on the pre-bootstrap release |
| A rename is mistaken for adoption | The migration states what it does not do; `UnsupportedTarget` refuses the result |
| Ownership transfer is assumed rather than shown | V1 does not transfer ownership on existing projects |
| An intermediate merge changes behavior | Integration branch with one activation merge |
| A defective install hides behind the scaffold exemption | Artifact verification precedes exemptions; the install rule is equality |
| A repeated or worsened finding goes undetected | Multiset comparison over four-part identity |
| Adopter content impersonates a placeholder | Reserved markers rejected in `file` inputs |
| A non-text hook breaks detection | Byte-level sentinel search |
| Security-relevant CI drift stays green | Full `env` and `with` comparison, step identity, trust predicates |
| A canary gives false assurance | Run locally with a non-secret sentinel across all channels |
| A YAML parser's defaults misread Actions | A specified `SafeLoader` contract with duplicate rejection and `on` normalization |
| The Python floor is unproved | An explicit 3.11 validation lane |
| False drift from line endings or umask | Specified normalization and execute-bit-only comparison |
| An ownership class traps ordinary configuration | `CONTRIBUTING.md` and `.gitattributes` are adopter-owned |
| Bootstrap becomes an authoring gate | `scaffold` compiles a real project before prose exists |
| A destructive overwrite runs unreviewed | Bound to a recomputed plan digest and target identity |
| A secret leaks through the preflight | Fixed trusted job, structural test, local canary |
| Licence obligations are lost | Conservative preservation plus an audit gating every mode before licence writing |
| One change contains the whole system | Nine review boundaries on an integration branch |

## Proposed future changes

**Experience:** one-command initialize-and-apply over the same engine; inline prose fields with
escaping; guided PRD authoring; stack presets without an implicit default; opt-in regeneration of
seed-once files; `apply --strict` gating on the hook.

**Capability lifecycle:** a broader first-party catalog; third-party registries with signing and trust
policy; live profiles; removal, replacement, and reconfiguration; versioned capability IDs with
migrations; managed document regions; a sandboxed plugin model if declarative slots prove insufficient.

**Adoption and portability:** an adoption lifecycle for populated repositories with `plan-adopt`,
collision handling, and ownership transfer; a named v1 compatibility release for existing Copier
projects; snapshot adoption into Copier lineage; non-git targets with a state-namespacing rule;
declarative validation-command lists; interpreter adapters and native Windows support; a portable
structured workflow parser; structured JSON diagnostics; hook sandboxing.

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
transaction committed before it is gated; a fourth transaction phase whose recovery duplicates another's;
combining `O_EXCL` with `flock`; unlinking and recreating a lock; deriving the lock location from a
user-supplied state directory; non-atomic journal transitions; a single staging directory for a target
spanning mounts; claiming atomic multi-file visibility; operating on planned paths by name after a
one-time check; claiming resistance to a concurrent local adversary; comparing readiness findings as
`(code, path)` sets; allowing an empty finding path; a `Finding` order left to implementation; one global
exit-code rule across inspection and mutation; claiming the hook runs once when refusals and rollbacks
run it zero times; gating the transaction on the hook; reporting success when the hook failed; treating
an equivalent reapply as an unconditional exit-0 no-op; recording or replaying hook results; `status`
executing the hook; requiring complete prose before compiling; recording slot completion in the manifest;
requiring the hook to be decodable UTF-8; accepting adopter content containing a reserved marker; two
canonical hook paths; an adoption command without preview or collision rules; implying a rename bootstraps
a project; a manifest listed in its own inventory; giving snapshots any update lifecycle; promising both a
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

- `docs/prd.md`, per the requirement delta, including the breaking hook-path change. **Pre-runtime gate.**
- `CONTEXT.md`, per the domain-language changes. **Pre-runtime gate.**
- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs on the Copier path only. **Pre-runtime gate.**
- An ADR for the functional-core architecture, the domain model, and the ownership boundary.
- The licensing and provenance audit record and any resulting ADR. **Prerequisite to batch 5.**
- `docs/project-readiness.md`, reflecting the canonical hook path, derived slot completion, `status`,
  `restore`, and the populated manifest-free contract.
- Release notes containing the pinned pre-bootstrap tag, the rename's scope and limits, and the
  collision and rollback guidance.
- Generated adopter documentation described above.
- Source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open, subject to owner assent on the two scope reductions named at the
top.

The licensing and provenance audit gates every licensing mode and precedes batch 5. If it changes the
proposed `LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design must be amended and reconfirmed
before licence-writing implementation proceeds.

## References

- `docs/prd.md`; `CONTEXT.md`; `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md`
- `design.discovery-draft.md`, `design.revision-2.md`, `design.revision-4.md` in this directory
- `design.revision-3.reconstructed.md` — a reconstruction of revision 3, faithful in substance but not
  verifiable byte-for-byte against the original
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub: Dependabot on Actions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions)
- [Git: `git rev-parse`](https://git-scm.com/docs/git-rev-parse); [Git: `git clean`](https://git-scm.com/docs/git-clean)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/); [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
