"""Pure readiness values, ordering, multiset comparison, and gating."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Severity = Literal["blocking", "informational"]


@dataclass(frozen=True, slots=True)
class SubjectPath:
    value: str


@dataclass(frozen=True, slots=True)
class Repository:
    """Repository-wide subject; it is deliberately not represented by an empty path."""


type SubjectAt = SubjectPath | Repository


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    subject_at: SubjectAt
    subject: str
    rule: str
    severity: Severity
    message: str
    next_action: object

    def __post_init__(self) -> None:
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] — runtime contract guard
            self.subject_at, (SubjectPath, Repository)
        ):
            raise TypeError("subject_at must be SubjectPath or Repository")
        if self.severity not in ("blocking", "informational"):
            raise TypeError("severity must be blocking or informational")

    @property
    def path(self) -> Path:
        match self.subject_at:
            case SubjectPath():
                return Path(self.subject_at.value)
            case Repository():
                return Path(".")

    def identity(self) -> tuple[str, str, str, str]:
        match self.subject_at:
            case SubjectPath():
                location = self.subject_at.value
            case Repository():
                location = ""
        return (self.code, location, self.subject, self.rule)

    def render(self, _root: Path | None = None) -> str:
        match self.subject_at:
            case SubjectPath():
                location = self.subject_at.value
            case Repository():
                location = "repository"
        return f"{self.code}: {location}: {self.message}; next: {self.next_action}"


@dataclass(frozen=True, slots=True)
class MechanicalReadinessResult:
    schema_version: int
    findings: tuple[Finding, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", sort_findings(self.findings))

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(
            finding for finding in self.findings if finding.severity == "blocking"
        )


def sort_findings(findings: tuple[Finding, ...] | list[Finding]) -> tuple[Finding, ...]:
    return tuple(sorted(findings, key=lambda finding: finding.identity()))


def compare_blocking_multisets(
    observed: MechanicalReadinessResult, expected: MechanicalReadinessResult
) -> bool:
    return Counter(f.identity() for f in observed.blocking) == Counter(
        f.identity() for f in expected.blocking
    )


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reason: str = ""


def gate_readiness(
    operation: str,
    baseline: MechanicalReadinessResult,
    expected: MechanicalReadinessResult,
    observed: MechanicalReadinessResult,
) -> GateResult:
    if operation == "initial":
        allowed = compare_blocking_multisets(observed, expected)
    elif operation in {"add", "restore", "reconcile"}:
        old = Counter(f.identity() for f in baseline.blocking)
        new = Counter(f.identity() for f in observed.blocking)
        allowed = all(count <= old[identity] for identity, count in new.items())
    else:
        return GateResult(False, "unknown operation")
    return GateResult(allowed, "" if allowed else "blocking readiness changed")


def evaluate_readiness(
    findings: tuple[Finding, ...] = (),
) -> MechanicalReadinessResult:
    return MechanicalReadinessResult(1, findings)


def finding_matches_catalog(code: str) -> bool:
    """Return ``True`` if the finding code belongs to the frozen catalog."""
    from scripts.bootstrap.readiness_rules import finding_code_is_known

    return finding_code_is_known(code)
