"""Declarative capability fragment bodies and render-boundary definitions.

This module is the compiled-workflow source of truth for the four v1
capabilities: the byte bodies (templates with render markers, contribution
bodies, and reusable-workflow templates) and the render-boundary definitions
that reference them.  It is pure: bodies are constants and every content id is
derived from the body bytes, so interning ``template_bodies()`` into a
``VerifiedBlobStore`` resolves every declared blob reference.

The declarative catalog surface (settings, dependencies, artifact paths, slots)
lives in ``scripts.bootstrap.catalog``; ``tests/test_capability_matrix.py``
pins the two surfaces in agreement and compares the compiled workflow outputs
against the frozen fixtures in ``scripts/fixtures/workflows``.
"""

from __future__ import annotations

from typing import Final

from scripts.bootstrap.blobs import ContentId
from scripts.bootstrap.fragments import (
    CACHIX_GITHUB_SETUP,
    CAPABILITIES,
    DELIVERY_WORKFLOW,
    GITHUB_SETUP,
    PR_AGENT_GITHUB_SETUP,
    TEMPLATE_UPDATES,
)
from scripts.bootstrap.render import (
    ArtifactDefinition,
    CapabilityDefinition,
    ContributionDefinition,
    CoreDefinition,
    DocumentationSource,
    DocumentFragmentDefinition,
    MaintenanceSource,
    ProjectSource,
    ReleaseNeedsSource,
    SettingSource,
    SlotDefinition,
    SubstitutionDefinition,
)

CORE_CI_PATH: Final[str] = ".github/workflows/ci.yml"

# The core compiled CI template: the portable baseline every generated project
# receives.  Capability checks, the Cachix publish job, and the release job are
# contributed through the three slot markers; unselected capabilities leave
# their slots empty and emit no job.
CORE_CI_TEMPLATE: Final[bytes] = b"""\
name: CI

on:
  pull_request:
  push:
    branches:
      - agentic-template:value:default-branch
  workflow_dispatch:

permissions:
  contents: read

jobs:
  project-validation:
    name: Project validation
    runs-on: ubuntu-latest
    env:
      AGENTIC_TEMPLATE_SOURCE_REPOSITORY: knirski/agentic-template
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Set up uv and Python 3.14
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.12.1"
          python-version: "3.14"
          enable-cache: true
      - name: Validate generated-project contract
        if: github.repository != 'knirski/agentic-template'
        run: uv run --python 3.14 scripts/validate_repository.py

  delivery-contract:
    name: Delivery contract
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Set up uv and Python 3.14
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.12.1"
          python-version: "3.14"
          enable-cache: true
      - name: Validate generic delivery files
        run: uv run --python 3.14 scripts/validate_template.py

agentic-template:slot:capability-checks
agentic-template:slot:publish-job
agentic-template:slot:release-job
"""

# --- semantic-release --------------------------------------------------------

RELEASERC_TEMPLATE: Final[bytes] = b"""\
{
  "branches": [agentic-template:value:default-branch],
  "plugins": [
    "@semantic-release/commit-analyzer",
    "@semantic-release/release-notes-generator",
    [
      "@semantic-release/exec",
      {
        "prepareCmd": "uv version ${nextRelease.version} && uv lock"
      }
    ],
    [
      "@semantic-release/git",
      {
        "assets": ["pyproject.toml", "uv.lock"],
        "message": "chore(release): ${nextRelease.version} [skip ci]\\n\\n${nextRelease.notes}"
      }
    ],
    "@semantic-release/github"
  ]
}
"""

