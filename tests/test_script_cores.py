"""Unit tests for the validation scripts' functional cores."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts import check_project_readiness as readiness
from scripts import validate_repository as repository
from scripts import validate_template as template
from scripts.bootstrap.validation_program import (
    STREAM_PREFIX_LIMIT,
    StageFailed,
    StageLaunchFailed,
    StagePassed,
    StageSignalled,
    stage_exit_code,
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
            """# Agentic Delivery Template

A language-neutral GitHub repository template for planning.
""",
            Path("README.md"),
        )
        self.assertEqual(
            tuple(finding.code for finding in findings).count(
                "READINESS_README_BOILERPLATE"
            ),
            1,
        )

    def test_readiness_aggregator_preserves_stage_order(self) -> None:
        findings = readiness.evaluate_readiness(
            prd=(VALID_PRD, Path("docs/prd.md")),
            readme=(VALID_README, Path("README.md")),
            hook=readiness.HookState(
                path=Path("scripts/validate-project"),
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
                path=Path("scripts/validate-project"),
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

    def test_readiness_json_usage_errors_use_the_machine_envelope(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = readiness.main(["--format", "json", "unexpected"])

        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue(), "")
        document = cast(dict[str, object], json.loads(stdout.getvalue()))
        self.assertEqual(document["command"], "check_project_readiness")
        self.assertEqual(document["outcome_class"], "invalid_request")
        self.assertEqual(document["exit_code"], 2)

    def test_template_json_usage_errors_use_the_machine_envelope(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = template.main(["--format", "json", "unexpected"])

        self.assertEqual(result, 2)
        self.assertEqual(stderr.getvalue(), "")
        document = cast(dict[str, object], json.loads(stdout.getvalue()))
        self.assertEqual(document["command"], "validate_template")
        self.assertEqual(document["outcome_class"], "invalid_request")

    def test_repository_core_stops_after_nonzero_stage(self) -> None:
        self.assertTrue(stage_failed(7))
        self.assertFalse(stage_failed(0))
        self.assertTrue(stage_failed(StageFailed(7)))
        self.assertFalse(stage_failed(StagePassed(0)))

    def test_repository_adapter_folds_successful_stages(self) -> None:
        with patch(
            "scripts.validate_repository.run_stage",
            side_effect=(
                StagePassed(),
                StagePassed(),
                StagePassed(),
            ),
        ) as run:
            self.assertEqual(repository.main([]), 0)

        self.assertEqual(run.call_count, 3)

    def test_repository_stage_capture_is_bounded_and_hashable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "emit.py"
            _ = script.write_text(
                "\n".join(
                    (
                        "import sys",
                        "sys.stdout.buffer.write(b'A' * (1024 * 1024 + 17) + b'\\x1b[31m')",
                        "sys.stderr.buffer.write(b'err\\n')",
                        "raise SystemExit(7)",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            observation = repository.run_stage([sys.executable, str(script)])

        self.assertIsInstance(observation, StageFailed)
        assert isinstance(observation, StageFailed)
        self.assertEqual(observation.exit_code, 7)
        assert observation.stdout is not None
        self.assertEqual(observation.stdout.total_bytes, 1024 * 1024 + 22)
        self.assertEqual(
            len(base64.b64decode(observation.stdout.prefix_base64)),
            STREAM_PREFIX_LIMIT,
        )
        self.assertTrue(observation.stdout.truncated)
        assert observation.stderr is not None
        self.assertEqual(observation.stderr.total_bytes, 4)

    def test_repository_stage_capture_distinguishes_signal_and_launch_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "signal-stage.py"
            _ = script.write_text(
                "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n",
                encoding="utf-8",
            )
            signalled = repository.run_stage([sys.executable, str(script)])
        self.assertIsInstance(signalled, StageSignalled)
        assert isinstance(signalled, StageSignalled)
        self.assertEqual(stage_exit_code(signalled), 143)

        launched = repository.run_stage(["/no/such/validation-stage"])
        self.assertIsInstance(launched, StageLaunchFailed)
        assert isinstance(launched, StageLaunchFailed)
        self.assertEqual(stage_exit_code(launched), 2)
        self.assertEqual(launched.error.kind.value, "executable_not_found")

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
