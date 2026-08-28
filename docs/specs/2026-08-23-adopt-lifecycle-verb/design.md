# Adopt Lifecycle Verb for Brownfield Repositories

**Status:** Draft 2, assembled from approved discovery and design batches; amended 2026-08-28
during T3 implementation with the lifecycle-installation decisions (owner-confirmed).
**Date:** 2026-08-23
**Planning mode:** Spec-backed Plan
**Origin:** `.handoff/2026-08-23-framework-gap-analysis.md` finding F-02; owner selected
"build an `adopt` verb" over "declare greenfield-only" on 2026-08-23.

## Problem

The framework is intended to work both for bootstrapping new projects and for application to
existing ("brownfield") repositories, but the product contract forbids the second half of that
goal. REQ-007 restricts installation to "a verified non-bare Git working tree containing a
recognized scaffold produced by one of the two generation paths"; `CONTEXT.md` defines the
*Unrecognized manifest-free target* and states that bootstrap v1 "neither installs into, adopts,
nor migrates this unsupported state." The observation core already classifies such targets
(`UnsupportedManifestFree`) and every command refuses them with `UNSUPPORTED_TARGET`.

A maintainer of an existing repository therefore has no path to install template-managed delivery
infrastructure without recreating the repository through GitHub or Copier. This design resolves
the contradiction by building adoption rather than narrowing the stated goal.

## Settled decisions

Owner decisions recorded so review does not reopen them.

- **Entry conditions:** any non-bare Git working tree without a project manifest qualifies,
  including dirty trees and empty trees. No additional structural requirements in v1.
- **Conflict policy:** per-path explicit declarations inside the answer document. Every collision
  between planned managed output and observed content must be declared `keep-existing` or
  `replace`; undeclared collisions refuse the plan naming every offending path.
- **Capability parity:** adoption uses the same snapshot-profile/capability bundle schema as
  `init`/`apply`, extended with the collision declarations. One input contract, one resolver.
- **Provenance posture:** adopted projects record `GenerationPath.ADOPTED` and behave
  snapshot-like: `restore` works against the recorded baseline, `reconcile` is permanently
  refused, and source-baseline repair/regeneration rules match snapshot projects. Adopted
  projects can never gain Copier reconcile lineage.
- **Seed-once protection:** paths in the seed-once legal/provenance class accept only
  `keep-existing` under adoption; `replace` is structurally rejected in v1.
- **No new transaction machinery:** adopt reuses the journaled transaction machine unchanged;
  the machine is plan-driven, so no new machine-level decision type is introduced.
- **CLI implementation stays on stdlib argparse:** `typer` was evaluated and declined. Each verb
  already maps linearly onto one parser block, one frozen intent dataclass, and one decision
  function; typer's annotation-driven wiring would duplicate the intent layer, its click-based
  echo/exit conventions conflict with REQ-014's canonical text/JSON presentation contract, and
  the marginal benefit does not justify a third runtime dependency in the engine that ships into
  every generated project. A declarative-parser evaluation may be revisited only if the verb
  count grows past roughly twelve.
- **Contract amendments are in scope:** REQ-007, REQ-010, and `CONTEXT.md` change with this
  feature. The frozen readiness-rule corpus is untouched; adoption adds no blocking obligation
  over adopter-owned state and rebinds no stable identifier, so the extension is additive under
  REQ-013 (verified: `validate_readiness_rule_catalog` pins readiness rules only).

Amendments settled 2026-08-28 (owner decisions recorded so review does not reopen them):

- **Lifecycle installation:** the template contract requires the generated-lifecycle source
  files (AGENTS.md, every skill, `scripts/bootstrap/*.py`, `.rygor/source-ownership.json`,
  `copier.yml`, …) to exist in the installed tree, and no generation path renders them —
  GitHub/Copier targets receive them from their template packaging before `apply`. Because the
  adoption entry condition is an arbitrary manifest-free tree, `adopt` must install the
  lifecycle source set itself: the template root's declared `lifecycle_paths` plus the template
  root's `.rygor/source-ownership.json` plus `CLAUDE.md`. Without this the reused expected-target
  contract gate would refuse every real brownfield adoption, contradicting the settled entry
  conditions.
