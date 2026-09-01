# Packaged Capability CLI

## Status

Approved design for Rygor's first packaged-release product reset. This design replaces the current
template-repository product direction without rewriting Git history, tags, release records, or archived specifications.
The current product requirements document remains authoritative until implementation replaces it with
the contract defined here; the implementation must update that document before relying on the new
requirements.

## Problem

Rygor currently combines three roles in one Git repository: template source, copied bootstrap engine,
and generated-project delivery assets. Using it requires GitHub template generation or Copier, and
generated repositories inherit source lifecycle, cleanup, reconciliation, and copied Python machinery.
Those paths make distribution, upgrades, adoption, ownership, and hosting support more complicated than
the value Rygor is intended to provide.

The desired product is a repository-delivery tool. A user should run one packaged command against a new
or existing Git repository, choose a small set of capabilities, and receive deterministic CI,
documentation, validation integration, and release automation. The target repository should retain
only declarative configuration, applied state, managed artifacts, and adopter-owned product content; it
should not contain a copy of the Rygor engine.

Rygor must remain technology-stack-neutral and must not make GitHub an architectural assumption. The
initial release will implement GitHub delivery and Gemini-backed PR Agent behavior because those are the
behaviors already present, while capability contracts must permit future GitLab hosting and alternative
AI backends without redesigning the core.

There are no users of the current v1 or v2 generated-project contracts. The current implementation may
therefore be removed rather than migrated. Repository history is retained. The package redesign is
released at the version semantic-release computes from the repository state and the transition's
breaking-change signal when the completed implementation reaches `main`; this design calls that exact
version `R` and its major component `M`. Neither value is frozen in advance.

## Scope

### In scope

- Convert Rygor into a buildable Python distribution with a `rygor` CLI and embedded resources.
- Distribute the initial release as an HTTPS direct wheel with a mandatory SHA-256 digest, without
  publishing Rygor to a package registry.
- Keep engine coordinate, acquisition source, and exact build identity distinct so registry resolution
  can be added later without changing the project lifecycle.
- Support deterministic creation of a new Git repository and adoption of an existing non-bare Git
  working tree.
- Store adopter-controlled desired configuration separately from Rygor-controlled applied state.
- Compile built-in capabilities through provided contracts and typed contributions.
- Implement the already-existing behavior as `github-ci`, `semantic-release`, `nix`,
  `cachix-publish`, and `pr-agent` capabilities.
- Configure `pr-agent` with Gemini only while keeping its AI backend an explicit setting.
- Support capability enablement, disablement, and reconfiguration by editing desired configuration and
  applying a previewed plan.
- Detect managed drift, restore recorded output, upgrade the engine explicitly, and recover interrupted
  mutations.
- Preserve the functional-core/effectful-shell design and the existing recoverable transaction
  guarantees where they remain applicable.
- Validate the built wheel, its embedded resource index, the complete initial capability matrix, and
  Rygor's own repository through dogfooding.
- Replace active product, contributor, domain, and operational documentation to describe the packaged
  product.
- Add an ADR that supersedes the Copier and adopted-lifecycle decisions while retaining historical ADRs
  and specifications.

### Out of scope

- A `gitlab-ci` implementation in the first packaged release.
- AI backends other than Gemini in the first packaged release.
- Third-party capability packages, Python entry-point discovery, subprocess plugins, or a stable external
  capability API.
- Publication to PyPI or another package registry.
- A universal provider-neutral CI language.
- Automatic mutation of repository secrets, branch protection, environments, or other hosting settings.
- Non-Git targets and bare repositories.
- Migration of manifests or copied engines produced by the template-era implementation.
- Copier generation, GitHub template generation, template reconciliation, source baselines, or snapshot
  cleanup.
- Rewriting Git history or deleting existing tags and releases.
- A stable public Python library API.
- Offline engine acquisition. A fresh clone may fetch its exact checksummed wheel.

## User Stories

### US-1: Install delivery infrastructure into a new repository

As an adopter, I want to run a checksummed Rygor wheel with an explicit profile so that a new Git
repository receives a deterministic delivery foundation without copying the Rygor engine.

Priority: must.

- Given a target path that does not exist or is empty, when the adopter runs `rygor new` with a valid
  profile and settings, then Rygor creates a non-bare Git working tree and installs one complete,
  mechanically valid project state.
- Concurrent `new` attempts for the same canonical target serialize before target creation or Git
  initialization; an interrupted attempt retains enough evidence to restore an absent or empty target.
- The generated project records the exact engine coordinate, direct-wheel source, wheel digest,
  normalized capability configuration, and managed inventory.
- No unselected capability artifact is present.
- Running the same wheel with the same normalized inputs produces byte-identical managed output, modes,
  and operation ordering.

### US-2: Adopt an existing repository safely

As an adopter, I want to add Rygor to an existing Git repository so that I can gain managed delivery
behavior without recreating or silently overwriting my product.

Priority: must.

- Given a manifest-free non-bare Git working tree, `rygor plan adopt` reports every collision and the
  ownership result before mutation.
- A managed-path replacement requires an explicit per-path collision decision and a plan digest bound to
  the observed target.
- Existing adopter content remains adopter-owned unless an explicitly approved replacement installs a
  managed artifact at that path.
- An undeclared collision, unsafe path, unsupported filesystem type, target identity change, or stale plan
  refuses the operation without partial installation.

### US-3: Configure capabilities declaratively

As an adopter, I want one reviewable configuration file so that capability changes and settings are
understood through ordinary Git review.

Priority: must.

- `.rygor/project.toml` contains the explicit effective capability set and every normalized non-secret
  setting.
- A profile expands only during creation or adoption and is retained solely as provenance.
- Editing desired configuration does not mutate generated artifacts until `plan apply` and `apply` are
  run.
- Enabling, disabling, or reconfiguring capabilities re-renders shared consumer artifacts in one
  transaction.
- Secret values are rejected from configuration and state.

### US-4: Understand repository state

As a developer or coding agent, I want a read-only status command with actionable diagnostics so that I
can distinguish desired changes, drift, engine compatibility, activation requirements, and recovery.

Priority: must.

- `rygor status` never runs an adopter hook, prompts, mutates files, or queries a hosting service.
- Text and JSON representations carry the same stable diagnostic identifiers, paths, capabilities, and
  next actions.
- Status distinguishes healthy state, pending desired configuration, managed drift, update availability,
  an engine that is too old, invalid capability resolution, unverified external activation, corrupted
  state, and pending recovery.
- A status result obtained with an older engine is explicitly marked incomplete when the repository
  requires newer semantics.

### US-5: Validate any technology stack

As an adopter, I want Rygor to own the mechanical delivery checks while my repository owns its product
validation so that the same delivery model works for Python, Nix, Node, Rust, or another stack.

Priority: must.

- `rygor validate` checks the Rygor configuration, applied state, managed inventory, mechanical readiness,
  and then calls the extensionless adopter-owned `scripts/validate-project` hook.
- Rygor does not generate a product `pyproject.toml` or require the product hook to use Python.
- Hook results are point-in-time evidence and are not persisted or replayed during recovery.
- Hosting CI invokes the exact configured Rygor engine and the same validation boundary.

### US-6: Recover and restore safely

As an adopter, I want interrupted operations and managed drift to have explicit remedies so that Rygor
never leaves an ambiguous partially managed repository.

Priority: must.

- Every mutation runs under one continuous mutation lease and write-ahead journal. `new` begins with a
  parent-scoped bootstrap lease before `.git` exists and hands off without a gap to the canonical Git
  target lock; established repositories use the canonical lock directly.
- Before sealing, failure restores exact planned bytes and modes or retains evidence for explicit
  recovery.
- After sealing, recovery verifies the installed state and completes cleanup forward.
- Unknown third states are preserved and reported rather than overwritten.
- `restore` uses the recorded applied configuration and engine identity, never pending desired
  configuration, and does not upgrade the project.
- `apply` and `restore` run only under the recorded engine build. A running engine with a different
  resource or catalog digest refuses and names the exact wheel coordinate, source, and digest that can
  act on the repository.

### US-7: Evolve within the packaged release's stable major version

As an adopter, I want newer Rygor releases within packaged major `M` to understand repositories created
by earlier releases in that major, and older engines to fail safely on newer behavior, so that minor
updates add value without creating breaking migrations.

Priority: must.

- A newer engine in major `M` reads every valid earlier same-major state and can propose a non-lossy
  upgrade.
- Running a newer minor against an older project gives a non-blocking update notice during inspection;
  no manifest is rewritten automatically.
- A repository records its exact applied engine and minimum compatible engine.
- An older engine may provide limited inventory inspection, but it refuses validation, rendering,
  restoration, and mutation when the repository requires a newer minor.
- Major version `M + 1` is required only when valid major-`M` configuration cannot be preserved or
  interpreted safely.

### US-8: Extend hosting and AI choices without a core redesign

As a Rygor maintainer, I want hosting and tool variants to compose through narrow contracts so that a
future GitLab capability or PR Agent backend does not multiply combination-specific implementations.

