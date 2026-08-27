"""Pure readiness policy tests."""

from __future__ import annotations

from scripts.bootstrap.readiness import (
    Finding,
    MechanicalReadinessResult,
    Repository,
    SubjectPath,
    compare_blocking_multisets,
    gate_readiness,
    sort_findings,
)


def _finding(subject: str, *, code: str = "R") -> Finding:
    return Finding(
        code=code,
        subject_at=SubjectPath("docs/prd.md"),
        subject=subject,
        rule="heading",
        severity="blocking",
        message="missing",
        next_action="edit the file",
    )


def test_sorting_is_normative_and_repository_is_not_an_empty_path() -> None:
    findings = (
        _finding("z"),
        Finding(
            code="A",
            subject_at=Repository(),
            subject="repository",
            rule="contract",
            severity="informational",
            message="info",
            next_action="inspect",
        ),
        _finding("a"),
    )
    ordered = sort_findings(findings)
    assert ordered[0].code == "A"
    assert ordered[-1].subject == "z"


def test_multiset_detects_repeated_and_worsened_findings() -> None:
    one = _finding("slot")
    baseline = MechanicalReadinessResult(1, (one, one))
    observed = MechanicalReadinessResult(1, (one,))
    assert not compare_blocking_multisets(observed, baseline)
    assert compare_blocking_multisets(baseline, baseline)


def test_gate_preserves_preexisting_findings_for_incremental_operations() -> None:
    one = _finding("slot")
    baseline = MechanicalReadinessResult(1, (one,))
    expected = MechanicalReadinessResult(1, (one,))
    observed = MechanicalReadinessResult(1, (one,))
    assert gate_readiness("add", baseline, expected, observed).allowed
