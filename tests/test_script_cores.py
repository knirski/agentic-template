"""Unit tests for the validation scripts' functional cores."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts import check_project_readiness as readiness
from scripts import validate_repository as repository
from scripts import validate_template as template
from scripts.bootstrap import validation_presentation as presentation
from scripts.bootstrap.errors import ProcessError, ProcessErrorKind
from scripts.bootstrap.readiness import Finding, SubjectPath
from scripts.bootstrap.validation_program import (
    STREAM_PREFIX_LIMIT,
    CapturedStream,
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


def test_readiness_core_evaluates_text_without_filesystem_access() -> None:
    path = Path("docs/prd.md")
    findings = readiness.evaluate_prd(VALID_PRD, path)
    assert findings == ()

    findings = readiness.evaluate_prd(VALID_PRD.replace("## Goals", "## Wrong"), path)
    assert findings[0].code == "READINESS_PRD_HEADING_MISSING"
    assert readiness.exit_code(findings) == 1


def test_readme_core_preserves_boilerplate_diagnostics() -> None:
    findings = readiness.evaluate_readme(
        """# Rygor

A language-neutral GitHub repository template for planning.
""",
        Path("README.md"),
    )
    assert (
        tuple(finding.code for finding in findings).count(
            "READINESS_README_BOILERPLATE"
        )
        == 1
    )


def test_readiness_aggregator_preserves_stage_order() -> None:
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
    assert findings[0].code == "READINESS_README_COMMAND"


def test_non_regular_hook_reports_the_regular_file_code() -> None:
    findings = readiness.evaluate_hook(
        readiness.HookState(
            path=Path("scripts/validate-project"),
            exists=True,
            regular_file=False,
            executable=False,
            text=None,
        )
    )
    assert findings[0].code == "READINESS_HOOK_NOT_REGULAR"
    assert readiness.exit_code(findings) == 1


def test_unexpected_arguments_report_a_usage_error() -> None:
    output = io.StringIO()
    with contextlib.redirect_stderr(output):
        result = readiness.main(["unexpected"])

    assert result == 2
    assert "READINESS_USAGE_ERROR" in output.getvalue()


def test_readiness_json_usage_errors_use_the_machine_envelope() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = readiness.main(["--format", "json", "unexpected"])

    assert result == 2
    assert stderr.getvalue() == ""
    document = cast(dict[str, object], json.loads(stdout.getvalue()))
    assert document["command"] == "check_project_readiness"
    assert document["outcome_class"] == "invalid_request"
    assert document["exit_code"] == 2


def test_template_json_usage_errors_use_the_machine_envelope() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = template.main(["--format", "json", "unexpected"])

    assert result == 2
    assert stderr.getvalue() == ""
    document = cast(dict[str, object], json.loads(stdout.getvalue()))
    assert document["command"] == "validate_template"
    assert document["outcome_class"] == "invalid_request"


def test_validation_presentation_parsing_and_safe_text() -> None:
    assert presentation.parse_options(
        ["--explain", "--quiet", "--format", "text", "--color", "never"]
    ) == presentation.ValidationOptions("text", "never", True, True)
    assert presentation.parse_options(["--format", "json"]) == (
        presentation.ValidationOptions("json", "auto", False, False)
    )
    for argv in (
        ["--format"],
        ["--format", "yaml"],
        ["--color", "rainbow"],
        ["--unknown"],
        ["--format", "json", "--quiet"],
        ["--format", "json", "--color", "always"],
    ):
        assert presentation.parse_options(argv) is None
    assert presentation.requested_json(["--format", "json"])
    assert presentation.requested_json(["--format=json"])
    assert not presentation.requested_json(["--format", "text"])
    assert presentation.safe_text("line\n\x1b\u202e") == "line\\x0a\\x1b\\u202e"


def test_validation_presentation_renders_text_and_json_findings() -> None:
    finding = Finding(
        "READINESS_TEST",
        SubjectPath("README.md"),
        "README.md",
        "rule",
        "blocking",
        "bad",
        "fix it",
    )
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = presentation.render_findings(
            command="check_project_readiness",
            findings=(finding,),
            exit_code=1,
            options=presentation.ValidationOptions(format="json"),
            diagnostic="bad\ninput",
        )
    assert result == 1
    assert '"outcome_class":"validation_failed"' in stdout.getvalue()
    assert "bad" in stdout.getvalue()
    assert "input" in stdout.getvalue()

    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        result = presentation.render_findings(
            command="check_project_readiness",
            findings=(finding,),
            exit_code=2,
            options=presentation.ValidationOptions(explain=True, color="never"),
            diagnostic="internal",
        )
    assert result == 2
    assert "state: check_project_readiness" in stderr.getvalue()
    assert "READINESS_TEST: README.md" in stderr.getvalue()

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = presentation.render_findings(
            command="validate_template",
            findings=(),
            exit_code=2,
            options=presentation.ValidationOptions(format="json"),
            diagnostic="internal",
        )
    assert result == 2
    document = cast(dict[str, object], json.loads(stdout.getvalue()))
    assert document["outcome_class"] == "internal_failure"


def test_template_internal_failures_use_the_machine_outcome_class() -> None:
    stdout = io.StringIO()
    with (
        patch(
            "scripts.validate_template.validate_contract",
            side_effect=RuntimeError("broken contract"),
        ),
        contextlib.redirect_stdout(stdout),
    ):
        result = template.main(["--format", "json"])

    assert result == 2
    document = cast(dict[str, object], json.loads(stdout.getvalue()))
    assert document["outcome_class"] == "internal_failure"
    assert "TEMPLATE_INTERNAL_ERROR" in str(document["diagnostic"])


def test_repository_stage_documents_and_text_presentation() -> None:
    stream = CapturedStream.from_bytes(b"output\x1b\n")
    observations = (
        StagePassed(stdout=stream),
        StageFailed(7, stderr=stream),
        StageSignalled(15),
        StageLaunchFailed(ProcessError(ProcessErrorKind.EXECUTABLE_NOT_FOUND)),
    )
    for observation in observations:
        document = repository._stage_document("stage", observation)  # pyright: ignore[reportPrivateUsage]
        assert "kind" in document
    assert (
        repository._stream_text(  # pyright: ignore[reportPrivateUsage]
            CapturedStream(1, "0" * 64, "!", False)
        )
        == "<invalid captured prefix>"
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        repository._render_text_stage(  # pyright: ignore[reportPrivateUsage]
            "stage",
            StageFailed(3, stdout=stream, stderr=stream),
            presentation.ValidationOptions(explain=True, color="never"),
        )
    assert "==> stage" in stdout.getvalue()
    assert "stage: failed exit=3" in stdout.getvalue()
    assert "stderr:" in stderr.getvalue()

    colored = io.StringIO()
    with (
        patch.dict("os.environ", {}, clear=True),
        contextlib.redirect_stdout(colored),
    ):
        repository._render_text_stage(  # pyright: ignore[reportPrivateUsage]
            "stage",
            StagePassed(),
            presentation.ValidationOptions(color="always"),
        )
    assert "\033[36m" in colored.getvalue()


def test_repository_json_main_serializes_stage_documents() -> None:
    with (
        patch(
            "scripts.validate_repository.run_stage",
            side_effect=(StagePassed(), StagePassed(), StagePassed()),
        ),
        contextlib.redirect_stdout(io.StringIO()) as output,
    ):
        assert repository.main(["--format", "json"]) == 0
    document = cast(dict[str, object], json.loads(output.getvalue()))
    assert document["outcome_class"] == "succeeded"
    assert len(cast(list[object], document["stages"])) == 3


def test_repository_main_presents_invalid_options() -> None:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        result = repository.main(["unexpected"])

    assert result == 2
    assert "REPOSITORY_VALIDATION_USAGE_ERROR" in stderr.getvalue()


def test_repository_core_stops_after_nonzero_stage() -> None:
    assert stage_failed(7)
    assert not stage_failed(0)
    assert stage_failed(StageFailed(7))
    assert not stage_failed(StagePassed(0))


def test_captured_stream_rejects_negative_prefix_limits() -> None:
    try:
        CapturedStream.from_bytes(b"data", prefix_limit=-1)
        raise AssertionError("expected ValueError for negative prefix limit")
    except ValueError:
        pass


def test_repository_adapter_folds_successful_stages() -> None:
    with patch(
        "scripts.validate_repository.run_stage",
        side_effect=(
            StagePassed(),
            StagePassed(),
            StagePassed(),
        ),
    ) as run:
        assert repository.main([]) == 0

    assert run.call_count == 3


def test_repository_stage_capture_is_bounded_and_hashable() -> None:
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

    assert isinstance(observation, StageFailed)
    assert observation.exit_code == 7
    assert observation.stdout is not None
    assert observation.stdout.total_bytes == 1024 * 1024 + 22
    assert (
        len(base64.b64decode(observation.stdout.prefix_base64)) == STREAM_PREFIX_LIMIT
    )
    assert observation.stdout.truncated
    assert observation.stderr is not None
    assert observation.stderr.total_bytes == 4


def test_repository_stage_success_and_outcome_classification() -> None:
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "success-stage.py"
        _ = script.write_text("raise SystemExit(0)\n", encoding="utf-8")
        observation = repository.run_stage([sys.executable, str(script)])

    assert isinstance(observation, StagePassed)
    assert (
        repository._outcome_class(  # pyright: ignore[reportPrivateUsage]
            2,
            [
                StageLaunchFailed(ProcessError(ProcessErrorKind.EXECUTABLE_NOT_FOUND)),
            ],
        )
        == "internal_failure"
    )
    assert (
        repository._outcome_class(  # pyright: ignore[reportPrivateUsage]
            2, [StageFailed(2)]
        )
        == "validation_failed"
    )


def test_repository_stage_capture_distinguishes_signal_and_launch_failure() -> None:
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "signal-stage.py"
        _ = script.write_text(
            "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n",
            encoding="utf-8",
        )
        signalled = repository.run_stage([sys.executable, str(script)])
    assert isinstance(signalled, StageSignalled)
    assert stage_exit_code(signalled) == 143

    launched = repository.run_stage(["/no/such/validation-stage"])
    assert isinstance(launched, StageLaunchFailed)
    assert stage_exit_code(launched) == 2
    assert launched.error.kind.value == "executable_not_found"


def test_readiness_adapter_presents_findings() -> None:
    output = io.StringIO()
    with contextlib.redirect_stderr(output):
        result = readiness.main([])

    assert result == 1
    assert "READINESS_PRD_MARKER" in output.getvalue()


def test_template_adapter_validates_source_contract() -> None:
    assert template.main([]) == 0