- **Collision policy over lifecycle paths:** the full per-path declare policy applies. An
  undeclared collision between a planned lifecycle file and observed content refuses the plan
  naming every offender; `keep-existing` excludes the path from the install and from the
  manifest inventory; `replace` overwrites with the prior `FileState` recorded in the receipt.
  Lifecycle files are template-owned, not legally sensitive, so unlike the seed-once
  legal/provenance class `replace` is allowed.
- **Post-install ownership — managed inventory:** installed lifecycle files join the manifest's
  managed inventory. They are restore-able and drift-fatal, diverging deliberately from
  GitHub/Copier projects where the same files stay outside the inventory. The source baseline
  still records them (lifecycle paths are not excluded from source-entries collection), so
  adopted projects keep snapshot-style repair/regeneration diagnosis. Consequence accepted: an
  adopter file replaced by a lifecycle install becomes drift-fatal managed state.
- **CLAUDE.md packaging:** installed as a regular file whose bytes are the template's AGENTS.md
  content. The template ships `CLAUDE.md` as a symlink to AGENTS.md, but the observation and
  transaction layers reject every symlink in a project tree; an installed symlink would make the
  adopted project permanently unobservable. A symlink-create operation type (new journal,
  rollback, and recovery third states) was evaluated and declined for v1. Accepted divergence:
  adopted projects carry a regular `CLAUDE.md` instead of a symlink, and its content is the
  template's AGENTS.md bytes even when AGENTS.md itself is declared `keep-existing`.

## Scope

**In scope**

- `PlanAdopt`/`Adopt` intents, `GenerationPath.ADOPTED`, and the `collisions` answer-document
  section (*adoption declaration*).
- A conflict-aware compilation branch that partitions planned outputs into create / replace /
  keep-existing exclusions with typed compile errors.
- The adoption lifecycle-install set: reading the template root's declared lifecycle source
  (plus its `.rygor/source-ownership.json` and the `CLAUDE.md` regular copy), compiling those
  files through the same partitioning, and recording installed entries in the managed
  inventory.
- Restore parity for adopted projects: the recorded-render reconstruction sources installed
  lifecycle bytes from the template root, verified against the recorded inventory identities.
- CLI verbs `plan adopt` and `adopt` with the existing envelope and exit-code taxonomy.
- Status diagnostics describing adoptability of unmanaged trees.
- PRD amendments (REQ-007, REQ-010), `CONTEXT.md` terminology updates, README and durable
  adopter documentation updates.
- Fixtures covering both generation-path refusal surfaces and the full adopt success/refusal
  matrix, consistent with REQ-004 (generated behaviour exercised from the template source).

**Out of scope (deferred)**

- Capability removal, replacement, or reconfiguration (unchanged from v1).
- Copier update lineage or reconcile capability for adopted projects.
- `replace` on seed-once legal/provenance paths.
- An interactive bundle interviewer; bundles remain fully declarative inputs.
- Non-Git targets, bare repositories, and manifest-bearing targets (remain refused).
- Migration of an adopted project into a recognized-scaffold shape.

## User Stories

- **US-1 (must):** As a maintainer of an existing repository, I want `plan adopt` to preview every
  planned creation, replacement, and exclusion, so that I can review the full mutation before
  anything changes.
  *Given* a manifest-free, non-bare Git working tree and a complete adoption bundle, *when* I run
  `plan adopt --bundle ./bundle --target . --out receipt.json`, *then* the receipt enumerates all
  operations with per-path decisions and no target file is modified.
- **US-2 (must):** As the same adopter, I want `adopt` to install through the journaled
  transaction machine, so that an interrupted run either restores the exact pre-state or completes
  forward via `recover`.
- **US-3 (must):** As the same adopter, I want undeclared collisions refused, so that nothing is
  silently overwritten or skipped. *Given* a bundle missing a declaration for any path where
  managed output meets existing content, *when* planning, *then* refusal exits 1 naming every
  undeclared collision path with its next action.
- **US-4 (must):** As the same adopter, I want `keep-existing` paths to become permanently
  adopter-owned — absent from the managed inventory, never drift-fatal, never restored,
  reconciled, or re-created later.
- **US-5 (must):** As the same adopter, I want `replace` to overwrite only paths I explicitly
  declared, with the prior file identity preserved in the plan receipt.