# The reusable release workflow, called by the compiled CI release job.
SEMANTIC_RELEASE_WORKFLOW: Final[bytes] = b"""\
name: Semantic Release

on:
  workflow_call:

concurrency:
  group: semantic-release-${{ github.repository }}
  cancel-in-progress: false

jobs:
  release:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          ref: ${{ github.sha }}
          fetch-depth: 0

      - name: Check release eligibility
        id: release-eligibility
        env:
          GH_TOKEN: ${{ github.token }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_SHA: ${{ github.sha }}
        run: python3 scripts/check-release-eligibility.py

      - name: Set up uv and Python 3.14
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          version: "0.12.1"
          python-version: "3.14"
          enable-cache: true

      - name: Publish semantic release
        if: steps.release-eligibility.outputs.eligible == 'true'
        uses: cycjimmy/semantic-release-action@b12c8f6015dc215fe37bc154d4ad456dd3833c90 # v6.0.0
        with:
          semantic_version: 25.0.8
          extra_plugins: |
            @semantic-release/exec
            @semantic-release/git
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""

# The gated release-job contribution to the core CI.  The needs list is
# derived: static core jobs first, then every selected capability check in
# composed order, so release waits on the complete validation graph.
RELEASE_JOB: Final[bytes] = b"""\
  release:
    name: Semantic Release
    # The template source releases through the gated maintainer workflow
    # (template-ci.yml); generated projects keep this portable gate.  The
    # branch check compares the run ref with the repository's default branch
    # instead of interpolating a YAML-encoded scalar into the expression.
    if: >
      github.repository != 'knirski/agentic-template' &&
      github.ref_name == github.event.repository.default_branch &&
      (github.event_name == 'push' || github.event_name == 'workflow_dispatch')
    needs: agentic-template:value:release-needs
    permissions:
      contents: write
      pull-requests: write
      issues: write
    uses: ./.github/workflows/semantic-release.yml"""

# --- nix ---------------------------------------------------------------------

# The reusable Nix check workflow, called by the nix capability's CI
# contribution.  It is absent from the portable baseline.
NIX_WORKFLOW: Final[bytes] = b"""\
name: Nix check

on:
  workflow_call:

jobs:
  nix-check:
    name: Nix flake check
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Install Nix
        uses: cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24 # v31.11.1
      - name: Run flake checks
        run: nix flake check
"""

NIX_CHECK_JOB: Final[bytes] = b"""\
  nix-check:
    name: Nix flake check
    uses: ./.github/workflows/nix.yml"""

# The generated-project flake: development shell, formatter, and portable
# checks.  It never references source-only paths (tests, uv metadata).
FLAKE_NIX_TEMPLATE: Final[bytes] = b"""\
{
  description = agentic-template:value:project-name;

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (system: {
        default = nixpkgs.legacyPackages.${system}.mkShell {
          name = agentic-template:value:project-name;

          packages = with nixpkgs.legacyPackages.${system}; [
            actionlint
            git
            nixfmt
            python314
            uv
          ];
        };
      });

      formatter = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        pkgs.writeShellScriptBin "nixfmt" ''
          if [ "$#" -gt 0 ]; then
            exec ${pkgs.nixfmt}/bin/nixfmt "$@"
          fi
          exec ${pkgs.nixfmt}/bin/nixfmt flake.nix
        ''
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          source = self;
        in
        {
          formatting =
            pkgs.runCommand "project-formatting"
              {
                nativeBuildInputs = [ pkgs.nixfmt ];
              }
              ''
                nixfmt --check ${source}/flake.nix
                touch $out
              '';

          workflow-lint =
            pkgs.runCommand "project-workflow-lint"
              {
                nativeBuildInputs = [ pkgs.actionlint ];
              }
              ''
                actionlint "${source}/.github/workflows/"*.yml
                touch $out
              '';

          repository-validation =
            pkgs.runCommand "project-repository-validation" { nativeBuildInputs = [ pkgs.python314 ]; }
              ''
                cd ${source}
                # The bare-python lane runs the stdlib-only readiness checker;
                # the full canonical validator needs the declared runtime
                # dependencies (pydantic) and runs through uv in CI.
                python3.14 scripts/check_project_readiness.py
                touch $out
              '';
        }
      );
    };
}
"""

# The template's own flake lock: the generated flake declares the same inputs,
# so the lock stays valid for generated projects until an adopter re-locks.
FLAKE_LOCK: Final[bytes] = b"""\
{
  "nodes": {
    "nixpkgs": {
      "locked": {
        "lastModified": 1785692966,
        "narHash": "sha256-vUfIeBEfpbAfZ5zjgIkYk7eHBeVfCYVjLbWnMkseYnk=",
        "owner": "NixOS",
        "repo": "nixpkgs",
        "rev": "643809054d65fdd466a63e3155b8c498cb483c04",
        "type": "github"
      },
      "original": {
        "owner": "NixOS",
        "ref": "nixos-unstable",
        "repo": "nixpkgs",
        "type": "github"
      }
    },
    "root": {
      "inputs": {
        "nixpkgs": "nixpkgs"
      }
    }
  },
  "root": "root",
  "version": 7
}
"""

# --- cachix-publish ----------------------------------------------------------

# The reusable Cachix publish workflow: a fixed trusted preflight decides
# availability, and the privileged publish job starts only when the preflight
# returned available.  An unavailable token skips publishing while Nix
# validation continues uncached; an invalid configured cache fails the publish
# job as an activation error rather than silently disabling Nix validation.
CACHIX_PUBLISH_WORKFLOW: Final[bytes] = b"""\
name: Cachix publish

