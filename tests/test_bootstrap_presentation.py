"""Deterministic presentation and validation-program tests."""

from __future__ import annotations

import unittest

from scripts.bootstrap.presentation import render_json, render_text
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


class PresentationTests(unittest.TestCase):
    def test_text_and_json_have_the_same_ordered_findings(self) -> None:
        value = {"command": "status", "findings": [{"code": "R", "subject": "x"}]}
        text = render_text(value)
        encoded = render_json(value)
        self.assertIn("R: x", text)
        self.assertIn('"code":"R"', encoded)

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