- **US-6 (should):** As the same adopter, I want `status` on an unmanaged tree to describe its
  adoptability and name `init` plus `plan adopt` as the next action.
- **US-7 (must):** As a template maintainer, I want adopted projects to record `ADOPTED`
  provenance and behave snapshot-like afterward: `restore` works against the recorded baseline,
  `reconcile` is permanently refused, and source-baseline repair/regeneration rules match
  snapshot projects.
- **US-8 (must):** As a template maintainer, I want seed-once legal/provenance paths restricted
  to `keep-existing` under adoption, so pre-existing legal text is structurally impossible to
  overwrite in v1.

## Constraints

- Additive compatibility only (REQ-013): no required seed-once path may be added, no blocking
  obligation may be added over adopter-owned state, no stable identifier may be reinterpreted,
  and every existing normalized project state must remain satisfiable through its supported
  lifecycle. Verified: the compatibility corpus pins readiness-rule identities only.
- Functional core / imperative shell (PRD quality attributes, ADR 0002): collision partitioning,
  validation, and provenance derivation are pure; filesystem, Git, process, and terminal effects
  stay in the existing shells.
- Closed typed outcomes (REQ-014): adopt intents join the closed unions; refusals carry concrete
  next actions (`apply`, `status`); inspection never mutates; planning never prompts; text and
  JSON presentations agree.
- Recoverability (REQ-011): every adopt mutation executes one complete typed operation plan under
  the target lock and write-ahead journal; recovery semantics are inherited, not redesigned.
- Exit codes: 0 success; 1 user-correctable refusal, unmet precondition, expected scaffolds,
  installed-but-unready hook result; 2 usage, input, contract, transaction, internal failures.
- Ownership separation (REQ-009): the manifest records neither adopter prose, legal text, secret
  values, nor claims about current tree bytes; pre-adoption file identities live in receipts only.

## Context

What exists today, end-to-end:

1. The shell observes a target into a closed `SystemState`; absent-manifest trees classify via
   `recognize_generation` into `RecognizedScaffold` or `UnsupportedManifestFree(shape, snapshot)`.
2. Policy (`decisions.py`) maps intent × state onto typed decisions, refusing unsupported
   combinations.
3. Bundles decode an answer document plus referenced content bytes
   (`decode_bundle_input`); `compile_initial_install` normalizes answers, resolves the profile
   closure, and compiles one `OperationPlan` carrying provenance and gates.
4. The journal-driven transaction machine applies plans with exact recovery semantics.
5. Receipts encode/decode plans bound to a target digest; `_GENERATION_PATHS` derives the closed
   generation set from the enum.

Research mapping (concern → existing solution → decision):

| Concern | Existing solution | Decision | Driver |
|---|---|---|---|
| Target classification | `observation.py` produces `UnsupportedManifestFree` for brownfield trees | reuse | US-1 entry condition |
| Lifecycle verbs | closed intent unions (`intents.py`), per-verb dispatch (`decisions.py`) | modify | REQ-010 lifecycle gains `plan adopt`/`adopt` |
| Provenance | `GenerationPath` enum across manifest, receipts, baselines | modify | `ADOPTED` member; snapshot-like posture |
| Plan compilation | `compile_initial_install`, planner operation types | reuse + new branch | conflict-aware partitioning |
| Conflict policy | none (apply requires exact scaffold) | new | US-3/US-5 |
| Seed-once handling | planner seed-input validation assumes absent-or-scaffold state | modify | US-8 |
| Journal/transaction | `transaction_machine.py` | reuse, unchanged | US-2 |
| Compatibility freeze | corpus pins readiness rules only | verified compatible | REQ-013 |

Gotchas:

- `decisions.py` currently returns `UNSUPPORTED_TARGET` for action intents over
  `UnsupportedManifestFree`; the adopt branch must take precedence for adopt intents only,
  leaving every other verb's refusal untouched.
- `source_baseline.py` derives tagged baselines via exhaustive match over `GenerationPath`;
  adding an enum member breaks compilation until the `ADOPTED` case exists (desired).
- Generated documentation fragments mention generation paths and lifecycle availability; the
  capability/documentation fragment layer must emit adopt-aware guidance without per-capability
  branches (REQ-015).