Priority: should.

- Hosting capabilities satisfy the abstract `hosting` contract while retaining provider-specific
  contracts such as `hosting.github`.
- `nix` remains independently useful without hosting and contributes optional CI validation when a
  compatible consumer is present.
- `pr-agent` remains the stable capability ID; `ai_backend = "gemini"` selects the only initial backend.
- Adding an AI backend later does not require a new capability ID or hosting templates for every
  host/backend combination.

### US-9: Dogfood the released product and candidate artifact

As a Rygor maintainer, I want the repository to be managed by a released Rygor while candidate wheels are
tested independently so that self-hosting does not create a circular release dependency.

Priority: must.

- The Rygor repository records the latest adopted released wheel, not a local development path.
- Candidate wheels execute against disposable new and adopted repositories before publication.
- The first package release is produced by the existing release machinery, attached as a checksummed
  release artifact, and followed by adoption of the Rygor repository.
- Subsequent releases are validated through the previously released engine's managed delivery
  foundation, tested from the candidate wheel, published as release assets, and adopted in a follow-up
  engine upgrade.
- Self-adoption requires no `keep-existing` exception. Rygor's release preparation rides the same
  `scripts/release-prepare` hook and capability settings every adopter uses, so its managed `.releaserc`
  and release workflow are the rendered ones.

## Constraints

- `docs/prd.md` is the product source of truth. Its current template/Copier requirements conflict with
  this design and must be replaced as the first authoritative product-document change.
- Semantic-release is authoritative for the release coordinate. The completed package transition carries
  a breaking-change signal and is delivered through one release-triggering integration boundary; `R` is
  the next major version computed from the latest release that exists when that boundary reaches `main`.
  Intermediate incomplete states do not merge as release-triggering package changes. Existing history,
  tags, and releases remain.
- Preparatory work that carries no release-triggering conventional-commit type may land on `main`
  incrementally, provided every intermediate state leaves the repository's own validation green and the
  template-era product still buildable and releasable. Packaging metadata, embedded resources, engine
  identity, and documentation are eligible; capability rendering, lifecycle command behavior, and the
  removal of the template implementation are not, because they change the delivered product. Only the
  remaining release-triggering change is held on one integration branch until its full gate passes.
- The Python floor remains the repository's supported floor and the project uses uv, Ruff, basedpyright,
  pytest, and the canonical parallel test invocation.
- The build must produce a wheel and source distribution; release validation must exercise the built
  wheel in a clean environment.
- The first distribution source is an HTTPS direct wheel with a mandatory SHA-256 digest. Registry
  resolution is a future source variant, not an initial implementation requirement.
- Only built-in capabilities execute. Capability definitions are data and pure transformations; they do
  not receive direct filesystem, process, network, environment, clock, Git, or terminal access.
- Rygor never stores secret values and does not claim to observe whether a hosting secret is configured.
- Generated validation remains least-privileged. Secret-bearing automation is isolated from untrusted
  contributor execution.
- A non-bare Git working tree is required after initialization because target identity, durable recovery
  storage, and managed operations are scoped through Git. The pre-Git portion of `new` uses only the
  bounded parent-scoped bootstrap evidence defined below.
- Inspection never mutates. Planning never prompts. Destructive operations have no interactive
  confirmation path and require a freshly bound plan digest.
- The threat model covers crashes, accidental concurrency, drift, target substitution, unsafe paths, and
  corrupted state. It does not claim protection against a malicious local actor able to alter the target
  and `.git` concurrently with the process.

## Context

The current repository is a non-packaged Python project named `rygor` at version 2.6.0. It declares
runtime dependencies but has no build backend or console-script entry point. The bootstrap engine lives
under `scripts/bootstrap`, public invocation is through `scripts/bootstrap_project.py`, and resource
loading assumes the template checkout is present.

Current generation has GitHub snapshot and Copier paths. Projects receive copied lifecycle source,
bootstrap code, readiness scripts, generated-project dependencies, source-baseline state, cleanup
inventories, and path-specific reconcile rules. These behaviors are deliberate in the prior design but
are unnecessary once the engine is acquired as a package.

The current capability catalog already implements the behavior that becomes the initial built-in catalog:

- GitHub CI is implicit core output rather than a selectable capability.
- `semantic-release` contributes release automation.
- `nix` installs Nix resources and enriches CI.
- `cachix-publish` depends on Nix and contributes publication behavior.
- `pr-agent-gemini` installs Gemini-specific PR Agent configuration and workflows.

The current renderer also generates a product `pyproject.toml` containing Rygor implementation
dependencies. That output is removed because package dependencies belong to Rygor and product toolchains
belong to adopters.

The existing functional core, typed outcomes, canonical JSON, path validation, target observation,
planning, locking, journaling, transaction machine, rollback, recovery, presentation, and extensive
stateful tests provide useful implementation evidence. They are retained conceptually and moved behind
the package boundary where compatible. Copier, generation-path, template-root, source-baseline, cleanup,
and reconcile concepts are deleted rather than adapted.

### Research mapping

| Concern | Existing solution | Decision | Current requirement |
|---|---|---|---|
| Typed functional core | Immutable values and decisions under `scripts/bootstrap` | reuse | Deterministic, analyzable plans and closed outcomes |
| Effect boundaries | Filesystem, Git, process, and observation adapters | modify | Package core must remain free of ambient effects |
| Canonical state and plans | Canonical JSON, checksums, plan digests | reuse | Reviewable state, stale-plan refusal, and deterministic JSON |
| Recoverable mutation | Lock, journal, rollback, recovery, transaction machine | modify | Every managed mutation must be recoverable |
| Capability resolution | Catalog, dependency resolver, profiles, contribution compiler | modify | Provided contracts, typed contributions, settings, and explicit hosting |
| GitHub CI | Implicit core workflow compilation | modify | `github-ci` is a selectable hosting/CI consumer |
| Nix CI coupling | Nix fragments enrich implicit GitHub CI | modify | Nix must work without GitHub and optionally enrich selected CI |
| PR Agent | Fixed `pr-agent-gemini` definition and Gemini workflows | modify | Stable `pr-agent` capability with an explicit Gemini backend setting |
| Template resource lookup | Checkout-relative `_template_root()` and source bundle | delete | The wheel embeds a fingerprinted resource index |
| Copier and snapshots | `copier.yml`, answers, generation paths, source baselines | delete | Package-only lifecycle has no template lineage |
| Adopted lifecycle source | Copied engine and lifecycle inventory | delete | Generated repositories do not contain the Rygor engine |
| Product validation | Copied Python aggregate validator and extensionless hook | modify | Packaged `rygor validate` invokes adopter-owned stack-neutral hook |
| Product dependencies | Generated `pyproject.toml` with Pydantic and PyYAML | delete | Rygor dependencies remain inside its tool environment |
| Python distribution | Project metadata without build backend or script | new | Buildable direct wheel and `rygor` console entry point |
| Desired/applied split | Immutable answer manifest and append-only additions | modify | Reviewable reconfiguration and safe backend switching |
| Engine source model | Template/version identity | new | Direct wheel now and registry source later |
| Minor compatibility floor | Frozen v1 schema corpus | modify | Newer minors read older state; older engines fail safely |
| Dogfooding | Source repository compiled as an integrated fixture | modify | Released-engine self-management plus candidate-wheel fixtures |
| Active documentation | Template, Copier, and GitHub-centric guidance | modify | Package-only public contract and capability terminology |
| Historical ADRs/specs | Accepted decisions and archived records | reuse | Preserve history; supersede rather than rewrite |

## Architecture

### Package boundary

Rygor is one Python distribution with an internal catalog of built-in capabilities and embedded
resources:

```text
src/rygor/
├── cli/                 command decoding and text/JSON presentation
├── application/         use-case orchestration and effect ports
├── core/                pure values, decisions, resolution, rendering, planning
├── capabilities/        built-in definitions and backend definitions
├── adapters/            filesystem, Git, process, environment, lock, journal
└── resources/           core and capability-owned packaged artifacts
```

The exact module split may remain smaller where a direct module is clearer. The architectural rule is
the dependency direction: CLI and adapters depend on application and core contracts; pure core code does
not import effect adapters. The built-in registry is the composition root.

The public product surface is the `rygor` CLI, `.rygor/project.toml`, `.rygor/state.json`, and the JSON
command envelope. Internal `rygor.*` modules are not a stable library API in the initial packaged release.

### Operational pipeline

Every managed transition uses the same pipeline:

```text
observe
  -> decode state
  -> resolve capabilities
  -> render candidate
  -> build bound plan
  -> acquire mutation lease
  -> re-observe
  -> write journal
  -> apply operations
  -> run mechanical gates
  -> seal transaction
  -> clean recovery evidence
```

