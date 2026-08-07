#!/usr/bin/env python3
"""Validate active CI and release topology for project validation."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/ci.yml"
RELEASE = ROOT / ".github/workflows/semantic-release.yml"


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    project_job = workflow.split("  project-validation:\n", 1)[-1].split(
        "\n  nix:\n", 1
    )[0]
    release_job = workflow.split("\n  release:\n", 1)[-1]
    if "name: Project validation" not in workflow:
        fail("project-validation must expose the stable Project validation check name")
    if "python3.14 scripts/validate_repository.py" not in workflow:
        fail("generated mode must invoke python3.14 scripts/validate_repository.py")
    if "python3.14 tests/test_project_readiness.py" not in workflow:
        fail("source mode must run readiness fixtures")
    if "AGENTIC_TEMPLATE_SOURCE_REPOSITORY: knirski/agentic-template" not in workflow:
        fail("source identity constant is missing")
    if (
        "pull_request:" not in workflow
        or "workflow_dispatch:" not in workflow
        or "push:" not in workflow
    ):
        fail(
            "validation workflow must support ordinary pull_request, push, and manual events"
        )
    if "pull_request_target" in workflow:
        fail("project validation must not use pull_request_target")
    if re.search(r"continue-on-error:\s*true", project_job):
        fail("project validation cannot tolerate failure")
    if re.search(r"^\s+environment:", project_job, re.M):
        fail("project validation cannot attach an environment")
    if re.search(r"secrets\.", project_job):
        fail("project validation cannot receive secrets")
    if "runs-on: ubuntu-latest" not in project_job:
        fail("project validation must use ubuntu-latest")
    if "persist-credentials: false" not in project_job:
        fail("project validation checkout must not persist credentials")
    if re.search(r"^\s+ref:", project_job, re.M):
        fail("project validation must not override checkout ref")
    if re.search(r"permissions:.*write", project_job, re.S):
        fail("project validation must not have write permissions")
    if (
        "project-validation" not in release
        and "project-validation" not in workflow.split("release:", 1)[-1]
    ):
        # The reusable release workflow is gated by the caller's release needs.
        fail("release graph must depend on project-validation")
    if "needs: [delivery-contract, project-validation, nix]" not in workflow:
        fail("release job must require project-validation")
    if re.search(r"if:.*always\(\)", release_job):
        fail("release job must not bypass failed dependencies")
    print("delivery contract: ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError) as exc:
        print(
            f"DELIVERY_CONTRACT_ERROR: {exc}; next: fix the active workflow contract",
            file=sys.stderr,
        )
        raise SystemExit(1)