on:
  workflow_call:

jobs:
  cachix-availability:
    name: Cachix availability
    runs-on: ubuntu-latest
    outputs:
      available: ${{ steps.check.outputs.available }}
      guidance: ${{ steps.check.outputs.guidance }}
    steps:
      - name: Check Cachix auth token
        id: check
        env:
          CACHIX_AUTH_TOKEN: ${{ secrets.CACHIX_AUTH_TOKEN }}
        run: |
          if [ -n "$CACHIX_AUTH_TOKEN" ]; then
            echo "available=true" >> "$GITHUB_OUTPUT"
            echo "guidance=Proceed." >> "$GITHUB_OUTPUT"
          else
            echo "available=false" >> "$GITHUB_OUTPUT"
            echo "guidance=The CACHIX_AUTH_TOKEN secret is unavailable in this run; likely causes include fork pull requests, Dependabot runs, and restricted Actions policy. Cachix publishing is skipped while Nix validation continues uncached. See docs/github-setup.md." >> "$GITHUB_OUTPUT"
          fi

  publish:
    name: Publish to Cachix
    if: needs.cachix-availability.outputs.available == 'true'
    needs: [cachix-availability]
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Install Nix
        uses: cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24 # v31.11.1
      - name: Set up Cachix cache
        uses: cachix/cachix-action@5f2d7c5294214f71b873db4b969586b980625e71 # v17
        with:
          name: agentic-template:value:cache-name
          authToken: ${{ secrets.CACHIX_AUTH_TOKEN }}
      - name: Build and push flake outputs
        env:
          CACHIX_CACHE_NAME: agentic-template:value:cache-name
        run: |
          system=$(nix eval --raw --impure --expr 'builtins.currentSystem')
          nix build ".#devShells.${system}.default"
          cachix push "$CACHIX_CACHE_NAME" "result"
"""

# The Cachix publish job contributed to the core CI: it is additionally gated
# on the default-branch event and on successful Nix validation, and delegates
# availability and pushing to the reusable workflow.
CACHIX_PUBLISH_JOB: Final[bytes] = b"""\
  cachix-publish:
    name: Cachix publish
    if: >
      github.ref_name == github.event.repository.default_branch &&
      (github.event_name == 'push' || github.event_name == 'workflow_dispatch')
    needs: [nix-check]
    uses: ./.github/workflows/cachix-publish.yml
    secrets: inherit"""

# --- pr-agent-gemini ---------------------------------------------------------

# The PR review workflow: a fixed trusted preflight determines Gemini
# availability, and the privileged review job starts only when the preflight
# returned available and the normal event trust conditions pass.  The
# preflight has no checkout, no third-party actions, no repository script,
# no untrusted expression interpolation, no shell tracing, and references the
# secret exactly once; its only outputs are the literal availability boolean
# and constant guidance.
PR_AGENT_WORKFLOW: Final[bytes] = b"""\
# AI-powered PR review using Qodo's PR Agent with a Gemini backend.
# Requires the GEMINI_API_KEY GitHub Actions repository secret.
name: PR Agent

on:
  pull_request:
    types:
      - opened
      - reopened
      - ready_for_review

permissions: {}

concurrency:
  group: pr-agent-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: true