The mutation lease is the canonical Git target lock for an established repository and the bootstrap
lease for the pre-Git part of `new`. The bound plan includes the desired-configuration digest,
applied-state checksum, observed managed paths and modes, engine coordinate, engine build identity,
capability catalog digest, resource digest, and ordered operations. Re-observation under the applicable
lease must match the plan or execution refuses as stale.

Before sealing, a failure restores exact planned bytes and modes or retains the journal and backups for
explicit recovery. After sealing, recovery verifies the installed candidate and completes cleanup
forward. A durable restored state is distinguished from a partial rollback before evidence is removed.
An unrecognized third state blocks recovery and retains evidence.

### Domain model

**Core** is the provider-neutral policy, state, rendering, planning, validation, and lifecycle machinery.
It owns no GitHub, GitLab, Gemini, Nix, or product-stack assumption.

**Capability** is the only selectable extension unit. It is a built-in unit of desired repository
behavior, not a separately installable plugin.

**Capability definition** is the immutable declarative description of a capability: stable ID, provided
contracts, requirements, exclusive contracts, conflicts, normalized setting schema, standalone
artifacts, typed contributions, documentation, readiness obligations, and minimum engine requirement.

**Provided contract** is an abstract token fulfilled by a selected capability, such as `hosting`,
`hosting.github`, `delivery.ci`, or `toolchain.nix`.

**Requirement** is a dependency on a provided contract. A definition depends on a concrete capability ID
only when exact identity rather than substitutable behavior is required.

**Contribution** is a typed provider-neutral declaration emitted by a capability for a compatible
consumer to render. Contributions contain intent and required parameters, not raw GitHub or GitLab YAML.

**Consumer capability** is a capability such as `github-ci` that consumes contributions and renders them
as host-specific artifacts.

**Capability setting** is a normalized non-secret parameter stored in desired and applied configuration.

**AI backend** is a tool-internal variant selected by a capability setting. It is distinct from a
hosting capability and from a provided-contract provider.

**Capability catalog** is the fingerprinted set of definitions embedded in one Rygor build.

**Profile** is a creation-time shortcut expanded once into an explicit capability set. It is not a live
policy.

**Engine coordinate** is the logical distribution identity: distribution name, release version, and
entry point.

**Engine source** describes acquisition. For `direct-wheel`, `sha256` is the expected digest supplied
before acquisition and used to authenticate the downloaded bytes. `direct-wheel` is the only initial
implementation. The discriminator exists from schema 1 so a future `registry` source can be added without
changing lifecycle concepts.

**Build identity** is the acquisition-attested artifact SHA-256 plus the resource and catalog digests
computed from the installed distribution. For a direct wheel, `artifact_sha256` must equal the source's
expected `sha256` before Rygor renders resources from the wheel or seals project state.

The two digests are established differently and the distinction is load-bearing. `resource_digest` and
`catalog_digest` are recomputed by the running process from the installed package, so tampering after
installation is detected directly. `artifact_sha256` is not recomputed: an installed distribution
contains an unpacked tree, not the wheel it came from, and Rygor does not re-download the artifact in
order to hash it. Rygor reads the digest the installer already verified, from PEP 610
`direct_url.json` `archive_info.hashes`, or accepts it as explicit source metadata on the command line.
Integrity of the acquired bytes is therefore the installer's guarantee — `uv` rejects a wheel whose
bytes do not match the `#sha256=` fragment before any Rygor code runs — and Rygor's own check is that
the attested digest agrees with the digest the project declares or is about to persist. A missing,
unverifiable, or disagreeing attestation is an integrity failure that performs no project mutation.

**Minimum engine** is the earliest compatible engine coordinate permitted to interpret the repository's
persisted semantics. It is advanced only when a capability, setting, state field, migration, or rendered
behavior cannot be safely reproduced by an earlier engine.

**Desired configuration** is adopter-controlled declarative intent in `.rygor/project.toml`.

**Applied state** is Rygor-controlled evidence of the last sealed transition in `.rygor/state.json`.

**Managed artifact** is deterministic output owned exclusively by Rygor and represented in the inventory.

**Seed-once artifact** is initial product scaffolding created only when permitted, then owned by the
adopter and excluded from drift enforcement.

**Adopter-owned artifact** is existing or subsequently created product content outside the managed
inventory.

### Capability definition contract

Conceptually, each definition contains:

```python
CapabilityDefinition(
    id="pr-agent",
    provides=frozenset({"review.automation"}),
    requires=frozenset({"hosting", "delivery.ci"}),
    settings_schema=PrAgentSettings,
    artifacts=(),
    contributions=(ReviewAutomation(...),),
)
```

Definitions and backend definitions are pure. They receive normalized values and return declarations or
typed diagnostics. They cannot write files, inspect Git, read environment variables, execute processes,
query hosts, or change lifecycle schemas.

The core contribution vocabulary is deliberately small and closed for this release:

- `ValidationCheck`
- `PublishJob`
- `ReleaseJob`
- `ReviewAutomation`

New contribution kinds require a current capability use case. Rygor does not model arbitrary CI syntax.

`ReleaseJob` carries whether the job invokes the adopter release-preparation hook, so a consumer can
render the invocation and, when `toolchain.nix` is selected, wrap it in the project's Nix environment.
It carries no command text: the hook path is fixed and the adopter owns the script behind it.

Each contribution states whether consumption is optional or required. An optional Nix validation
contribution may remain unconsumed when no delivery CI is selected. Publish, release, and review
automation require exactly one compatible selected consumer. Required contributions are never silently
dropped.

A capability that emits a required contribution must also declare a requirement on the contract its
consumer provides. Otherwise the requirement graph and the routing graph can disagree: a selection would
satisfy every declared requirement, pass resolution step 3, and then fail at routing in step 6 with a
diagnostic about an unconsumed contribution rather than about the missing capability. `pr-agent`
therefore requires `delivery.ci` alongside `hosting`, matching `semantic-release` and `cachix-publish`.
Requirement granularity is a catalog invariant, not a stylistic choice; the resolver rejects a
definition whose required contributions have no corresponding declared requirement.

Resolution is deterministic:

1. Decode and normalize selected IDs and settings.
2. Compute requirements over provided contracts.
3. Reject missing providers, incompatible providers, and multiple providers of an exclusive contract.
4. Validate conflicts, setting schemas, and minimum-engine requirements.
5. Collect standalone artifacts and typed contributions.
6. Route each contribution to one compatible consumer according to its consumption rule.
7. Let consumers render host-specific artifacts.
8. Reject undeclared path collisions and unsafe paths.
9. Sort all identifiers, artifacts, contributions, diagnostics, and operations canonically.
10. Produce a complete render and contribution provenance for inventory diagnostics.

### Initial built-in catalog

| Capability | Provides | Requires | Behavior |
|---|---|---|---|
| `github-ci` | `hosting`, `hosting.github`, `delivery.ci` | none | Renders GitHub workflows and consumes validation, publish, release, and review contributions |
| `nix` | `toolchain.nix` | none | Seeds `flake.nix` and `flake.lock` once and emits an optional validation contribution |
| `cachix-publish` | `delivery.publish` | `toolchain.nix`, `delivery.ci` | Emits a Cachix publish job; normalizes `cache_name`; documents `CACHIX_AUTH_TOKEN` |
| `semantic-release` | `delivery.release` | `hosting`, `delivery.ci` | Renders `.releaserc`; seeds `scripts/release-prepare`; emits trusted release automation |
| `pr-agent` | `review.automation` | `hosting`, `delivery.ci` | Emits host-consumed PR review automation using the configured AI backend |

`hosting` is exclusive: a project selects exactly one hosting provider when a selected capability requires
hosting. A future `gitlab-ci` may provide `hosting`, `hosting.gitlab`, and `delivery.ci` and consume the
same typed declarations. Provider-specific contracts remain available only for semantics that cannot be
substituted.

Nix does not require GitHub or any hosting capability. It always seeds its standalone resources. When
`github-ci` is selected, that consumer incorporates Nix's optional validation check and becomes more
capable.

Initial profiles expand as follows:

| Profile | Explicit initial capability set |
|---|---|
| `portable` | `github-ci` |
| `release-automated` | `github-ci`, `semantic-release` |
| `nix-enabled` | `github-ci`, `nix` |
| `integrated` | `github-ci`, `semantic-release`, `nix`, `cachix-publish`, `pr-agent` |

Users may also select a custom set, including `nix` without hosting.

### PR Agent backend composition

The capability ID is `pr-agent`, never `pr-agent-gemini`. Hosting and AI choice are independent axes:

```text
                  pr-agent
                 /        \
        hosting consumer   AI backend
        GitHub / GitLab     Gemini / future alternatives
```

The initial normalized settings are:

```toml
[capabilities.pr-agent]
ai_backend = "gemini"
model = "gemini/gemini-3.7-flash"
fallback_models = ["gemini/gemini-3.5-flash-lite"]
```

The initial backend registry contains only `gemini`. Its definition supplies allowed model configuration,
required secret references, environment wiring declarations, and readiness guidance. It requires the
external secret name `GEMINI_API_KEY`; the value is never accepted or persisted.

