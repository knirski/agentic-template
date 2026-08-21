# Bootstrap fragment maintenance

This directory contains source-owned declarative Markdown fragments used by
the bootstrap renderer. Fragment bodies may contain only the documented
`agentic-template:value:*` markers; they must not read the environment, execute
commands, or introduce adopter-owned paths.

To add a compatible capability:

1. Declare its stable ID, dependencies, non-secret settings, artifacts, slots,
   runtime metadata, and document fragments in `scripts/bootstrap/catalog.py`.
2. Add the matching render definitions and verified static bodies in
   `scripts/bootstrap/capability_fragments.py`.
3. Add any capability-specific documentation fragment here and keep its output
   path inside the four managed operational documents.
4. Add matrix, rendering, workflow, readiness, and external-activation fixtures
   before changing the frozen catalog surface.
5. Update `.agentic-template/source-ownership.json` for every new lifecycle
   source file and run the complete template validation suite.

Capability definitions must remain declarative. The resolver, renderer,
transaction interpreter, and CLI must not gain capability-specific branches.
Settings are normalized and non-secret; external credentials are configured in
GitHub, never persisted by bootstrap.