jobs:
  gemini-availability:
    name: Gemini availability
    runs-on: ubuntu-latest
    outputs:
      available: ${{ steps.check.outputs.available }}
      guidance: ${{ steps.check.outputs.guidance }}
    steps:
      - name: Check Gemini API key
        id: check
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          if [ -n "$GEMINI_API_KEY" ]; then
            echo "available=true" >> "$GITHUB_OUTPUT"
            echo "guidance=Proceed." >> "$GITHUB_OUTPUT"
          else
            echo "available=false" >> "$GITHUB_OUTPUT"
            echo "guidance=The GEMINI_API_KEY secret is unavailable in this run; likely causes include fork pull requests, Dependabot runs, and restricted Actions policy. See docs/github-setup.md." >> "$GITHUB_OUTPUT"
          fi

  pr-agent:
    name: Run PR Agent
    if: |
      needs.gemini-availability.outputs.available == 'true' &&
      github.event.pull_request.head.repo.full_name == github.repository &&
      github.event.pull_request.user.type != 'Bot' &&
      (github.event.pull_request.author_association == 'OWNER' ||
       github.event.pull_request.author_association == 'MEMBER' ||
       github.event.pull_request.author_association == 'COLLABORATOR')
    needs: [gemini-availability]
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: read
      issues: write
      pull-requests: write
    steps:
      - name: Run PR Agent
        uses: the-pr-agent/pr-agent@6ad7cf75d95cb3bbb54cf2ad92050eb03804964a # v0.40.0
        env:
          config.model: gemini/gemini-3.6-flash
          config.fallback_models: '["gemini/gemini-3.5-flash-lite"]'
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_AI_STUDIO.GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
"""

# Trusted pull-request comment commands: the same fixed trusted preflight
# gates the privileged comment job.
PR_AGENT_COMMANDS_WORKFLOW: Final[bytes] = b"""\
# Trusted pull-request comment commands for Qodo's PR Agent.
# Requires the GEMINI_API_KEY GitHub Actions repository secret.
name: PR Agent Commands

on:
  issue_comment:
    types:
      - created

permissions: {}

jobs:
  gemini-availability:
    name: Gemini availability
    runs-on: ubuntu-latest
    outputs:
      available: ${{ steps.check.outputs.available }}
      guidance: ${{ steps.check.outputs.guidance }}
    steps:
      - name: Check Gemini API key
        id: check
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          if [ -n "$GEMINI_API_KEY" ]; then
            echo "available=true" >> "$GITHUB_OUTPUT"
            echo "guidance=Proceed." >> "$GITHUB_OUTPUT"
          else
            echo "available=false" >> "$GITHUB_OUTPUT"
            echo "guidance=The GEMINI_API_KEY secret is unavailable in this run; likely causes include fork pull requests, Dependabot runs, and restricted Actions policy. See docs/github-setup.md." >> "$GITHUB_OUTPUT"
          fi

  pr-agent:
    name: Run PR Agent command
    if: |
      needs.gemini-availability.outputs.available == 'true' &&
      github.event.issue.pull_request != null &&
      github.event.comment.user.type != 'Bot' &&
      contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association)
    needs: [gemini-availability]
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: read
      issues: write
      pull-requests: write
    steps:
      - name: Run PR Agent command
        uses: the-pr-agent/pr-agent@6ad7cf75d95cb3bbb54cf2ad92050eb03804964a # v0.40.0
        env:
          config.model: gemini/gemini-3.6-flash
          config.fallback_models: '["gemini/gemini-3.5-flash-lite"]'
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GOOGLE_AI_STUDIO.GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
"""

PR_AGENT_TOML: Final[bytes] = b"""\
[config]
model = "gemini/gemini-3.6-flash"
fallback_models = ["gemini/gemini-3.5-flash-lite"]

[github_action_config]
auto_review = true
auto_describe = true
auto_improve = true
pr_actions = ["opened", "reopened", "ready_for_review"]