A future backend is added as another backend definition under the same capability ID. Reconfiguration
changes desired settings, produces a normal bound plan, replaces workflow references transactionally,
and removes obsolete secret references from managed output. Rygor never migrates or copies secret values.

### Adopter release preparation

Stack neutrality forces an extension point here. A `semantic-release` capability that renders a complete
`.releaserc` must decide how to stamp the computed version and how to produce release artifacts, and
those are product-toolchain decisions Rygor does not own. A rendered prepare command that runs `uv` is
not a delivery contract, it is a Python contract, and it is useless to a Rust or Node adopter. Every
adopter that ships an artifact needs this, so it is a capability contract rather than a Rygor exception.

`semantic-release` therefore renders a fixed prepare command that invokes an adopter-owned hook:

```json
"prepareCmd": "scripts/release-prepare ${nextRelease.version}"
```

`scripts/release-prepare` is seed-once, extensionless, and stack-neutral, receiving the computed version
as its first argument, exactly as `scripts/validate-project` is the stack-neutral validation boundary. It
stamps the version, builds whatever the project distributes, and writes the files the capability's
settings name. Rygor's own copy performs the version handoff, compatibility-corpus freeze, wheel and sdist
build, rebuilt-wheel revalidation, and checksum generation.

The remaining declarations are settings, so they stay reviewable data rather than shell text:

```toml
[capabilities.semantic-release]
prepare_hook = true
commit_assets = ["pyproject.toml", "uv.lock", "tests/data/releases"]
release_assets = ["dist/*.whl", "dist/*.tar.gz", "dist/SHA256SUMS"]
```

`commit_assets` becomes the `@semantic-release/git` asset list and `release_assets` the
`@semantic-release/github` asset list. Both are target-relative globs validated for path safety like any
managed path; neither may escape the worktree or name a reserved runtime path. An empty `commit_assets`
renders no `@semantic-release/git` plugin at all rather than a plugin with an empty asset list, because
the latter is a configuration that commits nothing and fails differently across plugin versions.

`prepare_hook` defaults to `false` and both asset lists default to empty, so a project created with
`release-automated` or `integrated` releases a tag and release notes and works on its first run without
the adopter writing anything. Shipping an artifact is the opt-in. The seeded `scripts/release-prepare`
is a working no-op that exits 0 and documents its contract in comments, so enabling the hook before
filling the script in cannot break a release either.

Because a managed `.releaserc` names a seed-once script, `rygor validate` treats the pair as a capability
readiness obligation: when `prepare_hook` is set, the hook must exist and be executable. Drift detection
deliberately ignores seed-once paths, so without this check a deleted hook would first surface in the
trusted release job, after the tag decision.

The release job's toolchain comes from existing contract composition rather than a new axis. The
`ReleaseJob` contribution declares that the job invokes the prepare hook; when `toolchain.nix` is
present, `github-ci` renders `nix develop -c scripts/release-prepare "$VERSION"`, the same way selected
CI already becomes more capable in the presence of Nix. Without Nix the hook bootstraps whatever it
needs, which is the adopter's business.

`flake.nix` and `flake.lock` are seed-once rather than managed for the same reason. A dev shell is a
declaration of product toolchain — the current template hardcodes `python314` and `uv` — and Rygor owns
no such thing. The `nix` capability seeds them once and then leaves them to the adopter, while its
optional `ValidationCheck` contribution keeps working against whatever flake the repository ends up with.

### Ownership and render model

The candidate render partitions paths into:

- Rygor-managed output, included in the inventory and reproducible from the applied configuration and
  exact engine build.
- Seed-once product scaffolding, created only when absent or explicitly permitted and then excluded from
  the inventory. `scripts/validate-project`, `scripts/release-prepare`, `flake.nix`, and `flake.lock` are
  all seed-once: each declares product toolchain or product behavior, which Rygor seeds but does not own.
- Adopter-owned existing content, never rendered or made drift-fatal.

`.rygor/project.toml` is adopter-controlled desired state and is not a managed render. Rygor may create it
during `new` or `adopt`, and an explicit upgrade transaction may update its engine coordinate and source,
but ordinary edits remain reviewable desired changes. `.rygor/state.json` is Rygor-controlled primary
state and is not listed inside its own inventory.

Consumer capabilities own their complete generated artifact. Multiple contributing capabilities do not
own overlapping YAML fragments; the consumer compiles one deterministic workflow and inventory
provenance records every contributor. Direct collisions between independently rendered artifacts are a
catalog error.

Managed drift blocks unrelated render mutation. `restore` repairs the recorded applied render; `apply`
transitions from the applied configuration to the desired configuration. Seed-once and adopter-owned
files are never restored.

Disabling a capability removes its managed artifacts and nothing else. Files it seeded once stay, because
they became adopter-owned the moment they were written, and Rygor has no record of whether the adopter
has since edited them. Re-enabling the capability does not re-seed or overwrite them. Disabling `nix`
therefore leaves `flake.nix` in place; removing it is the adopter's decision to make.

## API Design

### Distribution and invocation

The first packaged Rygor release `R` is a wheel attached to its release or another HTTPS artifact
location, accompanied by its SHA-256 digest. Semantic-release determines `R` when the completed breaking
transition reaches `main`; the initial product is not published to a package registry.

Release identity is one checked handoff. Semantic-release supplies `nextRelease.version` once as `R`
during preparation. Package metadata, the normalized wheel filename version, the frozen
compatibility-corpus `EngineCoordinate.version`, and the expected tag under the configured tag format
(`vR` initially) must all derive from that value. The GitHub publisher attaches the validated wheel,
source distribution, and checksums to that same tag; post-publication verification confirms the tag and
release coordinate. Any disagreement aborts publication. The later self-adoption may persist only the
coordinate verified from that immutable released wheel.

The published wheel is necessarily rebuilt during preparation and is therefore not byte-identical to the
candidate the pre-release matrix validated: preparation stamps `R` into package metadata, so the two
artifacts differ in version metadata and in every filename and digest derived from it. Nothing else may
differ. The release path closes that gap by re-running the installed-wheel boundary suite — resource
index verification, the complete capability matrix, and the public command contracts — against the
rebuilt wheel inside preparation, before the GitHub publisher attaches anything. A repository whose only
evidence is the pre-bump candidate has not validated the artifact it would publish. "The artifact under
test is the artifact eligible for release" is satisfied by this second gate, not by the first one.

An invocation uses a direct wheel reference with a hash fragment:

The examples use `123.0.0` as a deliberately non-normative stand-in for `R`; implementations and
documentation substitute the exact semantic-release coordinate.

```console
uvx \
  --from 'https://example.invalid/releases/v123.0.0/rygor-123.0.0-py3-none-any.whl#sha256=<digest>' \
  rygor status
```

The CLI captures the portable direct source and digest from installer direct-URL metadata where
available. Creation, adoption, and upgrade also accept explicit source metadata. A portable project
cannot persist a local development wheel path as its released engine source; local paths are permitted in
disposable candidate-wheel fixtures.

The direct wheel's metadata must match the declared engine distribution and version. The CLI entry point
may differ from the distribution name and is part of the engine coordinate. `EngineSource.sha256` is the
expected digest established before acquisition; `BuildIdentity.artifact_sha256` is the digest the
installer attested for the bytes it actually fetched, read from PEP 610 direct-URL metadata or supplied
explicitly. The two values identify the same direct wheel and must be equal. A mismatch is an integrity
failure: Rygor must not render resources from the installed distribution or persist it as the applied
engine. Rygor cannot retroactively prevent its own execution — the installer verified the bytes before
handing control to this process — so the guarantee Rygor adds is that a distribution whose acquisition
cannot be tied to the declared digest never becomes recorded project state.

The model separates:

```text
EngineCoordinate(distribution, version, entrypoint)
EngineSource(kind, acquisition fields, integrity fields)
BuildIdentity(artifact_sha256, resource_digest, catalog_digest)
```

The initial decoder accepts only `source.kind = "direct-wheel"`. A future release can add
`source.kind = "registry"`, resolving the same coordinate as an exact package requirement, without
changing commands, capability state, inventory, or lifecycle semantics.

### Commands

The public lifecycle is:

- `rygor new PATH --profile PROFILE ...`
- `rygor plan adopt PATH --profile PROFILE ...`
- `rygor adopt PATH ... --plan DIGEST`
- `rygor capability list`
- `rygor capability show CAPABILITY`
- `rygor plan apply`
- `rygor apply --plan DIGEST`
- `rygor status`
- `rygor validate`
- `rygor plan restore`
- `rygor restore --plan DIGEST`
- `rygor plan upgrade`
- `rygor upgrade --plan DIGEST`
- `rygor recover [PATH]`

Creation and adoption accept both the `[project]` values and capability settings through
schema-validated command input and materialize the complete normalized configuration. Exact flag
encoding may use repeated `CAPABILITY.KEY=VALUE` arguments, dedicated project flags, or a supplied
project configuration, but there is no interactive questionnaire or hidden ambient default.

