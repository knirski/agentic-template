# Deterministic Project Bootstrap with Capability Profiles

**Status:** Draft assembled for final confirmation  
**Date:** 2026-08-05  
**Planning mode:** Spec-backed Plan

## Summary

Add a deterministic, explicit bootstrap compiler that turns either supported generated-repository
shape into a locally ready project from a complete, reviewable input bundle. The compiler expands an
explicitly selected snapshot profile into an exact capability set, writes only declared outputs,
persists normalized mechanical state, and validates the result through the repository's canonical
validation boundary.

The first capability catalog covers the integrations already present in the template:

- semantic-release;
- Nix;
- Cachix publishing, which depends on Nix; and
- Qodo PR Agent with a Gemini backend.

The catalog and composition model are deliberately extensible, but v1 does not accept executable
plugins, secrets, capability removal, or live-profile mutation. GitHub-created repositories remain
one-time snapshots. Copier-created repositories retain update lineage, after which bootstrap
reconciliation recompiles derived artifacts without duplicating Copier's merge behavior.

This design is an explicit product decision that extends `docs/prd.md`. Implementation must update
the PRD and amend ADR 0001 before changing runtime behavior so those authoritative documents describe
the approved compiler and ownership boundary.

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

- Produce a fully locally ready repository from complete user-authored product content and explicit
  mechanical choices.
- Make the same normalized input and template inputs produce byte-for-byte identical
  bootstrap-managed output.
- Require explicit intent-based profile selection and freeze its expansion at creation time.
- Support exact custom capability selection and additive post-bootstrap capability changes.
- Keep core validation independent of optional capabilities and external activation.
- Share one bootstrap engine across GitHub-snapshot and Copier generation paths.
- Give Copier and bootstrap non-overlapping update responsibilities.
- Preserve adopter-owned product content and detect drift in bootstrap-managed artifacts.
- Make missing external secrets safe and actionable instead of causing noisy workflow failures.
- Produce durable adopter-facing delivery, update, capability, and GitHub setup documentation.
- Allow new declarative capabilities without changing the resolver or transaction engine.

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

## Users and workflows

### US-1: Prepare a reviewable input bundle

As a template adopter, I want an initializer to collect my choices and content into a reviewable
bundle without touching the project so that generation inputs can be inspected, versioned, and
reused.

Acceptance criteria:

- `init` supports interactive collection and a pre-seeded non-interactive input.
- It requires an explicit profile selection; the interactive flow may recommend `portable` but the
  engine has no default profile.
- It requires complete user-supplied PRD, README, validation hook, SECURITY policy, and licensing
  input.
- It copies referenced content bytes into a self-contained bundle and writes relative references in
  `bootstrap.json`.
- It does not mutate a generated project or perform external operations.
- It refuses a non-empty output location instead of silently replacing a bundle.

### US-2: Bootstrap a generated project deterministically

As an adopter, I want to preview and explicitly apply a complete bundle so that the result is locally
ready without manual placeholder replacement.

Acceptance criteria:

- `plan` reports the exact create, replace, and delete set without mutation.
- `apply` performs initial bootstrap only from recognized generated-project scaffolding.
- Successful apply makes `python3 scripts/validate-repository.py` succeed locally.
- The adopter executable is installed at the toolchain-neutral path `scripts/validate-project`.
- The result contains no required product placeholder and does not depend on Nix unless selected.
- The manifest records an initial input fingerprint derived from normalized mechanical values and
  referenced content hashes, without storing prose or source paths.
- Reapplying an equivalent bundle validates the current managed state and returns a no-op without
  rewriting seed-once adopter files.
- Reapplying a different bundle refuses mutation and directs the user to the appropriate supported
  lifecycle operation.

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

- README, PRD, validation hook, SECURITY policy, root license, and the project-validation workflow
  become adopter-owned after their initial installation.
- The manifest contains only normalized mechanical state and hashes.
- Licensing selection is mandatory and explicit.
- Bootstrap authors no legal terms and makes no legal-validity claim.
- Template Apache-2.0 text and bundled-skill provenance remain available when a different project
  license or private notice is installed.
- A licensing and provenance audit confirms the final notice layout before implementation fixes it
  and before release.

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
- A read-only preflight job detects availability before any job with write permissions starts.
- Runtime secret values are never emitted through logs or persisted outputs.
- Durable documentation identifies every manual activation step.