[pr_code_suggestions]
commitable_code_suggestions = true
dual_publishing_score_threshold = 5
"""


def template_bodies() -> dict[str, bytes]:
    """Every fragment body by key, for interning into a ``VerifiedBlobStore``."""
    return {
        "core-ci": CORE_CI_TEMPLATE,
        "releaserc": RELEASERC_TEMPLATE,
        "semantic-release-workflow": SEMANTIC_RELEASE_WORKFLOW,
        "release-job": RELEASE_JOB,
        "nix-workflow": NIX_WORKFLOW,
        "nix-check-job": NIX_CHECK_JOB,
        "flake-nix": FLAKE_NIX_TEMPLATE,
        "flake-lock": FLAKE_LOCK,
        "cachix-publish-workflow": CACHIX_PUBLISH_WORKFLOW,
        "cachix-publish-job": CACHIX_PUBLISH_JOB,
        "pr-agent-workflow": PR_AGENT_WORKFLOW,
        "pr-agent-commands-workflow": PR_AGENT_COMMANDS_WORKFLOW,
        "pr-agent-toml": PR_AGENT_TOML,
        "delivery-workflow": DELIVERY_WORKFLOW,
        "template-updates": TEMPLATE_UPDATES,
        "capabilities": CAPABILITIES,
        "github-setup": GITHUB_SETUP,
        "github-setup-cachix": CACHIX_GITHUB_SETUP,
        "github-setup-pr-agent-gemini": PR_AGENT_GITHUB_SETUP,
    }


DEFAULT_BRANCH = SubstitutionDefinition(
    name="default-branch",
    source=ProjectSource(kind="project", key="default_branch"),
)
PROJECT_NAME = SubstitutionDefinition(
    name="project-name",
    source=ProjectSource(kind="project", key="name"),
)
CACHE_NAME = SubstitutionDefinition(
    name="cache-name",
    source=SettingSource(
        kind="setting", capability="cachix-publish", setting="cache_name"
    ),
)
MAINTENANCE_STATUS = SubstitutionDefinition(
    name="maintenance-status",
    source=MaintenanceSource(kind="maintenance", key="status"),
)
RETAINED_PATHS = SubstitutionDefinition(
    name="retained-paths",
    source=MaintenanceSource(kind="maintenance", key="retained_paths"),
)
RELEASE_NEEDS = SubstitutionDefinition(
    name="release-needs",
    source=ReleaseNeedsSource(
        kind="release_needs",
        slot="capability-checks",
        static=("project-validation", "delivery-contract"),
    ),
)

GENERATION_PATH = SubstitutionDefinition(
    name="generation-path",
    source=DocumentationSource(kind="documentation", key="generation_path"),
)
PROFILE_ID = SubstitutionDefinition(
    name="profile-id",
    source=DocumentationSource(kind="documentation", key="profile_id"),
)
PROFILE_FROZEN = SubstitutionDefinition(
    name="profile-frozen",
    source=DocumentationSource(kind="documentation", key="profile_frozen"),
)
ADDITIONS = SubstitutionDefinition(
    name="additions",
    source=DocumentationSource(kind="documentation", key="additions"),
)
EFFECTIVE = SubstitutionDefinition(
    name="effective",
    source=DocumentationSource(kind="documentation", key="effective"),
)
CAPABILITY_SUMMARY = SubstitutionDefinition(
    name="capability-summary",
    source=DocumentationSource(kind="documentation", key="capability_summary"),
)


def _core_document_fragments() -> tuple[DocumentFragmentDefinition, ...]:
    return (
        DocumentFragmentDefinition(
            id="delivery-workflow",
            document="docs/delivery-workflow.md",
            order=0,
            body_blob=ContentId.from_bytes(DELIVERY_WORKFLOW),
        ),
        DocumentFragmentDefinition(
            id="template-updates",
            document="docs/template-updates.md",
            order=0,
            body_blob=ContentId.from_bytes(TEMPLATE_UPDATES),
            substitutions=(GENERATION_PATH, MAINTENANCE_STATUS, RETAINED_PATHS),
        ),
        DocumentFragmentDefinition(
            id="capabilities",
            document="docs/capabilities.md",
            order=0,
            body_blob=ContentId.from_bytes(CAPABILITIES),
            substitutions=(
                PROFILE_ID,
                PROFILE_FROZEN,
                ADDITIONS,
                EFFECTIVE,
                CAPABILITY_SUMMARY,
            ),
        ),
        DocumentFragmentDefinition(
            id="github-setup",
            document="docs/github-setup.md",
            order=0,
            body_blob=ContentId.from_bytes(GITHUB_SETUP),
        ),
    )


def core_definition() -> CoreDefinition:
    """The core render definition: the compiled CI artifact and its slots."""
    return CoreDefinition(
        artifacts=(
            ArtifactDefinition(
                id="ci",
                path=CORE_CI_PATH,
                kind="text",
                install_mode=0o644,
                template_blob=ContentId.from_bytes(CORE_CI_TEMPLATE),
                context="yaml",
                substitutions=(DEFAULT_BRANCH,),
            ),
        ),
        slots=(
            SlotDefinition(
                id="capability-checks",
                owner_artifact="ci",
                context="yaml",
                separator="\n",
                allowed_contribution_kind="yaml",
            ),
            SlotDefinition(
                id="publish-job",
                owner_artifact="ci",
                context="yaml",
                separator="\n",
                allowed_contribution_kind="yaml",
            ),
            SlotDefinition(
                id="release-job",
                owner_artifact="ci",
                context="yaml",
                separator="\n",
                allowed_contribution_kind="yaml",
            ),
        ),
        document_fragments=_core_document_fragments(),
    )


def capability_definitions() -> dict[str, CapabilityDefinition]:
    """Render-boundary definitions for the four catalog capabilities."""
    return {
        "semantic-release": CapabilityDefinition(
            id="semantic-release",
            description="Automated semantic releases.",
            artifacts=(
                ArtifactDefinition(
                    id="releaserc",
                    path=".releaserc",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(RELEASERC_TEMPLATE),
                    context="yaml",
                    substitutions=(DEFAULT_BRANCH,),
                ),
                ArtifactDefinition(
                    id="semantic-release-workflow",
                    path=".github/workflows/semantic-release.yml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(SEMANTIC_RELEASE_WORKFLOW),
                ),
            ),
            contributions=(
                ContributionDefinition(
                    id="release",
                    slot="release-job",
                    order=0,
                    kind="yaml",
                    body_blob=ContentId.from_bytes(RELEASE_JOB),
                    substitutions=(DEFAULT_BRANCH, RELEASE_NEEDS),
                ),
            ),
            runtime_dependencies=("python-semantic-release>=9",),
            supported_python=">=3.14",
            invocation="uvx semantic-release",
        ),
        "nix": CapabilityDefinition(
            id="nix",
            description="Nix development and CI tooling.",
            artifacts=(
                ArtifactDefinition(
                    id="flake-nix",
                    path="flake.nix",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(FLAKE_NIX_TEMPLATE),
                    context="yaml",
                    substitutions=(PROJECT_NAME,),
                ),
                ArtifactDefinition(
                    id="flake-lock",
                    path="flake.lock",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(FLAKE_LOCK),
                ),
                ArtifactDefinition(
                    id="nix-workflow",
                    path=".github/workflows/nix.yml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(NIX_WORKFLOW),
                ),
            ),
            contributions=(
                ContributionDefinition(
                    id="nix-check",
                    slot="capability-checks",
                    order=0,
                    kind="yaml",
                    body_blob=ContentId.from_bytes(NIX_CHECK_JOB),
                ),
            ),
        ),
        "cachix-publish": CapabilityDefinition(
            id="cachix-publish",
            description="Publish Nix artifacts through Cachix.",
            dependencies=("nix",),
            artifacts=(
                ArtifactDefinition(
                    id="cachix-publish-workflow",
                    path=".github/workflows/cachix-publish.yml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(CACHIX_PUBLISH_WORKFLOW),
                    context="yaml",
                    substitutions=(CACHE_NAME,),
                ),
            ),
            contributions=(
                ContributionDefinition(
                    id="cachix-publish",
                    slot="publish-job",
                    order=0,
                    kind="yaml",
                    body_blob=ContentId.from_bytes(CACHIX_PUBLISH_JOB),
                    substitutions=(DEFAULT_BRANCH,),
                ),
            ),
            document_fragments=(
                DocumentFragmentDefinition(
                    id="github-setup-cachix",
                    document="docs/github-setup.md",
                    order=10,
                    body_blob=ContentId.from_bytes(CACHIX_GITHUB_SETUP),
                ),
            ),
        ),
        "pr-agent-gemini": CapabilityDefinition(
            id="pr-agent-gemini",
            description="Qodo PR Agent with a Gemini backend.",
            artifacts=(
                ArtifactDefinition(
                    id="pr-agent-toml",
                    path=".pr_agent.toml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(PR_AGENT_TOML),
                ),
                ArtifactDefinition(
                    id="pr-agent-workflow",
                    path=".github/workflows/pr-agent.yml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(PR_AGENT_WORKFLOW),
                ),
                ArtifactDefinition(
                    id="pr-agent-commands-workflow",
                    path=".github/workflows/pr-agent-commands.yml",
                    kind="text",
                    install_mode=0o644,
                    template_blob=ContentId.from_bytes(PR_AGENT_COMMANDS_WORKFLOW),
                ),
            ),
            # No generated-project runtime dependency: the generated workflows
            # run PR Agent through its pinned GitHub action, and the package's
            # exact transitive pins are not installable on Python 3.14.  The
            # local command stays declared through the invocation metadata.
            supported_python=">=3.14",
            invocation="uvx pr-agent",
            document_fragments=(
                DocumentFragmentDefinition(
                    id="github-setup-pr-agent-gemini",
                    document="docs/github-setup.md",
                    order=20,
                    body_blob=ContentId.from_bytes(PR_AGENT_GITHUB_SETUP),
                ),
            ),
        ),
    }