`adopt` may propose `default_branch` from the observed Git HEAD as the value it writes into desired
configuration, and `name` from the target directory. That is capture-time observation, reported in the
plan and recorded once as an adopter-editable value; it is not the render-time Git read that the data
model prohibits. Rendering afterwards reads only the stored value, so the same configuration renders the
same bytes on a machine whose checkout has a different HEAD.

`new` applies only to a target that does not exist or is empty, so it may compile and execute its bound
plan in one command. Before creating the target or running `git init`, it acquires the deterministic
parent-scoped bootstrap lease and re-observes the target under that lease. It refuses a populated target,
an existing bootstrap transaction, or changed target identity and never acts as adoption implicitly.

`plan adopt` is read-only and requires an explicit collision declaration for every planned *managed*
path that already exists. A seed-once path that already exists needs no decision and is never rewritten,
because seed-once artifacts are created only when absent; the plan reports each one as retained
adopter-owned content so the outcome is still visible. `adopt` repeats the same intent and accepts the
plan digest; it re-observes the target under the lock before writing.

`capability list` and `capability show` inspect the packaged catalog. `show` reports requirements,
provided contracts, consumers, settings, artifacts with their ownership class, contributions, readiness
obligations, external secret names, activation limits, and minimum engine information. Ownership class
is reported because whether an artifact is managed or seed-once decides who may edit it afterwards, and
that is the question an adopter actually has.

`plan apply` compares adopter-controlled desired configuration, Rygor-controlled applied state, and the
observed tree. It reports capability closure, settings changes, artifact operations, ownership effects,
external activation notes, and a plan digest. `apply` executes exactly that bound transition. Like
`restore`, it renders, so it requires the recorded engine build and refuses `ENGINE_BUILD_MISMATCH`
otherwise. Separate `add`, `remove`, and `configure` command families are unnecessary.

`status` performs one stable read-only observation. It does not run either adopter hook or query hosting
state. It reports pending desired state separately from managed drift and cannot infer that an external
secret is configured.

`validate` requires an engine compatible with the repository. It validates configuration, state,
inventory, managed workflow structure, mechanical readiness, and then invokes
`scripts/validate-project`. Hook effects and results belong to the adopter and are not persisted or
rolled back.

`restore` re-renders only the recorded applied configuration with the recorded engine build and repairs
managed drift. It neither adopts pending desired changes nor changes engine identity.

Restore requires the exact recorded build, not merely a compatible one, under the rendering invariant
in *Engine compatibility and upgrade proposal*. The inventory records digests and modes, never content,
so repairing drift means re-rendering, and a newer engine's resources may render different bytes for the
same applied configuration. Restoring from that engine would be an upgrade performed under the name of a
repair. The adopter either acquires the recorded wheel and restores, or runs `plan upgrade` and accepts
the newer rendering explicitly.

`upgrade` is the only operation that changes the applied engine coordinate or source. It targets the
running engine: invoke the newer wheel and `plan upgrade` proposes recording that coordinate, together
with the source metadata that acquired it, captured from direct-URL metadata or supplied explicitly. It
may also run pure schema and capability-setting migrations and re-render managed artifacts. It requires
a previewed plan and is fully journaled.

`recover` examines both the deterministic parent bootstrap location and the canonical Git runtime
location. It classifies the authoritative journal and completes rollback or sealed cleanup, including
bootstrap-to-Git handoff cleanup. `PATH` defaults to the current working tree; it is required when an
interrupted `new` left the target absent. Recovery runs no adopter hook. Each journal records its
writer and minimum recovery engine; an incompatible engine identifies the exact compatible source rather
than attempting recovery.

There is no Copier `reconcile` operation.

### Command outcomes and presentation

The core returns closed typed outcomes covering:

- success or healthy state;
- action required, such as drift, pending desired state, update availability, external activation, or
  recovery;
- invalid request;
- catalog, render, state, or target contract failure;
- recovery blocked;
- internal failure.

Text and JSON presentation derive from the same value. Each diagnostic has a stable identifier, affected
path or capability where applicable, concise explanation, whether mutation occurred, and a concrete next
action. JSON emits exactly one canonical command envelope on standard output.

Exit status 0 means the requested operation or health evaluation succeeded. Exit status 1 means a
user-correctable or action-required state. Exit status 2 means invalid input, contract corruption,
unsupported semantics, unsafe execution, or an internal failure. An older engine's incomplete status is
action-required rather than healthy.

### Engine compatibility and upgrade proposal

Semantic compatibility is directional. A newer engine in packaged major `M` must read every valid
earlier same-major project. An older engine is not required to understand later capabilities, settings,
or render behavior.

The compatibility classifier considers the running coordinate, recorded applied coordinate, project
format, state schema, repository minimum engine, and the running engine's embedded compatibility
metadata:

| Condition | Result |
|---|---|
| Exact applied coordinate | Normal operation |
| Recognized newer same-major engine on older same-major state | Backward-compatible inspection and non-blocking update proposal; `apply` and `restore` excluded |
| `apply` or `restore` requested where the running resource or catalog digest differs from the recorded build | Refuse with `ENGINE_BUILD_MISMATCH`; name the recorded coordinate, source, and digest |
| Running engine below repository minimum | Limited warning inspection; semantic commands refuse with `ENGINE_TOO_OLD` |
| Running engine older than the repository's supported major | Refuse as unsupported downgrade |
| Unrelated or unrecognized coordinate | Refuse with `ENGINE_IDENTITY_MISMATCH` |
| Unsupported schema gap | Refuse and identify a compatible engine or intermediary |
| Recovery journal requiring another engine | Recovery takes precedence; identify the journal-compatible engine |

Running a later minor `M.y` against a repository applied by earlier `M.x` does not silently rewrite
anything. `status` and other safe inspection report `RYGOR_UPDATE_AVAILABLE` with recorded and running
coordinates, schema information, and the exact `plan upgrade` action.

One invariant governs every rendering operation: **`apply` and `restore` require the running build
identity to equal the recorded build identity; `new` and `adopt` establish it; `upgrade` is the only
transition that changes it.** Rendered bytes are a function of the embedded resources and capability
catalog, so a mutation performed by a different build either writes bytes the recorded configuration does
not describe or silently adopts that build's rendering. Both are engine transitions, and an engine
transition is `upgrade`'s job. A running engine whose `resource_digest` or `catalog_digest` differs from
the recorded build therefore refuses `apply` and `restore` with `ENGINE_BUILD_MISMATCH`, naming the
recorded coordinate, source URL, and digest.

The practical consequence is worth stating plainly: once a newer wheel is in use, the repository accepts
no mutation at all until an explicit `upgrade` lands. `RYGOR_UPDATE_AVAILABLE` is non-blocking for
inspection only. This is the cost of making rendered output reproducible from recorded state, and it is
paid deliberately.

Running earlier `M.x` against state whose `minimum_engine` is later `M.y` reports `ENGINE_TOO_OLD`. It may
compare recorded inventory identities with observed paths, but marks the result incomplete and refuses
validation, resolution, rendering, restore, and mutation. It never discards unknown configuration or
state.

Within packaged major `M`:

- New engines read all earlier valid same-major state.
- Schema changes are additive or have a pure, non-lossy migration.
- Stable capability IDs, setting meanings, provided contracts, and diagnostic meanings are not
  reinterpreted.
- The calling conventions of `scripts/validate-project` and `scripts/release-prepare` are frozen. Both
  are seed-once and therefore never re-rendered, so an engine cannot migrate an adopter's existing
  script; changing how a hook is invoked requires `M + 1`.
- New capabilities, settings, backends, contribution kinds with current consumers, and engine source
  variants may be added.
- A repository may raise its minimum engine when persisted behavior cannot be reproduced safely by an
  older minor.
- Major version `M + 1` is required when valid major-`M` configuration cannot be preserved or interpreted.

Engine major `M` scopes semantic compatibility; it does not replace the independently versioned persisted
contracts. The first packaged release starts `project_format` 1 and `state_schema` 1. Those two counters
evolve independently of each other and of the engine major, additively or through pure non-lossy
migration within `M`, while an incompatible persisted-contract change still requires `M + 1` regardless
of either numeric value.

Package version ordering helps present updates but is not the sole compatibility test. Embedded supported
predecessor and schema metadata decides whether a transition is valid. A distribution rename is an
explicit coordinate transition handled by `upgrade`.

### External activation

Capability configuration and external activation are separate. Rygor can prove that a workflow expects
`GEMINI_API_KEY` or `CACHIX_AUTH_TOKEN`; it cannot prove that a host has configured the secret without
adding host credentials and network effects, which are out of scope.

Status and capability inspection report required secret names and setup guidance as unverified external
activation. They never ask for or persist secret values. Generated contributor validation has no secret
access. Secret-bearing review, release, and publish jobs run only in capability-defined trusted event and
permission boundaries, never by checking out and executing untrusted contributor code with secrets.