### US-8: Reconcile derived artifacts after Copier update

As a Copier adopter, I want updated compatible compiler inputs to re-render derived outputs without
overwriting my project files or duplicating Copier's merge semantics.

Acceptance criteria:

- The documented sequence is `copier update`, bootstrap `reconcile`, then canonical validation.
- Copier selects and merges template inputs; reconciliation only compiles derived outputs.
- Reconciliation preserves the exact effective capability set and normalized settings.
- It updates only managed paths whose bytes match the old manifest hashes.
- It neither adds nor removes capabilities, changes settings, re-expands profiles, nor merges files.
- Copier conflict evidence, managed drift, or an incompatible catalog blocks all writes.
- GitHub-generated projects remain one-time snapshots without Copier update lineage.

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
  `docs/capabilities.md`, `docs/github-setup.md`, and `CONTRIBUTING.md`.
- The documents reflect generation path, frozen profile, effective capabilities, external
  prerequisites, validation, update, drift, and recovery behavior.
- Capability additions and reconciliation update affected managed documents in the same transaction
  as code and workflow artifacts.
- Direct edits are treated as managed drift in v1 and recovery guidance points to adopter-owned
  product documentation for project-specific prose.

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
- A normal validation or write failure automatically restores planned paths when possible.
- An interrupted journal blocks later mutations.
- `recover` explicitly rolls back to the pre-operation state and never resumes a partial plan.
- Hook-created artifacts outside the planned path set are permitted by the PRD and are not removed by
  recovery.

## Decision record from discovery

The following table records the approved answer to each material design question and the extension
path retained for viable deferred work.

| Topic | V1 decision | Proposed future change, if viable |
| --- | --- | --- |
| Bootstrap result | Complete supplied content produces a fully locally ready project | Partial bundles, staged readiness, or a separate finalize phase |
| Profile semantics | Named profiles are one-time snapshots | Explicit live profiles or profile-plus-override policies |
| Initial catalog | Current integrations only, behind a generic catalog | Broader first-party catalog and stack presets |
| Catalog ecosystem | Repository-local trusted definitions | Third-party registries with provenance and trust policy |
| Profile names | Intent-based names | More intent-specific profiles when justified by real usage |
| Selection default | No engine default; initializer may recommend `portable` | Guided recommendations based on declared project characteristics |
| Persisted ownership | Mechanical state in the manifest; prose in adopter files | Richer persisted initialization answers for documentation regeneration |
| Content input | Referenced ordinary files in a self-contained bundle | Inline prose fields where review and escaping rules are sufficient |
| Interaction | Initialize a bundle, then explicitly plan/apply | One-command interactive convenience layered on the same engine |
| Lifecycle | Initial bootstrap plus additive capability changes | Removal, replacement, rebasing, and full reconfiguration |
| External activation | Locally configured, externally unverified, safe skips | GitHub doctor, then explicitly authorized configuration writes |
| Licensing | Explicit adopter-supplied decision; preserve provenance | SPDX, SBOM, and richer license automation after legal review |
| Validation hook | Arbitrary directly runnable adopter executable | Declarative command hooks, interpreter adapters, and native Windows support |
| Documentation | Managed durable operational documents | Managed regions or adopter-supplied documentation fragments |
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
| Repository identity | Read live at runtime; no persisted owner/repository slug | Doctor-managed rename and transfer diagnostics |
| Template identity | Content fingerprints; Copier retains its own revision metadata | Signed release provenance |
| Seed ownership | Install once, then adopter-owned | Explicit opt-in reset or regeneration workflow |
| Schema evolution | Schema 1 remains backward-compatible throughout v1 | Explicit schema migrator in a later major version |
| Maintenance cleanup | Hash-checked declarative inventory | Authenticated source identity and richer provenance policy |
| Repeated apply | Equivalent initial input fingerprint yields a validated no-op | Explicit full re-bootstrap after a future ownership-aware migration design |

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
          canonical repository validation
```

The functional core returns immutable normalized models, diagnostics, and a complete filesystem plan.
The effectful edge reads source bytes, examines the target, writes the transaction journal, installs
the plan, invokes validation, and performs recovery.

### Proposed source layout

```text
scripts/bootstrap-project.py
scripts/bootstrap/
  __init__.py
  cli.py
  inputs.py
  model.py
  catalog.py
  resolver.py
  renderer.py
  planner.py
  transaction.py
  diagnostics.py

