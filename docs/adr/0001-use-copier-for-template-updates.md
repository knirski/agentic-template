---
status: accepted
---

# Use Copier for template generation and updates

The template uses Copier for project generation and ongoing updates rather than maintaining a
custom updater. Copier provides version-aware template updates, preservation of project changes,
and conflict handling without requiring this repository to own its own merge and filesystem
safety implementation.

Semantic-release Git tags are the template versions, and generated projects retain Copier's
`.copier-answers.yml` metadata. This accepts Python, Git, and network/tool-installation
requirements in exchange for a smaller and more maintainable template toolchain.

## Considered options

- A custom Rust updater was rejected because it duplicated mature template-update behavior and
  required maintaining executable distribution, merge, filesystem, and recovery semantics.
- Cruft was rejected because Cookiecutter compatibility and its additional template-variable
  model are not needed for this language-neutral template.

## Consequences

- Users install Copier and its prerequisites to create or update projects.
- Updates are selected by semantic-release tags and can be pinned with `--vcs-ref`.
- The repository owns the Copier configuration and smoke tests, while Copier owns update mechanics.