## Data Model

### Desired configuration

`.rygor/project.toml` is tracked, adopter-controlled desired state:

```toml
project_format = 1
initial_profile = "integrated"

[project]
name = "example"
default_branch = "main"

[engine]
distribution = "rygor"
version = "123.0.0"
entrypoint = "rygor"

[engine.source]
kind = "direct-wheel"
url = "https://example.invalid/releases/v123.0.0/rygor-123.0.0-py3-none-any.whl"
sha256 = "..."

[capabilities.github-ci]

[capabilities.semantic-release]
prepare_hook = false
commit_assets = []
release_assets = []

[capabilities.nix]

[capabilities.cachix-publish]
cache_name = "example"

[capabilities.pr-agent]
ai_backend = "gemini"
model = "gemini/gemini-3.7-flash"
fallback_models = ["gemini/gemini-3.5-flash-lite"]
```

`project_format` versions this file's contract and is the counter its fields are validated against. It
is independent of the state file's `state_schema` and of the packaged engine major; the state file
records a copy so the classifier can tell which format the last sealed transition was written against.

`[engine]` and `[engine.source]` sit in this adopter-controlled file but are Rygor-maintained: `new` and
`adopt` write them and `upgrade` is the only command that changes them. A hand edit to either is refused
as invalid desired configuration rather than accepted as a pending change, because no command could ever
apply it — `upgrade` targets the running engine, not a version declared in a file. Asking for a different
engine means invoking that engine and running `plan upgrade`, which then records it here.

`[project]` holds the small set of non-capability values that managed rendering needs and no capability
owns. `default_branch` is required because the rendered `.releaserc` names the release branch and
`github-ci` names push triggers; reading it from Git at render time would make output depend on ambient
repository state and break reproduction from recorded configuration alone. `name` labels seeded
scaffolding. The table is closed: a value belongs here only when more than one capability needs it or no
capability can own it, and everything else is a capability setting.

`initial_profile` is provenance only. It records how the initial capability set was chosen, is not part
of `applied_config`, and is therefore never a pending change. The explicit tables are authoritative.
Creation writes every effective setting, including defaults, so later releases cannot reinterpret an
omitted value. A newly introduced
setting is materialized by an explicit upgrade migration before it can affect an existing project.

The config permits only fields known to its `project_format`, capability IDs supported by the running
compatible engine, and normalized non-secret values. Invalid desired configuration is reported without
changing the applied state. Desired configuration may be edited while managed files are drifted;
application remains blocked until both contracts are addressed by an appropriate plan.

### Applied state

`.rygor/state.json` is canonical, checksummed Rygor-controlled state:

```json
{
  "format": "rygor.project-state",
  "state_schema": 1,
  "project_format": 1,
  "engine": {
    "coordinate": {
      "distribution": "rygor",
      "version": "123.0.0",
      "entrypoint": "rygor"
    },
    "source": {
      "kind": "direct-wheel",
      "url": "https://example.invalid/releases/v123.0.0/rygor-123.0.0-py3-none-any.whl",
      "sha256": "..."
    },
    "build": {
      "artifact_sha256": "...",
      "resource_digest": "sha256:...",
      "catalog_digest": "sha256:..."
    }
  },
  "compatibility": {
    "minimum_engine": "123.0.0"
  },
  "origin": {
    "kind": "new"
  },
  "applied_config": {
    "project": {
      "name": "example",
      "default_branch": "main"
    },
    "capabilities": {
      "cachix-publish": {
        "cache_name": "example"
      },
      "github-ci": {},
      "nix": {},
      "pr-agent": {
        "ai_backend": "gemini",
        "fallback_models": ["gemini/gemini-3.5-flash-lite"],
        "model": "gemini/gemini-3.7-flash"
      },
      "semantic-release": {
        "commit_assets": [],
        "prepare_hook": false,
        "release_assets": []
      }
    }
  },
  "inventory": {
    ".github/workflows/ci.yml": {
      "digest": "sha256:...",
      "mode": "0644",
      "contributors": ["cachix-publish", "github-ci", "nix", "semantic-release"]
    },
    ".github/workflows/pr-agent.yml": {
      "digest": "sha256:...",
      "mode": "0644",
      "contributors": ["github-ci", "pr-agent"]
    },
    ".releaserc": {
      "digest": "sha256:...",
      "mode": "0644",
      "contributors": ["semantic-release"]
    }
  },
  "checksum": "sha256:..."
}
```

The fields are described here in the order they appear above.

`format` is a string discriminator, not a counter. It exists so a template-era manifest — which also
carried a numeric `schema` field — can never be mistaken for this document. No compatibility or migration
path exists for those manifests. `state_schema` versions this file's own contract, and `project_format`
mirrors the counter from the desired file so the classifier can compare the format the state was written
against with the format of the file now on disk. Both counters evolve independently of each other and of
the packaged engine major.

`engine` records the coordinate, the acquisition source, and the build identity of the engine that
produced this state. It is written by `new`, `adopt`, and `upgrade`, and no other command may change it.
`compatibility` carries only `minimum_engine`; the packaged major is read from
`engine.coordinate.version` rather than stored beside it.

`origin` records how the repository entered management, `new` or `adopt`. It is provenance for
diagnostics and support only: no decision, plan, render, or recovery path branches on it, and adoption's
consequences are carried by the inventory and ownership classes rather than by this field.

`applied_config` mirrors the desired configuration in normalized form — the same `project` table and the
same capability settings, defaults materialized, secrets and adopter prose absent. It is the sole input
to `restore`, so anything omitted here could not be re-rendered, and it is stored normalized so that
restore and drift classification never depend on pending desired edits. Pending desired state is detected
structurally, by normalizing the file on disk and comparing it against this value: an edit is pending
exactly when it would change what Rygor renders, so reformatting, reordering tables, or spelling a
default explicitly is not a pending change.

`inventory` records one entry per managed path: normalized content digest and executable mode, which
together are what drift is measured against, plus the capabilities that contributed to it. Contributor
IDs explain provenance and nothing more — they never divide ownership of a file, which belongs whole to
its rendering consumer. Seed-once and adopter-owned paths do not appear.

`checksum` covers the document. It detects accidental or partial edits; it is not a security signature.

Two absences are deliberate and follow one rule: **a value that can be derived is never stored.** The
packaged major is derived from the coordinate, and there is no digest of `applied_config` because the
document checksum already covers that subtree. A stored copy of either would be a second source of truth
that can disagree with the first after a hand edit or a partial migration, with no principled way to
decide which one is right. The same rule is why nothing in state claims that the desired file on disk is
unmodified — that is observable, so it is observed rather than recorded.

State is primary evidence of the last sealed transition, not a claim about what the working tree
currently contains. Status observes the tree and compares it against the inventory.

### Runtime state

For an established repository, runtime evidence lives under the canonical Git common directory,
namespaced for the worktree as needed:

```text
.git/rygor/
├── lock
├── journal.json
├── backups/
└── transaction-evidence/
```

It is never committed and survives `git clean -fdx`. Target identity, worktree identity, engine recovery
compatibility, operation sequence, raw backup digests, exact modes, and journal phase are durable.

Journal transitions are atomic. The phases distinguish mutating, sealed, restored, and cleanup-complete
states so no recovery phase both rolls back and completes forward. Recovery is idempotent. A torn or
invalid journal is an explicit blocked state, not equivalent to absence.

#### Pre-Git initialization lease and handoff

Before a missing or empty target has a Git common directory, `new` uses this deterministic sibling path:

```text
<resolved-parent>/.rygor-init-<target-locator-sha256>/
├── lease
└── journal.json
```

The target locator is derived from the real path and filesystem identity of the existing parent plus the
validated final target component. The digest keeps the reserved name bounded and makes aliases through a
symlinked parent converge on the same lease. The adapter opens the stable `lease` file without truncation
and atomically acquires the platform's exclusive, non-blocking file lock. Directory existence alone does
not imply a live owner, and a process owns the lease only after that lock succeeds. A contender that
cannot acquire it reports initialization in progress without mutating the target. A process that acquires
it after an earlier owner exited must recover or explicitly clean the recorded transaction before a new
initialization. Process identifiers and elapsed time are diagnostic only and never authorize lock
stealing.

The lease adapter revalidates after acquisition that the locked file is still the file named by the
deterministic path. This closes the unlink-and-recreate race during cleanup; a waiter holding an unlinked
or replaced file releases it and retries before observing or mutating the target. A process crash releases
the platform lock, while the sibling directory and journal remain as durable recovery evidence.

After acquiring the bootstrap lease, `new` re-observes the target and atomically writes and syncs the
journal before any target mutation. The journal records a unique transaction ID, canonical target
locator, target pre-state (`absent` or `empty-directory`), engine and build identity, bound-plan digest,
and phase. A lease directory with no journal means the previous holder stopped before target mutation;
after acquiring the lease, `recover` may remove that empty evidence without changing the target. A
malformed journal or a target that no longer matches an allowed state is blocked for explicit inspection.
Only a valid durable journal permits target creation and `git init`.

