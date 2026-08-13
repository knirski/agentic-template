"""Unit tests for the validation scripts' functional cores."""

from __future__ import annotations

import contextlib
import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_project_readiness as readiness
from scripts import validate_repository as repository
from scripts import validate_template as template
from scripts.bootstrap.validation_program import (
    StageFailed,
    StagePassed,
    stage_failed,
)

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

    def test_non_regular_hook_reports_the_regular_file_code(self) -> None:
        findings = readiness.evaluate_hook(
            readiness.HookState(
                path=Path("scripts/validate_project.py"),
                exists=True,
                regular_file=False,
                executable=False,
                text=None,
            )
        )
        self.assertEqual(findings[0].code, "READINESS_HOOK_NOT_REGULAR")
        self.assertEqual(readiness.exit_code(findings), 1)

    def test_unexpected_arguments_report_a_usage_error(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = readiness.main(["unexpected"])

        self.assertEqual(result, 2)
        self.assertIn("READINESS_USAGE_ERROR", output.getvalue())

    def test_repository_core_stops_after_nonzero_stage(self) -> None:
        self.assertTrue(stage_failed(7))
        self.assertFalse(stage_failed(0))
        self.assertTrue(stage_failed(StageFailed(7)))
        self.assertFalse(stage_failed(StagePassed(0)))

    def test_repository_adapter_folds_successful_stages(self) -> None:
        with patch(
            "scripts.validate_repository.subprocess.run",
            side_effect=(
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
                subprocess.CompletedProcess([], 0),
            ),
        ) as run:
            self.assertEqual(repository.main([]), 0)

        self.assertEqual(run.call_count, 3)

    def test_readiness_adapter_presents_findings(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            result = readiness.main([])

        self.assertEqual(result, 1)
        self.assertIn("READINESS_PRD_MARKER", output.getvalue())

    def test_template_adapter_validates_source_contract(self) -> None:
        self.assertEqual(template.main([]), 0)


if __name__ == "__main__":
    _ = unittest.main()
