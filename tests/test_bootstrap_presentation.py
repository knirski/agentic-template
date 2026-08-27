"""Deterministic presentation and validation-program tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.bootstrap.diagnostics import (
    ActionRequired,
    CommandOutcome,
    ContractFailure,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticSeverity,
    HookExited,
    HookLaunchFailed,
    HookSignalled,
    InternalFailure,
    InvalidRequest,
    NoAutomaticAction,
    NotAttempted,
    RecoveryFailure,
    RunCommand,
    Succeeded,
)
from scripts.bootstrap.errors import ProcessError, ProcessErrorKind, SignalNumber
from scripts.bootstrap.presentation import (
    CommandResult,
    PresentationOptions,
    _color_enabled,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    render_json,
    render_text,
)
from scripts.bootstrap.readiness import (
    Finding,
    MechanicalReadinessResult,
    Repository,
    SubjectPath,
    gate_readiness,
)
from scripts.bootstrap.validation_program import (
    StageFailed,
    StagePassed,
    ValidationProgram,
    ValidationState,
)


def _diagnostic(
    code: str = "BOOTSTRAP_INPUT_LIMIT_USAGE",
    next_action: NoAutomaticAction | RunCommand | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        category=DiagnosticCategory.INPUT,
        severity=DiagnosticSeverity.ERROR,
        subject="input",
        summary="Resource limit exceeded",
        details="Observed 3; the configured limit is 2.",
        next_action=next_action or NoAutomaticAction("reduce the input"),
    )


def test_envelope_renders_every_outcome_class() -> None:
    outcomes: list[tuple[CommandOutcome, str]] = [
        (Succeeded(diagnostics=()), "succeeded"),
        (ActionRequired((_diagnostic(),)), "action_required"),
        (InvalidRequest((_diagnostic(),)), "invalid_request"),
        (ContractFailure((_diagnostic(),)), "contract_failure"),
        (RecoveryFailure((_diagnostic(),)), "recovery_failure"),
        (InternalFailure((_diagnostic(),)), "internal_failure"),
    ]
    for outcome, expected in outcomes:
        result = CommandResult(
            command="apply",
            outcome=outcome,
            state_document={"kind": "state"},
            decision_document={"kind": "decision"},
            changes=(),
            findings=(),
        )
        envelope = render_json(result)
        assert f'"outcome_class":"{expected}"' in envelope
    assert (
        "BOOTSTRAP_INPUT_LIMIT_USAGE"
        in render_json(
            CommandResult(
                command="apply",
                outcome=InvalidRequest((_diagnostic(),)),
                state_document=None,
                decision_document=None,
                changes=(),
                findings=(),
            )
        )
    )


def test_inspection_outcome_maps_exit_one_to_family_two() -> None:
    result = CommandResult(
        command="status",
        outcome=ActionRequired((_diagnostic(),)),
        state_document=None,
        decision_document=None,
        changes=(),
        findings=(),
    )
    assert '"exit_code":2' in render_json(result)
    assert render_text(result).splitlines()[0] == "action_required"


def test_envelope_renders_every_hook_evidence_variant() -> None:
    outcomes = [
        Succeeded(hook_evidence=HookExited(status=3)),
        Succeeded(hook_evidence=HookSignalled(signal=SignalNumber(15))),
        Succeeded(
            hook_evidence=HookLaunchFailed(
                ProcessError(ProcessErrorKind.EXECUTABLE_NOT_FOUND)
            )
        ),
        Succeeded(hook_evidence=NotAttempted("not attempted")),
    ]
    expected = ["exited", "signalled", "launch_failed", "not_attempted"]
    for outcome, kind in zip(outcomes, expected, strict=True):
        envelope = render_json(
            CommandResult(
                command="apply",
                outcome=outcome,
                state_document=None,
                decision_document=None,
                changes=(),
                findings=(),
            )
        )
        assert kind in envelope


def test_envelope_renders_both_finding_subject_shapes() -> None:
    findings = (
        Finding(
            "R", SubjectPath("docs/prd.md"), "prd", "rule", "blocking", "bad", "fix"
        ),
        Finding(
            code="R",
            subject_at=Repository(),
            subject="repo",
            rule="rule",
            severity="informational",
            message="info",
            next_action="inspect",
        ),
    )
    result = CommandResult(
        command="status",
        outcome=Succeeded(diagnostics=()),
        state_document=None,
        decision_document=None,
        changes=(),
        findings=findings,
    )
    envelope = render_json(result)
    assert '"subject_at":"docs/prd.md"' in envelope
    assert '"subject_at":"repository"' in envelope


def test_envelope_renders_both_next_action_shapes() -> None:
    result = CommandResult(
        command="apply",
        outcome=Succeeded(
            diagnostics=(
                _diagnostic(),
                _diagnostic(
                    code="BOOTSTRAP_INPUT_LIMIT_RUN",
                    next_action=RunCommand(("scripts/validate_repository.py",)),
                ),
            )
        ),
        state_document=None,
        decision_document=None,
        changes=(),
        findings=(),
    )
    envelope = render_json(result)
    assert '"kind":"instruction"' in envelope
    assert '"kind":"command"' in envelope
    assert "validate_repository.py" in envelope


def test_explain_trace_handles_scalar_state_and_decision() -> None:
    result = CommandResult(
        command="status",
        outcome=Succeeded(diagnostics=()),
        state_document=42,
        decision_document=None,
        changes=(),
        findings=(),
    )
    assert render_text(result, explain=True).splitlines()[-2:] == [
        "state: none",
        "decision: none",
    ]


def test_color_resolution_matches_terminal_and_environment() -> None:
    assert _color_enabled(PresentationOptions(color="always"))
    assert not _color_enabled(PresentationOptions(color="never"))
    with (
        patch.object(sys.stdout, "isatty", return_value=True),
        patch.dict(os.environ, {}, clear=True),
    ):
        assert _color_enabled(PresentationOptions(color="auto"))
    with patch.object(sys.stdout, "isatty", return_value=False):
        assert not _color_enabled(PresentationOptions(color="auto"))
    with (
        patch.object(sys.stdout, "isatty", return_value=True),
        patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False),
    ):
        assert not _color_enabled(PresentationOptions(color="auto"))


def test_text_and_json_have_the_same_ordered_findings() -> None:
    value = {"command": "status", "findings": [{"code": "R", "subject": "x"}]}
    text = render_text(value)
    encoded = render_json(value)
    assert "R: x" in text
    assert '"code":"R"' in encoded


def test_text_presenter_skips_non_dict_finding_items() -> None:
    value = {
        "findings": [
            "not-a-dict",
            {"code": "R", "subject": "x"},
        ]
    }
    assert render_text(value) == "R: x"


def test_finding_path_and_render_cover_both_subject_shapes() -> None:
    repository_finding = Finding(
        code="R",
        subject_at=Repository(),
        subject="repo",
        rule="rule",
        severity="informational",
        message="info",
        next_action="inspect",
    )
    path_finding = Finding(
        "R", SubjectPath("a"), "a", "rule", "blocking", "bad", "fix"
    )
    assert repository_finding.path == Path(".")
    assert path_finding.path == Path("a")
    assert "repository" in repository_finding.render()
    assert "a" in path_finding.render()
    assert repository_finding.identity() == ("R", "", "repo", "rule")
    assert path_finding.identity() == ("R", "a", "a", "rule")


def test_finding_constructor_rejects_invalid_contracts() -> None:
    with pytest.raises(TypeError):
        _ = Finding(
            "R",
            42,  # pyright: ignore[reportArgumentType] — invalid-contract fixture
            "a",
            "rule",
            "blocking",
            "bad",
            "fix",
        )
    with pytest.raises(TypeError):
        _ = Finding(
            "R",
            SubjectPath("a"),
            "a",
            "rule",
            "invalid-severity",  # pyright: ignore[reportArgumentType] — invalid-contract fixture
            "bad",
            "fix",
        )


def test_validation_program_stops_at_first_failed_stage() -> None:
    program = ValidationProgram(("template", "readiness", "project"))
    state = program.start()
    state = program.advance(state, StagePassed(0))
    assert state.next_stage == "readiness"
    state = program.advance(state, StageFailed(7))
    assert state.next_stage is None
    assert state.exit_code == 7
    terminal = program.advance(state, StagePassed())
    assert terminal == state

    malformed = ValidationState("missing", None)
    assert program.advance(malformed, StagePassed()).next_stage is None


def test_presenters_handle_command_and_scalar_fallbacks() -> None:
    assert render_text({"command": "status", "findings": ()}) == "status"
    assert render_text("value") == '"value"'


def test_text_presenter_renders_complete_diagnostics() -> None:
    value = {
        "findings": [
            {
                "code": "R1",
                "subject": "docs/prd.md",
                "message": "fill in the PRD",
                "next_action": "edit the file",
            }
        ]
    }
    assert (
        render_text(value)
        == "R1: docs/prd.md: fill in the PRD; next: edit the file"
    )


def test_readiness_constructor_and_gate_variants() -> None:
    repository_finding = Finding(
        code="R",
        subject_at=Repository(),
        subject="repo",
        rule="rule",
        severity="informational",
        message="info",
        next_action="inspect",
    )
    path_finding = Finding(
        "R", SubjectPath("a"), "a", "rule", "blocking", "bad", "fix"
    )
    baseline = MechanicalReadinessResult(1, (repository_finding, path_finding))
    assert "repository" in repository_finding.render()
    assert not gate_readiness("unknown", baseline, baseline, baseline).allowed


def test_validation_program_can_finish_without_stages() -> None:
    program = ValidationProgram(())
    state = program.start()
    assert state.next_stage is None
    assert program.advance(state, StageFailed(2)) == state