## Architecture

Component changes, all within the existing boundary:

- **intents.py** — `ADOPTED = "adopted"` joins `GenerationPath`; `AdoptOptions(bundle_digest)`
  mirrors `ApplyOptions`; `PlanAdopt`/`Adopt` join the closed intent unions.
- **bundles.py** — the answer document gains the optional `collisions` section. Decode validates
  syntax and the closed value set only; semantic validation happens in the compiler where the
  planned inventory is known. Collisions join normalized answers, keeping bundle digests and
  manifest identity deterministic functions of inputs.
- **decisions.py** — `_adopt_decision` accepts `ProjectAvailable` over `UnsupportedManifestFree`
  (empty or populated shapes); refuses recognized scaffolds naming `apply`, and existing projects
  naming `status`. Reuses the existing install decision type: the transaction executor is
  plan-driven and `OperationPlan` carries `generation_path` and provenance, so no new
  machine-level decision type exists.
- **planner / compiler** — `compile_adoption_install` mirrors `compile_initial_install` with
  `generation=ADOPTED` plus the lifecycle install set. It partitions planned managed outputs
  against observed entries: absent → create; declared `keep-existing` → excluded from both the
  plan and the managed inventory (absence *is* the ownership model; no new ownership class);
  declared `replace` → replace operation with prior `FileState` recorded in the receipt;
  undeclared collision → typed compile error listing all offenders; `replace` on the seed-once
  legal/provenance class → structurally rejected. The lifecycle install set joins the same
  partitioning and, when installed, joins the manifest inventory; it is *not* passed as managed
  render, so the source-entries collection still records it in the adopted source baseline.
  Reuse seed-once input handling, manifest answer normalization, VerifiedBlobStore, gate
  specifications (fully reused — the expected target gains the lifecycle files, so the
  template-contract gate passes naturally), and provenance assembly with generation=ADOPTED.
- **source_baseline.py** — exhaustive match gains the `ADOPTED` case, deriving a snapshot-style
  tagged digest over installed lifecycle-source entries.
- **restore (recorded render)** — for adopted projects the recorded-render reconstruction
  extends the re-rendered selection with the installed lifecycle entries: their bytes are read
  from the template root and accepted only when their identities match the recorded inventory,
  so `restore` reproduces managed drift exactly as it does for the other generation paths.
- **observation/presentation** — `UnsupportedManifestFree` diagnostics gain adoptability framing;
  status names `init` + `plan adopt` as next actions while remaining exit-0 inspection.
- **CLI** — `adopt` and `plan adopt` subparsers; identical envelope shapes.
- **transaction_machine, journal, locking** — unchanged.

Where logic lives: collision partitioning and validation are pure planner functions; legality of
intent/state pairs lives in the decision core; all effects remain in the imperative shells.

## API Design

```console
uv run --python 3.14 scripts/bootstrap_project.py init --from ./adoption.json --output ./bundle
uv run --python 3.14 scripts/bootstrap_project.py plan adopt --bundle ./bundle --target . --out receipt.json
uv run --python 3.14 scripts/bootstrap_project.py adopt --bundle ./bundle --target .
uv run --python 3.14 scripts/bootstrap_project.py status --target .
```

- Envelopes: identical canonical JSON envelope shapes; `intent` values `adopt` and `plan-adopt`.
- Exit taxonomy unchanged (see Constraints).
- Refusals: adopt over a recognized scaffold names `apply`; over an existing project names
  `status`; undeclared collisions name every offending path; illegal declarations (path not
  actually colliding; `replace` on seed-once class) are input errors with subject paths.
- Status on unmanaged trees reports adoptability and next actions without executing or rewriting
  anything.

## Data Model

1. **Answer document** — optional top-level `collisions` object mapping repository paths to
   `"keep-existing"` or `"replace"`.
2. **Manifest** — `provenance.generation_path = "adopted"`. Keep-existing paths appear nowhere
   (absence from the managed inventory is the ownership record); replaced files' prior identities
   appear only in receipts. For adopted projects the managed inventory additionally records the
   installed lifecycle entries (same entry shape; no schema-version bump: the extension is
   additive and the manifest remains a function of normalized inputs).
