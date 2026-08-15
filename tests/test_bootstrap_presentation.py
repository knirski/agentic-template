"""Deterministic presentation and validation-program tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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


class CommandEnvelopeTests(unittest.TestCase):
    """In-process coverage for the CommandResult envelope builders.

    The CLI end-to-end suite exercises these pure constructors only through
    subprocesses, which pytest-cov cannot see; these tests cover every
    outcome, hook-evidence, next-action, and subject-at variant directly.
    """

    @staticmethod
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

    def test_envelope_renders_every_outcome_class(self) -> None:
        outcomes: list[tuple[CommandOutcome, str]] = [
            (Succeeded(diagnostics=()), "succeeded"),
            (ActionRequired((self._diagnostic(),)), "action_required"),
            (InvalidRequest((self._diagnostic(),)), "invalid_request"),
            (ContractFailure((self._diagnostic(),)), "contract_failure"),
            (RecoveryFailure((self._diagnostic(),)), "recovery_failure"),
            (InternalFailure((self._diagnostic(),)), "internal_failure"),
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
            self.assertIn(f'"outcome_class":"{expected}"', envelope)
        self.assertIn(
            "BOOTSTRAP_INPUT_LIMIT_USAGE",
            render_json(
                CommandResult(
                    command="apply",
                    outcome=InvalidRequest((self._diagnostic(),)),
                    state_document=None,
                    decision_document=None,
                    changes=(),
                    findings=(),
                )
            ),
        )

    def test_inspection_outcome_maps_exit_one_to_family_two(self) -> None:
        result = CommandResult(
            command="status",
            outcome=ActionRequired((self._diagnostic(),)),
            state_document=None,
            decision_document=None,
            changes=(),
            findings=(),
        )
        self.assertIn('"exit_code":2', render_json(result))
        self.assertEqual(render_text(result).splitlines()[0], "action_required")

    def test_envelope_renders_every_hook_evidence_variant(self) -> None:
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
            self.assertIn(kind, envelope)

    def test_envelope_renders_both_finding_subject_shapes(self) -> None:
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
        self.assertIn('"subject_at":"docs/prd.md"', envelope)
        self.assertIn('"subject_at":"repository"', envelope)

    def test_envelope_renders_both_next_action_shapes(self) -> None:
        result = CommandResult(
            command="apply",
            outcome=Succeeded(
                diagnostics=(
                    self._diagnostic(),
                    self._diagnostic(
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
        self.assertIn('"kind":"instruction"', envelope)
        self.assertIn('"kind":"command"', envelope)
        self.assertIn("validate_repository.py", envelope)

    def test_explain_trace_handles_scalar_state_and_decision(self) -> None:
        result = CommandResult(
            command="status",
            outcome=Succeeded(diagnostics=()),
            state_document=42,
            decision_document=None,
            changes=(),
            findings=(),
        )
        self.assertEqual(
            render_text(result, explain=True).splitlines()[-2:],
            ["state: none", "decision: none"],
        )

    def test_color_resolution_matches_terminal_and_environment(self) -> None:
        self.assertTrue(_color_enabled(PresentationOptions(color="always")))
        self.assertFalse(_color_enabled(PresentationOptions(color="never")))
        with (
            patch.object(sys.stdout, "isatty", return_value=True),
            patch.dict(os.environ, {}, clear=True),
        ):
            self.assertTrue(_color_enabled(PresentationOptions(color="auto")))
        with patch.object(sys.stdout, "isatty", return_value=False):
            self.assertFalse(_color_enabled(PresentationOptions(color="auto")))
        with (
            patch.object(sys.stdout, "isatty", return_value=True),
            patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False),
        ):
            self.assertFalse(_color_enabled(PresentationOptions(color="auto")))


class PresentationTests(unittest.TestCase):
    def test_text_and_json_have_the_same_ordered_findings(self) -> None:
        value = {"command": "status", "findings": [{"code": "R", "subject": "x"}]}
        text = render_text(value)
        encoded = render_json(value)
        self.assertIn("R: x", text)
        self.assertIn('"code":"R"', encoded)

    def test_text_presenter_skips_non_dict_finding_items(self) -> None:
        value = {
            "findings": [
                "not-a-dict",
                {"code": "R", "subject": "x"},
            ]
        }
        self.assertEqual(render_text(value), "R: x")

    def test_finding_path_and_render_cover_both_subject_shapes(self) -> None:
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
        self.assertEqual(repository_finding.path, Path("."))
        self.assertEqual(path_finding.path, Path("a"))
        self.assertIn("repository", repository_finding.render())
        self.assertIn("a", path_finding.render())
        self.assertEqual(repository_finding.identity(), ("R", "", "repo", "rule"))
        self.assertEqual(path_finding.identity(), ("R", "a", "a", "rule"))

    def test_finding_constructor_rejects_invalid_contracts(self) -> None:
        with self.assertRaises(TypeError):
            _ = Finding(
                "R",
                42,
                "a",
                "rule",
                "blocking",
                "bad",
                "fix",
            )
        with self.assertRaises(TypeError):
            _ = Finding(
                "R",
                SubjectPath("a"),
                "a",
                "rule",
                "invalid-severity",
                "bad",
                "fix",
            )

    def test_validation_program_stops_at_first_failed_stage(self) -> None:
        program = ValidationProgram(("template", "readiness", "project"))
        state = program.start()
        state = program.advance(state, StagePassed(0))
        self.assertEqual(state.next_stage, "readiness")
        state = program.advance(state, StageFailed(7))
        self.assertIsNone(state.next_stage)
        self.assertEqual(state.exit_code, 7)
        terminal = program.advance(state, StagePassed())
        self.assertEqual(terminal, state)

        malformed = ValidationState("missing", None)
        self.assertIsNone(program.advance(malformed, StagePassed()).next_stage)

    def test_presenters_handle_command_and_scalar_fallbacks(self) -> None:
        self.assertEqual(render_text({"command": "status", "findings": ()}), "status")
        self.assertEqual(render_text("value"), '"value"')

    def test_text_presenter_renders_complete_diagnostics(self) -> None:
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
        self.assertEqual(
            render_text(value),
            "R1: docs/prd.md: fill in the PRD; next: edit the file",
        )

    def test_readiness_constructor_and_gate_variants(self) -> None:
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
        self.assertIn("repository", repository_finding.render())
        self.assertFalse(
            gate_readiness("unknown", baseline, baseline, baseline).allowed
        )

    def test_validation_program_can_finish_without_stages(self) -> None:
        program = ValidationProgram(())
        state = program.start()
        self.assertIsNone(state.next_stage)
        self.assertEqual(program.advance(state, StageFailed(2)), state)


if __name__ == "__main__":
    _ = unittest.main()