.agentic-template/
  schemas/
  profiles.json
  compatibility/capabilities-v1.json
  maintenance-artifacts.json
  core/
  capabilities/
    semantic-release/
    nix/
    cachix-publish/
    pr-agent-gemini/
```

The exact module split may be refined in the implementation plan, but the dependency direction is
fixed: CLI and filesystem effects depend on the functional model; the model never imports CLI or
filesystem mutation code.

### File ownership

| Class | Owner and behavior |
| --- | --- |
| Copier/template inputs | Engine, catalog, render sources, validators, skills, static contracts, and `NOTICE.md`; Copier updates and merges these on its path |
| Bootstrap-managed output | Manifest, compiled CI, selected capability artifacts, generated contributor guidance, and durable operational documents; exact hashes are enforced |
| Seed-once adopter output | README, PRD, validation hook, SECURITY, root license, and project-validation workflow; installed initially and never regenerated in v1 |
| Adopter files | Product code, product documentation, unrelated workflows, and all files outside declared template ownership |
| Template-maintenance artifacts | Source tests, source workflow fixtures, historical source specs, and other paths in the maintenance inventory; excluded by Copier and conditionally removed from GitHub snapshots |

No path may belong to more than one class. Source validation rejects duplicate, nested, or
case-colliding ownership declarations.

### Generation-path behavior

Copier configuration excludes bootstrap-managed output, seed-once adopter output, and declared
template-maintenance artifacts. Copier copies the engine, catalog, static contracts, and update
metadata. Initial bootstrap installs derived and seed-once files.

GitHub's repository-template operation copies the source tree unchanged. Initial bootstrap therefore
uses the maintenance inventory and known scaffold hashes to:

- replace seed placeholders with bundle content;
- remove unselected capability artifacts;
- replace source CI with compiled project CI; and
- remove recognized template-maintenance artifacts.

Any unexpected bytes at a path proposed for replacement or deletion block the whole mutation.
Bootstrap never treats “looks like a template file” as sufficient evidence.

GitHub snapshots retain their one-time semantics. The presence of `.copier-answers.yml` identifies
the update-capable path, but bootstrap does not synthesize Copier lineage for a GitHub snapshot.

### Source-target protection

`plan`, `apply`, `plan-add`, `add`, `plan-reconcile`, `reconcile`, and `recover` accept optional
`--target PATH` and otherwise use the current directory. Every command displays the normalized target.

Mutation refuses a Git remote that normalizes to the canonical template repository. Initial apply
also requires either a recognized scaffold or an equivalent-input initialized manifest. Existing
managed drift, unsafe symlinks, Copier conflict evidence, or an unresolved transaction journal blocks
mutation.

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
    "prd": "content/prd.md",
    "readme": "content/readme.md",
    "validation_hook": "content/validate-project",
    "security_policy": "content/security.md"
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

The project name and default branch are mechanical settings. Repository owner/name is intentionally
absent because GitHub exposes current repository identity at runtime and persisted slugs become stale
after forks, transfers, and renames.

README, PRD, SECURITY, and supplied legal text must be valid UTF-8 text. The validation hook may be any
regular executable file and is copied byte-for-byte to `scripts/validate-project` with an executable
mode. Referenced paths are relative to the JSON file, must remain inside the bundle after
normalization, and may not traverse a symlink. Inline Markdown is not supported in v1.

Licensing modes are:

- `retain-apache-2.0`, with no adopter license path;
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

### Initial input fingerprint

The initializer and direct-input path normalize the mechanical answer model, hash every referenced
content file, and compute one `initial_input_fingerprint`. JSON whitespace, key ordering, and source
file locations do not affect it; normalized values and content bytes do.

When `apply` finds an existing manifest:

- an equal fingerprint plus healthy managed state returns a validated no-op;
- an equal fingerprint plus drift fails with recovery guidance; and
- a different fingerprint fails and identifies `add`, `reconcile`, or the deferred reconfiguration
  lifecycle as appropriate.

The fingerprint does not authorize re-copying adopter-owned files.

## Project manifest

`.agentic-template.json` is canonical mechanical state. Conceptually it records:

```text
schema_version and compiler_contract_version
generation_path
template-source content fingerprint
project name and default branch
initial input fingerprint
profile ID and frozen profile capability list
explicit capability additions
effective dependency closure
normalized non-secret settings
licensing decision
external activation requirements
selected render fingerprint
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

