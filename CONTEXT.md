# Repository Delivery Context

This context distinguishes the maintained template from repositories created from it and keeps the
shared readiness contract separate from path-specific packaging.

## Language

**Template source**:
The maintained `knirski/agentic-template` repository from which projects are created.
_Avoid_: Source project, generated template

**Generated project**:
A project repository created from the template source through a supported generation path.
_Avoid_: Template repository, copy

**Generation path**:
One of the supported mechanisms for creating a generated project: GitHub's repository-template
operation or Copier. A generation path may produce a different packaging topology without changing
the generated-project contract.
_Avoid_: Installation mode, source mode

**GitHub-generated project**:
A generated project created as a one-time repository snapshot through GitHub's repository-template
operation. It has no Copier update lineage.
_Avoid_: Copier project

**Copier-generated project**:
A generated project created by Copier with source and answer metadata that supports versioned
template updates.
_Avoid_: GitHub template copy

**Generated-project contract**:
The readiness behavior, adopter-owned validation hook, CI gate, and onboarding workflow shared by
all generated projects, independent of generation path.
_Avoid_: Identical generated layout, packaging contract

**Product requirements document**:
The authoritative product contract in `docs/prd.md`. In the template source it specifies template
behavior while retaining marked replacement scaffolding; in a generated project the adopter
replaces that scaffolding with the project's own requirements.
_Avoid_: Example PRD, non-authoritative scaffold

**Project readiness**:
The point-in-time canonical-validation outcome in which mechanical readiness has no blocking finding
and the adopter-owned validation hook completes successfully. It is evaluated, not persisted or
inferred by status. It does not certify
that the hook's commands are substantively adequate for the product or that optional integrations
with external prerequisites have been activated.
_Avoid_: Product correctness, release approval

**Mechanical readiness**:
The deterministic pre-hook finding result for required scaffolding, repository wiring, managed
artifacts, and other template/readiness rules. Bootstrap gates on this result; mechanical readiness
alone does not claim that the adopter hook ran or that the project is ready.
_Avoid_: Project readiness, hook result

**Project bootstrap**:
The deterministic initial transition from a recognized generated scaffold to a bootstrap installation
using a validated bootstrap input bundle. It reports project readiness separately; changing the
selected capabilities after installation is not bootstrap.
_Avoid_: Template update, capability reconfiguration, project setup script

**Bootstrap installation**:
A mechanically complete generated project whose declared bootstrap plan was installed and verified.
It may remain unready because declared scaffolding remains or the adopter-owned validation hook failed.
_Avoid_: Project readiness, product correctness

**Bootstrap answer document**:
The JSON input that supplies project bootstrap's mechanical configuration and references to
user-authored product content. It contains neither embedded product prose nor secrets.
_Avoid_: Project manifest, Copier answers, generated product requirements

**Bootstrap input bundle**:
The bootstrap answer document together with the exact bytes of every referenced content file. The
bundle is the complete deterministic input to project bootstrap.
_Avoid_: Bootstrap answer document, project manifest

**Capability**:
An optional, template-defined delivery integration selected in addition to the generated-project
core. A capability may depend on another capability and may require external activation.
_Avoid_: Core contract, stack preset, plugin

**Snapshot profile**:
A named, creation-time shortcut that expands once into an exact capability set. Later changes to the
profile definition do not alter existing generated projects.
_Avoid_: Live profile, capability set

**Project manifest**:
The persisted, machine-readable record of bootstrap schema version, normalized project settings,
snapshot profile provenance, capability additions, generated-lifecycle source baseline, and managed
artifact inventory. It is neither the product contract, current adopter-content state, nor a secret
store. Schema version 1 remains backward-compatible for the lifetime of bootstrap v1.
_Avoid_: Bootstrap answer document, product requirements document, Copier answers

**Managed inventory**:
The manifest's path-level identity of bootstrap-managed artifacts for one recorded source and
capability selection. Seed-once files, cleanup files, and the manifest itself are not members.
_Avoid_: Project tree, seed content record

**Managed drift**:
The state in which a bootstrap-managed artifact's observed normalized identity or executable mode
differs from its recorded managed-inventory entry. It is adopter-visible divergence, not a new template
source or manifest identity.
_Avoid_: Template update, seed-once edit, source drift

**Source baseline**:
The recorded path-level identity of generated-lifecycle source used by a project. It localizes source
changes; only Copier projects may advance it through capability reconciliation.
_Avoid_: Copier lineage, managed inventory, template version

**Source ownership**:
The fingerprinted declaration that partitions retained generated-lifecycle paths from the finite
template-source paths an initial GitHub snapshot may clean up. It authorizes path classes, while the
ephemeral cleanup inventory supplies expected content identities.
_Avoid_: Managed inventory, cleanup inventory

**Capability activation**:
The externally observable state in which a configured capability's external prerequisites, such as
a repository secret, are available. Project bootstrap configures local artifacts but does not
perform or certify activation.
_Avoid_: Capability selection, project readiness

