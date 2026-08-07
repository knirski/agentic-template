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
from scripts.bootstrap.template_contract import (
    ContractRule,
    canonical_rules,
    compare_rules,
    compatibility_corpus,
    contract_findings,
)
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
        terminal = program.advance(state, StagePassed())
        self.assertEqual(terminal, state)

    def test_contract_rules_and_corpus_are_frozen_and_comparable(self) -> None:
        self.assertEqual(len(canonical_rules()), 3)
        self.assertEqual(compatibility_corpus()[0], ("empty-template", False))
        self.assertTrue(compare_rules(canonical_rules(), canonical_rules()).compatible)
        changed = (*canonical_rules(), ContractRule("new", "blocking", "x", "y"))
        self.assertTrue(compare_rules(canonical_rules(), changed).compatible)
        altered = (
            ContractRule("required-files", "informational", "x", "y"),
            *canonical_rules()[1:],
        )
        result = compare_rules(canonical_rules(), altered)
        self.assertFalse(result.compatible)
        self.assertEqual(
            contract_findings(("a",), ("b",), ("c",)),
            (
                "missing required file: a",
                "missing required skill: b",
                "invalid skill frontmatter: c",
            ),
        )

    def test_presenters_handle_command_and_scalar_fallbacks(self) -> None:
        self.assertEqual(render_text({"command": "status", "findings": ()}), "status")
        self.assertEqual(render_text("value"), '"value"')

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
        self.assertTrue(
            gate_readiness("equivalent", baseline, baseline, baseline).allowed
        )
        self.assertTrue(
            gate_readiness("verification", baseline, baseline, baseline).allowed
        )
        self.assertFalse(
            gate_readiness("unknown", baseline, baseline, baseline).allowed
        )

    def test_validation_program_can_finish_without_stages(self) -> None:
        program = ValidationProgram(())
        state = program.start()
        self.assertIsNone(state.next_stage)
        self.assertEqual(program.advance(state, StageFailed(2)), state)


if __name__ == "__main__":
    unittest.main()
