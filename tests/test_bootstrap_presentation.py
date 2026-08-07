"""Deterministic presentation and validation-program tests."""

from __future__ import annotations

import unittest

from scripts.bootstrap.presentation import render_json, render_text
from scripts.bootstrap.validation_program import (
    StageFailed,
    StagePassed,
    ValidationProgram,
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


if __name__ == "__main__":
    unittest.main()