Once Git initialization exposes the canonical common directory, `new` performs a gap-free handoff:

1. Keep the bootstrap file lease held and acquire `.git/rygor/lock`.
2. Write and sync the canonical journal with the same transaction ID, bootstrap pre-state, operation
   evidence, and a `bootstrap-handoff` phase.
3. Mark the bootstrap journal as handed off and remove the sibling bootstrap evidence and lease path only
   after the canonical journal is durable, while continuing to hold both locks; release the bootstrap
   file lock last.

Every command targeting the repository checks the deterministic bootstrap location before treating a
missing, empty, or newly initialized target as unmanaged. If bootstrap and canonical evidence coexist,
recovery requires matching transaction IDs and gives the canonical handoff journal authority; any
mismatch is an unknown third state and preserves both. A pre-handoff rollback removes only paths proven
to have been created by that transaction, removes the target directory only when its recorded pre-state
was absent and the resulting directory is empty, and leaves a recorded empty-directory pre-state in
place. After handoff, the normal canonical journal governs rollback or forward cleanup and also removes
matching bootstrap residue. Thus a crash has no phase in which neither lease nor recovery evidence owns
the initialization.

### Plans

Planning is read-only. A plan digest is derived from the complete typed plan and its preconditions rather
than from a mutable receipt file. Applying the digest recomputes and revalidates the intent, then
re-observes under the lock. A command may optionally emit the canonical JSON plan for review, but execution
trusts the re-derived digest and preconditions rather than an editable plan document.

Operations remain closed typed filesystem actions with explicit preconditions and rollback data. Path
validation rejects absolute paths, traversal, reserved internal paths, unsafe symlink traversal,
unsupported node types, target-root substitution, and writes outside the canonical worktree.

## Validation and Testing Strategy

### Unit and contract tests

- Decode and normalize engine coordinates, direct-wheel sources, desired configuration, applied state,
  compatibility floors, capability settings, and command intents.
- Resolve abstract provided contracts, exclusive hosting, required and optional contributions, conflicts,
  and deterministic ordering with table-driven and property-based tests.
- Prove `nix` resolves and renders standalone output without `github-ci`.
- Prove `github-ci` consumes Nix validation, Cachix publication, semantic release, and PR Agent review
  declarations only when selected.
- Reject required contributions with no consumer or multiple consumers.
- Prove no secret value can enter configuration, normalized state, plans, diagnostics, or rendered docs.
- Render `.releaserc` across the `prepare_hook`, `commit_assets`, and `release_assets` combinations,
  including the empty-asset case that omits the git plugin, and prove no adopter command text reaches it.
- Prove `rygor validate` fails when `prepare_hook` is set and the seeded hook is missing or non-executable.
- Prove `apply` and `restore` refuse with `ENGINE_BUILD_MISMATCH` when the running build differs from the
  recorded one, and that `new`, `adopt`, and `upgrade` are unaffected.
- Acquire direct-wheel fixtures with matching and mismatching digests; prove source `sha256` equals
  observed `artifact_sha256` in every accepted build identity and that a mismatch is rejected before
  execution or state mutation.
- Prove all closed unions are exhaustively dispatched and basedpyright detects missing variants.
- Perturb every resource and definition field that affects output and assert the relevant digest changes.

### Built-wheel fixtures

Release validation builds the wheel and source distribution, creates a clean environment, and invokes the
installed console script. It verifies:

- all declared resources are present and match the embedded resource index;
- checkout-relative resource access is impossible;
- new and adopted temporary Git repositories work from the wheel;
- every profile and supported custom capability combination produces expected output;
- local candidate-wheel invocation works without persisting a local source in release-style project
  state;
- a fresh-clone fixture can acquire the exact checksummed released wheel;
- text and JSON CLI contracts are deterministic.

Generated GitHub workflows pass structural policy tests and `actionlint`. Trusted jobs are checked for
event, permissions, checkout, credential, secret, and dependency boundaries. Contributor validation is
proved secretless and read-only.

### Lifecycle and failure tests

- Exercise desired edit, plan, apply, status, restore, upgrade, and recover sequences.
- Run concurrent `new` commands against the same missing and empty target; prove exactly one acquires the
  bootstrap lease and every loser performs no target mutation.
- Interrupt `new` before the first bootstrap journal, after each pre-Git mutation, during `git init`, and
  at every canonical-lock handoff step. Prove the pre-journal case changes no target bytes, later recovery
  restores the distinct absent and empty pre-states, and handoff continues from the authoritative
  canonical journal without an unowned phase.
- Race a waiter with bootstrap cleanup and path recreation; prove lease-file identity revalidation rejects
  an unlinked lock inode before target observation or mutation.
- Exercise bootstrap aliases, malformed or mismatched bootstrap and canonical journals, adopter changes
  during interrupted initialization, and leftover handed-off markers as explicit third-state or
  idempotent-cleanup cases.
- Inject failure and process interruption before and after every journaled operation.
- Prove exact raw bytes and modes are restored, including CRLF and non-UTF-8 adopter pre-state where
  replacement is allowed.
- Exercise stale plans, concurrent mutation, target replacement, symlink substitution, third states,
  invalid journals, and `git clean -fdx` survival.
- Prove pending desired configuration does not affect restore.
- Prove status and recovery never invoke either adopter hook.
- Prove hook failure does not roll back a mechanically valid installation and its effects are not claimed
  by Rygor recovery.

### Compatibility corpus

Each released minor contributes frozen project configuration, state, plan, resource, capability, and
journal fixtures sufficient to prove the next minor's promised compatibility.

- Newer same-major engines inspect every older valid fixture in packaged major `M` and produce either
  normal behavior or an explicit non-lossy upgrade plan.
- An older-engine harness inspecting a newer fixture reports a warning and refuses semantic operations
  whenever `minimum_engine` exceeds the running version.
- Unknown fields and capability data are never rewritten by limited inspection.
- Unsupported major or schema gaps identify the compatible engine or required migration path.
- A migration preserves explicit existing settings and materializes new defaults without reinterpretation.

### Canonical repository validation

Development uses the repository-defined toolchain and canonical test invocation:

```console
uv run ruff format --check
uv run ruff check
uv run basedpyright
uv run pytest -n auto --dist=worksteal
uv build
```

The release gate additionally installs and exercises the built wheel, validates generated workflows, and
runs the candidate-wheel fixture matrix.

## Dogfooding

Rygor uses two-level self-hosting:

```text
released Rygor N  --manages-->  Rygor source repository
candidate wheel N+1 --tests-->  disposable repositories
```

After wheel `R` is built by the existing hand-maintained release path and attached as a checksummed
release asset, that released wheel adopts the Rygor repository using the integrated profile. The committed
project source points to the immutable release artifact, never to `dist/` or an editable checkout.

The adopter-owned `scripts/validate-project` hook in the Rygor repository runs its source-specific Ruff,
basedpyright, canonical pytest, build, clean-wheel installation, resource, and capability-matrix checks.
The managed `github-ci` validation remains generic and invokes the exact released engine, which then calls
that adopter hook.

For a subsequent release:

1. Released engine N manages the repository and delivery foundation.
2. Source validation builds candidate wheel N+1.
3. Candidate N+1 executes against disposable new and adopted repositories.
4. The checksummed candidate is attached to the new release.
5. A follow-up change uses that released artifact to preview and apply the repository engine upgrade.

The generic initial catalog does not include Python package publication. Attaching Rygor's wheel and
checksum is initially a Rygor-specific maintainer workflow at an adopter-owned path. A generic Python
publication capability is not added until a real second consumer justifies it.

Consequently Rygor's own repository adopts as an ordinary adopter, with no `keep-existing` exception and
no managed path it must specialize. Self-hosting proves the release and toolchain artifacts rather than
excusing them: a defect in the rendered `.releaserc` breaks Rygor's own next release.

Dogfooding is evidence in addition to, not a substitute for, the full profile and custom-selection matrix.

## Security and Failure Model

- Direct remote wheel references require HTTPS and SHA-256. The hash is verified before execution and the
  installed metadata must match the declared coordinate.
- Resource and catalog digests detect a corrupt or improperly rebuilt same-coordinate wheel after
  installation. Release assets are expected to be immutable; a missing asset is an availability failure,
  while a replaced asset is an integrity failure.
- Configuration accepts secret references only. Secret values are never logged, serialized, rendered,
  backed up, or placed in diagnostics.
- Untrusted pull requests run no secret-bearing job, use no write permission, persist no checkout
  credential, and attach no privileged environment.
- PR Agent, semantic release, and Cachix jobs receive only their declared secrets and permissions on
  trusted events. A hosting renderer cannot infer permission broadening from arbitrary capability data.
- Capabilities cannot execute arbitrary code inside the Rygor process. The adopter execution boundaries
  are the two explicit hooks: `scripts/validate-project` and `scripts/release-prepare`.
