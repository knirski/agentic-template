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
The deterministic state in which required scaffolding has been replaced, repository validation is
wired into CI, and the adopter-owned validation hook completes successfully. It does not certify
that the hook's commands are substantively adequate for the product.
_Avoid_: Product correctness, release approval

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
contract. Copier may exclude it; GitHub repository-template generation retains it.
_Avoid_: Source-only artifact

## Example dialogue

> **Developer:** Does a GitHub-generated project violate the contract because it contains Copier
> smoke tests?
>
> **Domain expert:** No. Those are template-maintenance artifacts. Generation paths can package
> different files as long as both generated projects satisfy the same generated-project contract.
