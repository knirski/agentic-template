#!/usr/bin/env python3
"""Validate active CI and release topology for project validation.

The source ``ci.yml`` is the compiled portable baseline: it carries the stable
project-validation and delivery-contract jobs and never emits capability
artifacts.  The release graph is compiled output -- pinned by
``tests/test_capability_matrix.py`` -- and the reusable release workflow
fixture is checked here for its eligibility gate.  This script stays
stdlib-only so the flake's bare-python repository-validation lane can run it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/ci.yml"
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
    if "name: Project validation" not in workflow:
        fail("project-validation must expose the stable Project validation check name")
    if "uv run --python 3.14 scripts/validate_repository.py" not in project_job:
        fail(
            "generated mode must invoke uv run --python 3.14 scripts/validate_repository.py"
        )
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
    if re.search(r"if:.*always\(\)", project_job):
        fail("project validation must not bypass failed dependencies")
    if "\n  release:" in workflow:
        fail("the portable baseline must not emit a release job")
    if "needs:" in workflow:
        fail("the portable baseline must not gate any job on a release graph")
    if "github.repository != 'knirski/agentic-template'" not in project_job:
        fail("portable validation must exclude the template source repository")
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