**Capability addition**:
An explicit post-bootstrap transition that adds capabilities and their dependencies to a generated
project without changing its original snapshot-profile provenance. The project manifest records the
explicit added IDs and complete normalized settings first introduced for their new closure. Capability
removal is a separate, deferred operation with stronger ownership requirements.
_Avoid_: Project bootstrap, live-profile update, capability activation

**Capability reconciliation**:
The deterministic recompilation of bootstrap-managed artifacts after Copier updates the bootstrap
engine or capability catalog. It preserves the exact effective capability set and never merges
adopter changes or selects a template version.
_Avoid_: Copier update, project bootstrap, capability addition, capability reconfiguration

**Bootstrap-managed artifact**:
A derived file owned exclusively by project bootstrap and reproducible from the project manifest and
current capability catalog. Direct adopter edits are drift and block reconciliation rather than
being overwritten or merged.
_Avoid_: Adopter-owned file, Copier-managed file, template-maintenance artifact

**Bootstrap transaction**:
A journaled mutation of the exact files and directories declared by a bootstrap plan. Recovery either
restores their exact pre-operation state or finishes cleanup after a durably gated installation; it
does not cover artifacts or external effects created by the adopter-owned validation hook.
_Avoid_: Database transaction, validation-hook sandbox, repository rollback

**Point-in-time hook evidence**:
The result of one adopter-hook attempt made by an uninterrupted command. It is reported but never
persisted, inferred by status, or replayed by recovery.
_Avoid_: Readiness cache, hook state

**Project-validation hook**:
The adopter-owned, directly executable file at `scripts/validate-project` that performs
product-specific validation using any toolchain available in the target environment.
_Avoid_: Project-validation workflow, repository validator, Python validation script

**Project-validation workflow**:
The adopter-owned reusable GitHub Actions workflow called by bootstrap-managed CI through a stable
Project validation gate. Its initial form invokes repository validation, while adopters may extend
its internal jobs without editing managed CI or receiving caller secrets.
_Avoid_: Project-validation hook, bootstrap-managed CI, release gate

**Project licensing decision**:
The adopter's explicit bootstrap choice for the generated project's root licensing policy. It is
separate from the preserved provenance and license obligations of bundled template artifacts.
_Avoid_: Template source license, bundled skill provenance, implicit license inheritance

**Durable adopter documentation**:
Template-maintained operational guidance that remains useful after the generated project's README
and product requirements document become adopter-owned. It explains delivery, updates,
capabilities, and manual repository setup without becoming product scope.
_Avoid_: Template-source documentation, product documentation, generated boilerplate

**Product requirement**:
A uniquely identified, testable product obligation declared in the PRD with its own explanatory
and acceptance context.
_Avoid_: Requirement reference, implementation task

**Requirement reference**:
A use of a product requirement's identifier outside its declaration. Repeated references do not
create or duplicate product requirements.
_Avoid_: Requirement declaration

**Release gate**:
The repository-controlled dependency that prevents the release workflow from running unless project
validation succeeds.
_Avoid_: Merge protection

**Merge gate**:
The GitHub ruleset or branch-protection setting configured by a repository administrator to require
successful project validation before merging.
_Avoid_: Release dependency, automatically configured protection

**Template-maintenance artifact**:
A file used to develop or test the template source that is not required by the generated-project
contract. Copier excludes the finite cleanup-contract set; GitHub repository-template generation
initially retains it, and bootstrap removes only recognized, hash-matching versions.
_Avoid_: Source-only artifact

**Cleanup contract**:
The agreement between the finite template-maintenance ownership declaration, cleanup inventory, and
observed files that authorizes initial snapshot cleanup. Any disagreement authorizes no deletion.
_Avoid_: Managed inventory, recursive cleanup script

**Unrecognized manifest-free target**:
An empty or populated working tree with no project manifest that does not match either generation
path's exact scaffold recognition contract. Bootstrap v1 neither installs into, adopts, nor migrates
this unsupported state.
_Avoid_: Recognized generated scaffold, bootstrapped project

## Example dialogue

> **Developer:** Does a GitHub-generated project violate the contract because it contains Copier
> smoke tests?
>
> **Domain expert:** No. Those are template-maintenance artifacts. Generation paths can package
> different files as long as both generated projects satisfy the same generated-project contract.
>
> **Developer:** The project selected the full snapshot profile and passes project readiness, so is
> Gemini review active?
>
> **Domain expert:** Not necessarily. The project manifest records that the PR Agent capability is
> configured, while capability activation still depends on the external repository secret.
>
> **Developer:** Bootstrap installed an all-scaffold bundle, so is the project ready?
>
> **Domain expert:** No. It is a bootstrap installation, but project readiness still requires replacing
> the declared scaffolding and successfully running the adopter-owned validation hook.
>
> **Developer:** Can a GitHub-generated project reconcile a locally edited bootstrap engine?
>
> **Domain expert:** No. Its source baseline can identify the local change and a verified Git repair,
> but only a Copier-generated project has an update and reconciliation lifecycle.
