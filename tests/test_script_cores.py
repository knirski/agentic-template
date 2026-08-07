"""Unit tests for the validation scripts' functional cores."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts import check_project_readiness as readiness
from scripts import validate_repository as repository

VALID_PRD = """# Product

## Problem
The product problem.
## Goals
The product goals.
## Non-goals
The exclusions.
## Users and workflows
The workflow.
## Requirements
### REQ-001: Deliver value
The requirement body.
## Quality attributes
Reliable.
## Release criteria
Green checks.
## Open questions
None.
"""
VALID_README = """# Product

## Setup
Install the product.

## Validation
Run the canonical checks.
"""


class FunctionalCoreTests(unittest.TestCase):
    def test_readiness_core_evaluates_text_without_filesystem_access(self) -> None:
        path = Path("docs/prd.md")
        findings = readiness.evaluate_prd(VALID_PRD, path)
        self.assertEqual(findings, ())

        findings = readiness.evaluate_prd(
            VALID_PRD.replace("## Goals", "## Wrong"), path
        )
        self.assertEqual(findings[0].code, "READINESS_PRD_HEADING_MISSING")
        self.assertEqual(readiness.exit_code(findings), 1)

    def test_readme_core_preserves_boilerplate_diagnostics(self) -> None:
        findings = readiness.evaluate_readme(
            "# Product\n\nA language-neutral GitHub repository template for planning.\n",
            Path("README.md"),
        )
        self.assertEqual(findings[0].code, "READINESS_README_BOILERPLATE")

    def test_readiness_aggregator_preserves_stage_order(self) -> None:
        findings = readiness.evaluate_readiness(
            prd=(VALID_PRD, Path("docs/prd.md")),
            readme=(VALID_README, Path("README.md")),
            hook=readiness.HookState(
                path=Path("scripts/validate_project.py"),
                exists=True,
                regular_file=True,
                executable=True,
                text="project validation",
            ),
        )
        self.assertEqual(findings[0].code, "READINESS_README_COMMAND")

    def test_repository_core_stops_after_nonzero_stage(self) -> None:
        self.assertTrue(repository.stage_failed(7))
        self.assertFalse(repository.stage_failed(0))


if __name__ == "__main__":
    unittest.main()
