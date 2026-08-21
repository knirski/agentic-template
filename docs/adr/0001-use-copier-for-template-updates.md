---
status: accepted
---

# Use Copier for update-capable project generation

The template supports one-time GitHub snapshot generation and update-capable Copier generation. It
uses Copier for projects that need ongoing template updates rather than maintaining a custom updater.
Copier provides version-aware updates, project-change merging, and conflict handling without
requiring this repository to own its own merge and filesystem safety implementation.

Project-readiness validation is separate from Copier ownership. The template ships Python 3.14+
standard-library validators and an adopter-owned `scripts/validate-project` hook; Copier remains
responsible for preserving and reporting conflicts during updates. Copier updates the
fingerprinted generated-lifecycle compiler inputs; bootstrap alone reconciles the resulting
bootstrap-managed output, and only on the Copier-generated project path. It does not rewrite
seed-once adopter output such as product files, licences, or bundled-skill provenance notices.

## Ownership split

Copier owns source lifecycle updates; bootstrap owns derived-output reconciliation. Copier
retains every generated-lifecycle source input and excludes bootstrap-managed output, seed-once
output, source-only snapshot-cleanup targets, and the cleanup-control inventory from generated
projects. The maintenance exclusions are the finite template-maintenance artifact set declared by
`.agentic-template/source-ownership.json`, so a Copier-generated project never receives source
uv metadata (`pyproject.toml`, `uv.lock`, `.python-version`), Nix maintenance inputs
(`flake.nix`, `flake.lock`), maintainer-only workflows, source test suites, or historical specs.
Because a custom `_exclude` list replaces Copier's built-in exclusions, the template re-declares
them alongside: VCS metadata (`.git`), Python bytecode caches, editor and OS litter, and local tool
state never ship into generated projects.
GitHub snapshots initially retain those same paths and remove them only when the snapshot
cleanup contract authorizes deletion.

Seed-once output (README, PRD, SECURITY, `CONTRIBUTING.md`, the hook, and the
legal/provenance files) is adopter-owned: bootstrap installs it once and reconcile never
rewrites it. Copier excludes seed-once output by design; that exclusion takes effect once the
template ships scaffold content at distinct generated-lifecycle blob paths (the recorded T13
follow-up gate), and until then the seed-once files ship in the Copier copy so the generated
project carries its own scaffold, with Copier's merge and conflict handling preserving adopter
edits during updates.

Future adopting projects upgrade the template through `copier update`: Copier delivers
generated-lifecycle source updates, bootstrap reconciles the derived managed output on the
Copier path, and the adopter's seed-once files remain preserved.

Semantic-release Git tags are the template versions, and Copier-generated projects retain Copier's
`.copier-answers.yml` metadata. GitHub-generated projects are one-time snapshots without Copier
update lineage. This accepts Python, Git, and network/tool-installation requirements for
update-capable generation in exchange for a smaller and more maintainable template toolchain.

## Considered options

- A custom Rust updater was rejected because it duplicated mature template-update behavior and
  required maintaining executable distribution, merge, filesystem, and recovery semantics.
- Cruft was rejected because Cookiecutter compatibility and its additional template-variable
  model are not needed for this language-neutral template.

## Consequences

- Users install Copier and its prerequisites when they choose update-capable Copier generation.
- Updates are selected by semantic-release tags and can be pinned with `--vcs-ref`.
- The repository owns the Copier configuration and smoke tests, while Copier owns update mechanics.
  Ownership classes and the imperative-shell boundary are defined in
  [ADR 0002](0002-functional-core-domain-ownership.md).
