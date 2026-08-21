#!/usr/bin/env python3
"""Validate active CI and release topology for project validation.

The source ``ci.yml`` is the compiled portable baseline: its stable
project-validation job delegates to the adopter-owned reusable workflow, while
delivery-contract remains in managed CI.  The release graph is compiled output
-- pinned by ``tests/test_capability_matrix.py`` -- and the reusable release
workflow fixture is checked here for its eligibility gate.  This script stays
stdlib-only so the flake's bare-python repository-validation lane can run it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/ci.yml"
PROJECT_VALIDATION = ROOT / ".github/workflows/project-validation.yml"
MAINTAINER_WORKFLOW = ROOT / ".github/workflows/template-ci.yml"
RELEASE = ROOT / "scripts/fixtures/workflows/semantic-release.yml"


def fail(message: str) -> None:
    raise AssertionError(message)


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    maintainer = MAINTAINER_WORKFLOW.read_text(encoding="utf-8")
    release = RELEASE.read_text(encoding="utf-8")
    project_job = workflow.split("  project-validation:\n", 1)[-1].split(
        "\n  delivery-contract:\n", 1
    )[0]
    validation_workflow = PROJECT_VALIDATION.read_text(encoding="utf-8")
    if "name: Project validation" not in project_job:
        fail("project-validation must expose the stable Project validation check name")
    if "uses: ./.github/workflows/project-validation.yml" not in project_job:
        fail("managed CI must call the adopter-owned project-validation workflow")
    if "runs-on:" in project_job or "steps:" in project_job or "run:" in project_job:
        fail("managed CI must not inline the project-validation implementation")
    if "on:\n  workflow_call:" not in validation_workflow:
        fail("project-validation workflow must expose workflow_call")
    if "uv run --python 3.14 scripts/validate_repository.py" not in validation_workflow:
        fail("project-validation workflow must invoke the canonical validator")
    if "if: github.repository != 'knirski/agentic-template'" not in validation_workflow:
        fail("template-source project validation must preserve its readiness guard")
    if (
        "enable-cache: ${{ github.repository != 'knirski/agentic-template' }}"
        not in validation_workflow
    ):
        fail("template-source project validation must disable uv caching")
    if (
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
        not in validation_workflow
    ):
        fail("project-validation workflow must check out the repository")
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
    if re.search(r"continue-on-error:\s*true", validation_workflow):
        fail("project validation cannot tolerate failure")
    if re.search(r"^\s+environment:", validation_workflow, re.M):
        fail("project validation cannot attach an environment")
    if re.search(r"secrets\.", validation_workflow):
        fail("project validation cannot receive secrets")
    if "runs-on: ubuntu-latest" not in validation_workflow:
        fail("project validation must use ubuntu-latest")
    if "persist-credentials: false" not in validation_workflow:
        fail("project validation checkout must not persist credentials")
    if re.search(r"^\s+ref:", validation_workflow, re.M):
        fail("project validation must not override checkout ref")
    if re.search(r"permissions:.*write", validation_workflow, re.S):
        fail("project validation must not have write permissions")
    if re.search(r"if:.*always\(\)", validation_workflow):
        fail("project validation must not bypass failed dependencies")
    if "\n  release:" in workflow:
        fail("the portable baseline must not emit a release job")
    if "needs:" in workflow:
        fail("the portable baseline must not gate any job on a release graph")
    if "release-eligibility" not in release:
        fail(
            "the reusable release workflow must retain the branch-tip eligibility check"
        )
    if re.search(r"if:.*always\(\)", release):
        fail("the reusable release workflow must not bypass failed dependencies")
    if "test_project_readiness.py" not in maintainer or (
        "test_repository_validation.py" not in maintainer
    ):
        fail("source-mode readiness fixtures must run in the maintainer workflow")
    if "needs: [python-source, source-fixtures, workflow-lint]" not in maintainer:
        fail("source release must require the maintainer check suite")
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
        raise SystemExit(1) from exc