- The two hooks have deliberately different privilege. `scripts/validate-project` runs in the untrusted
  contributor job with no secrets, no write permission, and no persisted credential.
  `scripts/release-prepare` runs only in the trusted release job, on trusted events, with the release
  token and declared secrets in scope. Rygor never invokes the release hook on a `pull_request` event.
  This is not an escalation — the adopter already owns the workflow and could edit it directly — but it
  is adopter code executing with release privilege, and Rygor renders its invocation rather than
  auditing its contents.
- Plans bind target and content identities. Atomic bootstrap and canonical locks prevent accidental
  concurrent Rygor mutation, and double observation prevents ordinary time-of-check/time-of-use
  divergence. Bootstrap leases are never reclaimed solely from a process ID or timeout.
- Rygor does not claim atomic visibility across multiple files. It claims exact rollback before seal or
  verified completion after seal.
- Rygor does not roll back network effects or adopter-hook effects.
- Rygor does not defend against a concurrent malicious local actor with write access to the repository,
  `.git`, process environment, or executable search path.

## Documentation and Repository Transition

Implementation replaces active documentation as one coherent product transition:

- `docs/prd.md` becomes the packaged CLI product contract and release acceptance source. It is written
  before implementation, so it is also reconciled against as-built behavior in the same pass that
  rewrites the rest of the active documentation. A source of truth that was never checked against what
  shipped is not one.
- `README.md` explains direct-wheel invocation, new/adopt workflows, desired configuration, and the
  package-only scope.
- `CONTEXT.md` adopts the domain terms defined here and removes template generation-path terminology.
- `CONTRIBUTING.md` and `AGENTS.md` describe package builds, built-wheel testing, and the canonical
  validation boundary.
- `docs/capabilities.md` describes capability definitions, provided contracts, contributions, consumers,
  settings, profiles, and the initial catalog.
- `docs/delivery-workflow.md` describes desired state, plan/apply, status, restore, upgrade, recovery,
  external activation, and `scripts/release-prepare` with the release-asset settings and the trusted-job
  privilege that hook carries.
- `docs/project-readiness.md` describes package mechanical validation and the adopter-owned
  `scripts/validate-project` hook.
- `docs/github-setup.md` becomes guidance for the `github-ci` capability rather than a universal hosting
  contract.
- `docs/template-updates.md` is removed or replaced by engine-upgrade guidance under an accurately named
  path.
- A new ADR records the package-only CLI and capability compiler, supersedes ADRs 0001 and 0003, and
  affirms the still-applicable functional-core and ownership principles of ADR 0002.

Accepted historical ADR bodies, release notes, and archived specifications remain unchanged. The new ADR
and active context make their current status explicit.

Implementation removes active template and Copier configuration, copied-engine resources, source
baselines, cleanup inventories, generation-path adapters, reconciliation commands, and tests whose only
contract is the retired template lifecycle. Reusable pure core and transaction behavior moves under
`src/rygor`; tests are rewritten around the package boundary rather than mechanically preserved by path.

The repository's build metadata gains a build backend, package discovery, resource inclusion, and a
`rygor` console script. Runtime dependencies stay in the Rygor wheel environment. Product repositories do
not receive those dependencies.

## Trade-offs

### Selected approach: one wheel with built-in capabilities

One wheel and an internal registry provide the smallest trustworthy distribution boundary. Every release
tests one artifact, one capability catalog, one resource index, and one compatibility declaration. It
avoids dependency-resolution, trust, API-version, and recovery problems for external capability code.

The cost is that adding a capability requires a Rygor release. That is acceptable for the initial catalog
and does not prevent a future loader from populating the same definition model after a real third-party
use case establishes its trust and lifecycle requirements.

### Rejected: retain the template and add a package wrapper

This would preserve Copier and snapshot compatibility but retain copied lifecycle source, generation-path
branching, and two competing update mechanisms. With no legacy users, the complexity provides no current
value.

### Rejected: external entry-point capability packages now

Entry points are familiar in Python but would make capability code executable, introduce package and API
compatibility, complicate deterministic resource identity, and require trust and failure-isolation
policy. No current user story requires third-party distribution.

### Rejected: subprocess capability protocol now

A subprocess boundary could isolate languages and crashes, but would require protocol negotiation,
serialization, executable discovery, sandboxing expectations, and cross-process diagnostics. It is much
more expensive than the current built-in catalog.

### Rejected: capability-specific generated YAML fragments

Raw GitHub fragments would make GitLab substitution impossible and create merge/order semantics in the
core. A complete universal CI model would be equally costly and incomplete. The selected narrow typed
contributions cover only current behavior and leave host syntax to a selected consumer.

### Rejected: make Nix depend on GitHub CI

Nix provides standalone repository value and must remain selectable without hosting. Optional
contribution consumption expresses the actual relationship: selected CI becomes more capable in the
presence of Nix.

### Rejected: encode Gemini in the capability ID

`pr-agent-gemini` couples tool identity to one backend and would multiply capability IDs across hosting
and AI combinations. An explicit backend setting preserves one stable capability and supports future
reconfiguration.

### Rejected: publish the first packaged release to a registry

The distribution name and longer-term versioning policy may change. A checksummed direct wheel provides
the needed installability and reproducibility without reserving a registry contract prematurely. Keeping
engine coordinate separate from source makes later registry resolution additive.

### Rejected: artifact digest as the only engine identity

The digest identifies exact bytes but cannot express the future package coordinate or version semantics.
The selected model uses logical coordinate, acquisition source, and build identity separately.

### Rejected: warning-only old-engine mutation

An older engine may not understand a new capability or contribution in a shared workflow. Allowing it to
render could silently erase behavior. Limited read-only inspection warns; semantic commands fail closed
when the repository minimum exceeds the running engine.

### Rejected: except Rygor's own release files from management

The alternative to an extension point was to let Rygor adopt itself with `keep-existing` decisions on
`.releaserc`, `flake.nix`, `flake.lock`, and the release workflow, treating Rygor as the one adopter whose
files the capability cannot render. That reasoning depended on Rygor being exceptional, and it is not.
The template-era `.releaserc` renders a `uv`-specific prepare command and the flake pins `python314`, so
the capability as inherited only fits Python projects; stack neutrality requires changing it regardless,
and once changed it cannot stamp a version or build an artifact for anyone without an adopter boundary.
The exception would have shipped a broken capability to every other adopter while hiding the breakage
from the one repository positioned to notice it.

### Known limitations

- A direct release asset can become unavailable. The checksum prevents substitution but cannot provide
  availability; operators must restore the exact artifact or move through an explicit upgrade.
- GitHub is the only implemented hosting consumer in the first packaged release, even though the architecture is not
  GitHub-specific.
- Gemini is the only implemented PR Agent backend.
- External secret activation and branch protection remain human-administered and unverified.
- The target must have Git, and CI must be able to acquire uv, Python, the exact wheel, and Rygor's runtime
  dependencies.
- Minor-version backward compatibility does not mean an older minor can mutate a repository requiring
  newer behavior.
- Managed artifacts are whole-file owned. Rygor does not merge arbitrary adopter edits inside managed
  files.
- `restore` requires the exact recorded engine build, not merely a compatible one. Repairing drift on a
  machine that has only a newer wheel means acquiring the recorded wheel or upgrading explicitly.
- `artifact_sha256` is attested by the installer that fetched the wheel, not recomputed by Rygor. Rygor
  detects a tampered installed tree through the resource and catalog digests, and detects a disagreeing
  acquisition, but adds no independent check of the original bytes.
- Release preparation runs adopter-authored code in the trusted, secret-bearing job. Rygor renders the
  invocation and the asset lists but neither inspects nor sandboxes what the hook does.
- `flake.nix` and `flake.lock` are seeded once and then unowned, so a stale dev shell is the adopter's to
  fix and `nix flake check` is only as strong as the flake they keep.

These limitations are explicit product boundaries rather than hidden degradation.

## Open Questions

None. The future registry hostname, final distribution name, exact first packaged release coordinate,
and longer-term version presentation are deliberately not frozen in advance. Semantic-release determines
`R`; the approved engine-coordinate and source model record the result and do not block direct-wheel
delivery.

## References

- [uv tool invocation and `--from` sources](https://docs.astral.sh/uv/guides/tools/)
- [Python packaging direct references and archive hashes](https://packaging.python.org/en/latest/specifications/version-specifiers/#direct-references)
- [Python direct URL origin metadata](https://packaging.python.org/en/latest/specifications/direct-url/)
- [PR Agent automations and supported providers](https://github.com/qodo-ai/pr-agent/blob/main/docs/docs/usage-guide/automations_and_usage.md)
- `docs/specs/2026-08-05-deterministic-project-bootstrap/design.md`
- `docs/specs/2026-08-23-adopt-lifecycle-verb/design.md`
- `docs/adr/0001-use-copier-for-template-updates.md`
- `docs/adr/0002-functional-core-domain-ownership.md`
- `docs/adr/0003-adoption-installs-lifecycle-source.md`
