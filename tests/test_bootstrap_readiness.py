"""Pure readiness policy tests."""

from __future__ import annotations

import unittest

from scripts.bootstrap.readiness import (
    Finding,
    MechanicalReadinessResult,
    Repository,
    SubjectPath,
    compare_blocking_multisets,
    gate_readiness,
    sort_findings,
)


class ReadinessTests(unittest.TestCase):
    def finding(self, subject: str, *, code: str = "R") -> Finding:
        return Finding(
            code=code,
            subject_at=SubjectPath("docs/prd.md"),
            subject=subject,
            rule="heading",
            severity="blocking",
            message="missing",
            next_action="edit the file",
        )

    def test_sorting_is_normative_and_repository_is_not_an_empty_path(self) -> None:
        findings = (
            self.finding("z"),
            Finding(
                code="A",
                subject_at=Repository(),
                subject="repository",
                rule="contract",
                severity="informational",
                message="info",
                next_action="inspect",
            ),
            self.finding("a"),
        )
        ordered = sort_findings(findings)
        self.assertEqual(ordered[0].code, "A")
        self.assertEqual(ordered[-1].subject, "z")

    def test_multiset_detects_repeated_and_worsened_findings(self) -> None:
        one = self.finding("slot")
        baseline = MechanicalReadinessResult(1, (one, one))
        observed = MechanicalReadinessResult(1, (one,))
        self.assertFalse(compare_blocking_multisets(observed, baseline))
        self.assertTrue(compare_blocking_multisets(baseline, baseline))

    def test_gate_preserves_preexisting_findings_for_incremental_operations(
        self,
    ) -> None:
        one = self.finding("slot")
        baseline = MechanicalReadinessResult(1, (one,))
        expected = MechanicalReadinessResult(1, (one,))
        observed = MechanicalReadinessResult(1, (one,))
        self.assertTrue(gate_readiness("add", baseline, expected, observed).allowed)


if __name__ == "__main__":
    _ = unittest.main()
