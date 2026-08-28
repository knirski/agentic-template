"""Shared fixture helpers for the generation-path end-to-end suites.

The GitHub-snapshot suite (test_github_template_readiness.py) and the Copier
suite (test_copier_bootstrap.py) both build a tracked-source copy, overlay the
seed-once scaffold, write an answer bundle, and drive the bootstrap CLI.  The
helpers live here with public names so neither suite imports the other's
internals; the CLI suite keeps its own synthetic fixtures.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.contributions import render_generation
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.render import (
    LicensingInfo,
    MaintenanceInfo,
    ProfileInfo,
    ProjectInfo,
)
from scripts.bootstrap.result import Err, Ok, Result
from tests.git_config import deterministic_git_environment

PRD = """# Product
## Problem
Problem.
## Goals
Goals.
## Non-goals
No.
## Users and workflows
Users.
## Requirements
### REQ-001: Works
Acceptance body.
## Quality attributes
Reliable.
## Release criteria
Green.
## Open questions
None.
"""
README = """# Product
## Setup
Setup.
## Validation
Run `uv run --python 3.14 scripts/validate_repository.py`.
"""
SUPPLIED_SECURITY = "# Security\n\nReport privately.\n"
SUPPLIED_CONTRIBUTING = "# Contributing\n\nWelcome.\n"
SCAFFOLD_CONTRIBUTING = (
    "# Contributing\n\n"
    "<!-- rygor:placeholder:contributing -->\n\n"
    "## Running tests\n\n"
    "Run the test suite serially with `uv run pytest`. For faster feedback on a multi-core machine,\n"
    "run `uv run pytest -n auto --dist=worksteal` to distribute tests across available workers.\n"
)
SCAFFOLD_SECURITY = "# Security Policy\n\n<!-- rygor:placeholder:security -->\n"
SCAFFOLD_HOOK_TEMPLATE = (
    "#!/bin/sh\n# rygor:unconfigured:validate-project\necho run >> {record}\nexit 0\n"
)

# The finite source-only set declared by .rygor/source-ownership.json
# and removed by an initial GitHub snapshot apply.  Capability workflow files
# are source-maintainer artifacts: they are excluded from generated projects
# and compiled per-profile by apply, so unselected adopters never receive them.
CLEANUP_PATHS = (
    ".github/workflows/copier-smoke.yml",
    ".github/workflows/mutation.yml",
    ".github/workflows/pr-agent-commands.yml",
    ".github/workflows/pr-agent.yml",
    ".github/workflows/semantic-release.yml",
    ".github/workflows/template-ci.yml",
    ".pr_agent.toml",
    ".python-version",
    ".releaserc",
    "docs/specs",
    "flake.lock",
    "flake.nix",
    "pyproject.toml",
    "tests",
    "uv.lock",
)

# The complete v1 capability catalog surface, mirroring the deployed catalog
# order used by the capability-matrix and source-bootstrap suites.
ALL_CAPABILITIES = ("semantic-release", "nix", "cachix-publish", "pr-agent-gemini")
# The canonical Cachix cache name used by rendered fixtures.
CANONICAL_CACHE_NAME = "example"

_PROJECT = ProjectInfo(name="example", default_branch="main")
_LICENSING = LicensingInfo(mode="retain-apache-2.0", content_sha256=None)
_MAINTENANCE = MaintenanceInfo(status="clean", retained_paths=())


def _ok_render[Value, Failure](result: Result[Value, Failure]) -> Value:
    match result:
        case Ok(value):
            return value
        case Err(failure):
            raise AssertionError(f"unexpected render failure: {failure}")


def render_for(
    effective: tuple[str, ...],
    *,
    settings: dict[str, dict[str, str | bool]] | None = None,
) -> dict[str, bytes]:
    """Render the compiled managed outputs for one effective capability set.

    The shared test-side render entry point over the bootstrap render helper;
    it parameterizes only the canonically frozen fixture inputs (example
    project, retain-Apache-2.0, clean maintenance, custom profile) that the
    capability-matrix and per-profile activation suites both need.
    """
    resolved_settings: dict[str, dict[str, str | bool]] = {}
    if "cachix-publish" in effective:
        resolved_settings["cachix-publish"] = {"cache_name": CANONICAL_CACHE_NAME}
    if settings is not None:
        resolved_settings.update(settings)
    managed = _ok_render(
        render_generation(
            generation_path=GenerationPath.GITHUB,
            core=core_definition(),
            definitions=capability_definitions(),
            effective=effective,
            settings=resolved_settings,
            project=_PROJECT,
            licensing=_LICENSING,
            profile=ProfileInfo(
                id="portable" if not effective else "custom", frozen=effective
            ),
            maintenance=_MAINTENANCE,
            slots={},
            blobs=VerifiedBlobStore.empty(),
        )
    )
    return {file.path.value: file.content for file in managed}


def run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=deterministic_git_environment(env),
        text=True,
        capture_output=True,
        check=False,
    )


def assert_ok[ValueT, ErrorT](
    result: Result[ValueT, ErrorT], message: str = ""
) -> ValueT:
    """Return the ``Ok`` value; fail the test with the error otherwise."""

    match result:
        case Ok(value):
            return value
        case Err(error):
            context = f"{message}: " if message else ""
            raise AssertionError(f"{context}expected success, got {error}")


def assert_err[ErrorT, ValueT](
    result: Result[ValueT, ErrorT], message: str = ""
) -> ErrorT:
    """Return the ``Err`` value; fail the test when the result is ``Ok``."""

    match result:
        case Err(error):
            return error
        case Ok(value):
            context = f"{message}: " if message else ""
            raise AssertionError(f"{context}expected a failure, got {value}")


def tracked_files(root: Path) -> list[str]:
    """List source files available in the checkout for a fixture copy."""
    files = [
        entry
        for entry in run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"]
        ).stdout.split("\0")
        if entry and (root / entry).is_file()
    ]
    return sorted(files)


def scaffold_hook(record: Path) -> str:
    """The seed-once placeholder hook, recording executions to ``record``."""
    return SCAFFOLD_HOOK_TEMPLATE.format(record=record)