The template-source fingerprint covers the compiler, catalog, render sources, schemas, compatibility
fixture, and maintenance inventory available to that generated repository. The selected render
fingerprint covers core definitions, the exact effective capability definitions, and normalized
settings. It excludes unselected capabilities so unrelated catalog additions do not create false
project drift.

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

python3 scripts/bootstrap-project.py plan --answers PATH/bootstrap.json [--target PATH]
python3 scripts/bootstrap-project.py apply --answers PATH/bootstrap.json [--target PATH]

python3 scripts/bootstrap-project.py plan-add --answers addition.json [--target PATH]
python3 scripts/bootstrap-project.py add --answers addition.json [--target PATH]

python3 scripts/bootstrap-project.py plan-reconcile [--target PATH]
python3 scripts/bootstrap-project.py reconcile [--target PATH]

python3 scripts/bootstrap-project.py recover [--target PATH]
```

`init` creates a complete reviewable bundle only. With `--init-answers`, referenced source paths are
resolved relative to that seed document and copied into the output bundle. The initializer uses a
temporary sibling and installs the complete bundle only after validation.

All plan commands run every preflight possible without installing the target plan and report stable,
ordered path operations with old and new hashes. They do not invoke the adopter hook against a
partially rendered target. Apply commands repeat preflight to avoid time-of-check/time-of-use
assumptions.

Exit codes are stable:

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

For the same template-source fingerprint, normalized input model, referenced content bytes, profile
snapshot, and effective capability set, output is byte-for-byte deterministic:

- generated JSON uses canonical key ordering and separators;
- generated text uses UTF-8 and LF endings;
- generated file modes are declared;
- adopter content bytes are preserved;
- timestamps, random IDs, current working directories, hostnames, and environment variables do not
  enter final output; and
- output path enumeration is sorted.

Transaction journals may use unique temporary identifiers because they are transient recovery state,
not accepted generated output.

## Transaction and recovery semantics

Mutation is transactional only for the exact planned filesystem paths.

1. Validate inputs, source definitions, target topology, old hashes, and rendered bytes.
2. Stage every new file without changing accepted target paths.
3. Persist a target-local journal containing the operation list, expected hashes, backup locations,
   and transaction phase.
4. Back up every replaced or deleted planned path.
5. Install operations in deterministic order using same-filesystem atomic replacements where
   available.
6. Run `python3 scripts/validate-repository.py` from the target.
7. On success, remove backups and the journal and report activation instructions.
8. On ordinary failure, restore all planned paths and retain clear diagnostics if restoration is not
   complete.

An interrupted journal blocks `apply`, `add`, and `reconcile`. `recover` validates the journal and
backups, restores the pre-operation state, and removes recovery state only after verifying restored
hashes. It never resumes forward.

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
- current managed bytes equal to old manifest hashes; and
- the exact persisted effective capability set to remain resolvable without adding or removing an ID.

It may update implementations, selected documentation, render fingerprints, and managed hashes. It
may not re-expand a profile, modify seed-once or adopter files, select a template version, merge drift,
or invoke an implicit migration.

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

Validates one bootstrapped project instance:

- manifest schema and internal topology;
- profile snapshot, explicit additions, and effective capability set;
- initial input, template-source, and selected-render fingerprint structure;
- managed artifact modes and hashes;
- licensing decision and required preserved provenance;
- required durable documentation;
- arbitrary executable validation hook presence and mode;
- seed-once project-validation workflow's bounded contract;
- external requirement declarations; and
- absence of required placeholders.

It reports managed fingerprint mismatch as “reconcile required” only when individual managed hashes
still match. Individual hash mismatch is managed drift and must be resolved before reconciliation.

### `scripts/validate-project`

This is the canonical target path for the adopter-supplied arbitrary executable. It owns
product-specific validation, chooses its own toolchain, and may create normal validation artifacts.
The aggregate invokes it directly rather than through Python. Native Windows execution is not a v1
guarantee.

### `scripts/validate-repository.py`

Remains the canonical ordered boundary:

1. template contract;
2. project readiness; and
3. adopter project validation.

Source-only GitHub/Copy fixtures and profile/capability matrix suites are not added to this portable
generated-project boundary.

## Licensing and provenance

Bootstrap requires one explicit licensing choice and accepts no license default.

For `retain-apache-2.0`, the source Apache-2.0 text remains the root `LICENSE`. For
`provided-project-license` and `private`, the adopter-supplied legal text becomes root `LICENSE`. The
conservative minimum preservation design keeps `NOTICE.md` and retains the template Apache-2.0 text
under `LICENSES/Apache-2.0.txt` when it is no longer the root license.

Before implementation fixes these paths, a licensing/provenance audit must:

- inspect every bundled skill's upstream license and notice requirements;
- confirm whether the proposed Apache and notice locations satisfy redistribution obligations;
- identify any notice that must remain verbatim;
- define how adopter additions to notices are preserved; and
- update this design and an ADR if the required layout differs.

The audit may strengthen preservation requirements but may not authorize bootstrap to invent project
legal terms or declare the resulting project legally valid. Bootstrap reports the selected mode and
preserved provenance as mechanical facts only.

## Durable adopter documentation

The following bootstrap-managed documents are rendered from core and selected capability fragments:

- `docs/delivery-workflow.md`: canonical validation, CI/release gates, review flow, and recovery;
- `docs/template-updates.md`: GitHub snapshot or Copier lineage, compatible reconciliation, and drift;
- `docs/capabilities.md`: frozen profile, additions, effective set, settings safe to display, and
  dependencies;
- `docs/github-setup.md`: required secrets, safe skipped behavior, Actions/ruleset steps, and the
  distinction between release and merge gates; and
- `CONTRIBUTING.md`: developer workflow and links to the authoritative product documents.

Capability addition and reconciliation update these documents atomically with their related
artifacts. The manifest hashes them. V1 intentionally treats direct edits as drift; adopters put
project-specific prose in README, product docs, or other adopter-owned files. Managed regions and
adopter fragments are proposed future changes.

## Template-maintenance inventory

`.agentic-template/maintenance-artifacts.json` declares paths that exist only to develop and release
the template source, such as source fixture suites, Copier smoke workflow, and historical
template-source specs and plans.

The inventory records each path, expected source hash or tree hash, and whether the path is a regular
file or directory tree. It may not overlap a static, seed-once, adopter, or bootstrap-managed path.

- Copier excludes the declared inventory from generated projects.
- GitHub snapshot bootstrap removes only entries whose complete bytes match the declared source
  shape.
- A modified, missing-with-children, unsafe, or partially matching entry blocks initial cleanup and
  reports the exact path.
- Later `add` and `reconcile` operations never use the inventory to delete adopter files.

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
path and one next action. Diagnostics never include secret values. Multiple independent preflight
errors are returned in stable sorted order; mutation and recovery failures stop at the first point
where continuing could destroy evidence.

## Verification strategy

### Unit coverage

- Schema normalization and canonical serialization.
- Input path confinement, symlink rejection, and UTF-8 requirements.
- Profile expansion and exact dependency closure.
- Cycle, collision, type, slot, and compatibility detection.
- Initial input, source, render, and artifact hashing.
- Deterministic renderers and typed setting encoders.
- Plan ordering and no-op classification.
- Journal state transitions and recovery validation.

### Generated-project fixture matrix

Run both generation paths across:

- all four named non-custom profiles;
- representative custom empty, single, dependent, and multi-capability sets;
- all three licensing modes;
- required capability setting variations; and
- missing/present external-activation structures without using real secrets.

Each case proves untouched failure where applicable, successful bootstrap, canonical validation,
identical-input no-op, exact artifact presence/absence, stable manifest, and absence of source-only
maintenance files.

### Lifecycle coverage

- Add an independent capability.
- Add `cachix-publish` and resolve `nix`.
- Repeat a satisfied addition.
- Reject conflicting existing settings and removal.
- Modify one managed artifact and prove add/reconcile refuse it.
- Perform a compatible Copier update, then reconcile.
- Change an unselected capability and prove no selected render drift.
- Present an incompatible capability fixture or unknown manifest schema and prove zero writes.
- Inject failure before the journal, during each mutation phase, during canonical validation, and
  during rollback.
- Recover an interrupted transaction and verify exact pre-operation planned-path hashes.
- Let the adopter hook create an unrelated validation artifact and prove rollback leaves it alone.

### Workflow and security coverage

- Run `actionlint` on source and every generated workflow fixture.
- Assert the managed caller passes no secrets and has read-only permissions.
- Assert the seeded project-validation workflow invokes the canonical boundary and has no privileged
  environment.
- Assert release depends on the full project-validation call and selected checks.
- Assert missing Gemini/Cachix secrets create successful skip guidance.
- Assert privileged PR Agent or Cachix publishing jobs cannot start when preflight is false.
- Assert persisted checkout credentials and real credential-looking values are absent.

### Release gate

Before release:

- the PRD and Copier ADR reflect the approved boundary;
- the licensing/provenance audit is complete;
- repository formatting, linting, tests, builds, and template-source fixtures pass;
- both generation paths pass the full profile matrix;
- Copier update coverage proves seed-once preservation and derived reconciliation;
- security/workflow validation passes; and
- verification-before-completion and substantive code review find no unresolved required issue.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A catalog change silently changes an old snapshot | Persist exact sets, freeze compatibility fixtures, and block incompatible reconciliation |
| Copier and bootstrap both modify one output | Exclude derived/seed-once paths from Copier and validate ownership collisions |
| GitHub bootstrap deletes adopter work | Delete only declared exact-hash scaffold or maintenance paths; otherwise fail the whole plan |
| A managed file is edited directly | Readiness and mutation compare manifest hashes and provide restore/reconcile guidance |
| A crash leaves mixed output | Durable journal, backups, blocked mutation, and explicit rollback-only `recover` |
| The adopter hook creates side effects | Limit the transaction claim to planned paths and never delete unknown hook artifacts |
| Missing secrets fail every PR | Read-only activation preflight and successful skip guidance |
| A privileged job starts merely to check a secret | Separate preflight and privileged jobs with dependency-gated start conditions |
| Manifest records stale external state | Persist requirements only; inspect live state in workflows or the future doctor |
| Repository slug becomes stale | Read live GitHub context and omit owner/repository from the manifest |
| GitHub snapshot lacks source commit lineage | Record content fingerprints without inventing release metadata |
| A handwritten YAML checker overclaims correctness | Bounded policy checks, source `actionlint`, GitHub runtime validation, and explicit documentation |
| Managed documentation blocks customization | Keep product prose in adopter files and retain fragments/managed regions as future work |
| License replacement loses obligations | Mandatory conservative preservation plus a blocking provenance audit |
| Declarative rendering becomes too restrictive | Add typed slots first; consider signed/sandboxed plugins only through a future design |

## Proposed future changes

These options were discussed and intentionally deferred. They are viable extension proposals, not
rejected alternatives.

### Bootstrap experience and product guidance

- One-command interactive initialize-and-apply convenience over the same plan/apply engine.
- Partial bundles, staged readiness, or a separate finalize command.
- Inline prose fields with explicit escaping and review behavior.
- Guided PRD authoring without treating generated prose as authoritative until adopted.
- Stack presets and recommendation logic without adding an implicit engine default.
- Persisting richer initialization answers to regenerate selected documentation.
- Opt-in reset or regeneration of seed-once files after an ownership-aware migration design.

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
- SPDX, SBOM, and richer license/provenance automation.
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
- Treating capability removal as reconciliation.
- A custom version-aware updater that competes with Copier.
- Parallel Copier and Python rendering implementations.
- Mandatory trusted Copier task execution.
- Restricting the adopter validation hook to Python.
- Requiring `--target` solely as an operator-attention mechanism.
- A handwritten general-purpose YAML parser presented as complete semantic validation.
- Legal boilerplate authored by bootstrap or a claim that a selected license is legally sufficient.

## Required follow-up documents

Implementation must update or add:

- `docs/prd.md`, promoting the approved bootstrap behavior into authoritative requirements;
- `docs/adr/0001-use-copier-for-template-updates.md`, clarifying that Copier updates compiler inputs
  while bootstrap reconciles derived outputs;
- an ADR for the capability compiler and ownership model if the implementation plan confirms the
  boundary is architectural;
- the licensing/provenance audit record and any resulting ADR;
- generated adopter documentation described above; and
- source-maintainer instructions for adding a compatible capability.

## Open questions and implementation gates

No product-behavior decision is open for v1.

The licensing/provenance audit is a blocking implementation gate. If it changes the proposed
`LICENSES/Apache-2.0.txt` or `NOTICE.md` layout, this design must be amended and reconfirmed before
license-writing implementation proceeds.

## References

- `docs/prd.md`
- `docs/project-readiness.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/specs/2026-08-03-project-readiness/design.md`
- [GitHub: Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/)
- [Copier updating](https://copier.readthedocs.io/en/stable/updating/)
