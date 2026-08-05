# Product Requirements Document

<!-- agentic-template:placeholder:prd -->

This file is authoritative for the Agentic Delivery Template. In a generated project, replace this
entire template-source contract with the product's own content while retaining the section and
requirement structure demonstrated below.

## Problem

Repositories created from the template need a consistent delivery workflow and an explicit
transition from generic scaffolding to a configured product contract. Without deterministic
readiness evidence, intact placeholder content can be mistaken for a releasable project.

## Goals

- Provide a language-neutral workflow for planning, implementation, validation, review, and release.
- Make incomplete generated-project setup deterministic and actionable.
- Preserve clear ownership between template-maintained contracts and adopter-maintained product
  validation.
- Support both GitHub snapshot generation and update-capable Copier generation.

## Non-goals

- Supplying product code or stack-specific validation presets.
- Judging whether product requirements or validation commands are substantively adequate.
- Reimplementing Copier's update and conflict mechanics.
- Automatically configuring external repository settings.

## Users and workflows

- Template adopters create a repository, replace the marked product scaffolding, configure the
  project-validation hook, run repository validation, and configure merge protection.
- Developers and coding agents use the repository's canonical validation command as completion
  evidence.
- Template maintainers validate both supported generation paths before releasing template updates.

## Requirements

### REQ-001: Detect incomplete generated-project setup

An untouched generated project must fail deterministic readiness checks with stable diagnostics and
concrete next actions for its PRD, README, and project-validation hook.

### REQ-002: Provide one generated-project validation command

Generated-project documentation and CI must use one canonical command that checks the template
contract, project readiness, and the adopter-owned project-validation hook in a stable order.

### REQ-003: Gate releases on project validation

The checked-in release workflow must depend on project validation. Documentation must distinguish
that release gate from administrator-configured merge protection.

### REQ-004: Verify generated behavior from the template source

The template source must remain releasable by exercising generated-project failure and success
fixtures instead of bypassing readiness.

### REQ-005: Preserve generation-path ownership

GitHub-generated and Copier-generated projects must share the readiness contract while retaining
their path-specific packaging and update behavior. Copier remains responsible for its update and
conflict semantics.

### REQ-006: Keep template-owned validation portable and least-privileged

Template-owned contract and readiness checks must work without Nix, avoid mutating project files, and
produce reproducible results. The adopter-owned hook may select its own toolchain and create normal
validation artifacts, but CI must execute it on the supported GitHub-hosted runner without secrets,
write-capable permissions, persisted checkout credentials, or a privileged environment.

## Quality attributes

- **Reliability:** Conforming fixtures produce stable results and diagnostic identifiers.
- **Security:** Project validation runs on the supported GitHub-hosted runner without secrets, write
  permissions, persisted checkout credentials, or a privileged environment.
- **Compatibility:** A change that makes a conforming project unready is released as a breaking
  template-contract change with migration notes.
- **Portability:** Template-owned deterministic validation runs with Python 3.11+ and the standard
  library. Adopter-owned commands define their own toolchain requirements.
- **Maintainability:** Template, readiness, project, and aggregate validation keep separate ownership.

## Release criteria

- Repository-defined formatting, linting, tests, and builds pass.
- GitHub-style and Copier-generated fixtures demonstrate initial failure and configured success.
- Copier update coverage rejects silent overwrite of adopter-owned validation.
- Python syntax, workflow contracts, Markdown, and the source-maintainer validation suites
  pass.
- The release graph includes project validation and the final diff contains no secrets or generated
  agent state.

## Open questions

No current product decision is unresolved. Deferred ideas remain recorded in approved feature
designs until promoted through a separate planning workflow.