3. **Receipts** — schema untouched; encode/reconstruct accept `adopted` because the closed set
   derives from the enum; `source_before`/`source_after` carry adopted-tagged baselines.
4. **State machine** — zero new `SystemState` variants; adopt consumes the existing
   `UnsupportedManifestFree`.
5. **Typed errors** — compile-error kinds gained for undeclared collisions, declarations naming
   non-colliding paths, and illegal `replace` targets; transition-error kinds gained (or reused)
   so adopt refusals carry their specific next actions.

## Contract amendments

Implementation includes these documentation changes (this skill does not edit them directly):

- **REQ-007** — admit adoption of any verified non-bare manifest-free Git working tree as an
  initial-install entry condition alongside the two recognized scaffolds.
- **REQ-010** — add `plan adopt`/`adopt` to the public lifecycle enumeration; state that adopted
  projects follow snapshot repair/regeneration rules and never reconcile.
- **REQ-009** — note that adopted projects record installed lifecycle source inside the managed
  inventory; the ownership-separation prohibitions (no adopter prose, legal text, secret values,
  or claims about current tree bytes) are unchanged.
- **CONTEXT.md** — narrow *Unrecognized manifest-free target* to non-Git, bare, and
  manifest-bearing states; add *Adopted project* (generated-project whose manifest records
  adopted provenance) and *Adoption declaration* (the per-path collision map inside the answer
  document); extend the *Bootstrap answer document* definition to allow the declaration; extend
  the *Managed inventory* / *Generated-lifecycle source* terminology so adopted projects record
  installed lifecycle files in the inventory. Record the lifecycle-installation ownership
  decision as an ADR (it changes ownership semantics for one generation path).
- README, `docs/project-readiness.md`, and the durable adopter documents gain the brownfield
  entry path.

## Trade-offs

Alternatives considered and rejected:

- **Extend scaffold recognition** to admit arbitrary trees so plain `apply` handles brownfield —
  conflates exact-byte recognition with arbitrary content, silently changes refusal semantics of
  every other verb, contradicts the recognition contract.
- **Sidecar adoption compiler** outside the core unions — duplicates bundle decoding,
  normalization, gate and seed-once logic; two sources of truth for install semantics.
- **New ownership class for keep-existing paths** — absence from the managed inventory is simpler
  and composes with existing restore/reconcile logic.
- **Prior file identities in the manifest** — violates REQ-009's prohibition on claims about
  current tree bytes; receipts retain the evidence instead.
- **Allow `replace` on seed-once legal paths** — deferred; structurally rejected in v1.
- **Scope the expected-target contract gate for adopted plans** — evaluated during T3 and
  declined: skipping the required-file/skill checks would certify adopted projects that lack the
  template's own delivery infrastructure, defeating the verb's purpose. Installing the lifecycle
  set (settled above) keeps the gate fully reused and honest.
- **Symlink-create operation for `CLAUDE.md`** — evaluated and declined: the observation and
  transaction layers reject every project-tree symlink (an installed symlink makes the adopted
  project permanently unobservable), and making symlinks legal means new journal, rollback, and
  recovery third states — new transaction machinery the design froze as unchanged.

Why this design wins: purely additive across closed unions; one compiler, one transaction
machine, one receipt format; verifiably compatible under REQ-013; the observation core already
models the brownfield state, concentrating the diff where REQ-015's extension discipline expects
it.

Known limitations accepted for v1: adopted projects cannot gain Copier reconcile lineage;
uncommitted adopter work at declared `replace` paths is overwritten beyond the journal's
file-level restore; collision declarations are hand-authored; seed-once `replace` may be
revisited post-v1 if a real need appears; adopted projects package `CLAUDE.md` as a regular file
copy of the template's AGENTS.md rather than a symlink, and its bytes stay the template's AGENTS.md
content even when AGENTS.md is declared `keep-existing`; adopter files replaced by lifecycle
installs become drift-fatal managed state; a `keep-existing` declaration on a contract-required
skill whose existing bytes lack valid frontmatter fails the reused expected-target gate
deterministically.

## Open Questions

None unresolved. All scope forks raised during discovery were settled by owner decisions listed
under "Settled decisions". Deferred ideas are recorded under "Out of scope".
