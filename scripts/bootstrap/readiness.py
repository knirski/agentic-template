"""Pure readiness values, ordering, multiset comparison, and gating."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["blocking", "informational"]


@dataclass(frozen=True, slots=True)
class SubjectPath:
    value: str


@dataclass(frozen=True, slots=True)
class Repository:
    """Repository-wide subject; it is deliberately not represented by an empty path."""


SubjectAt = SubjectPath | Repository


@dataclass(frozen=True, slots=True, init=False)
class Finding:
    code: str
    subject_at: SubjectAt
    subject: str
    rule: str
    severity: Severity
    message: str
    next_action: object

    def __init__(self, *args: object, **kwargs: object) -> None:
        # Keep the original four-argument adapter contract while exposing the
        # structured seven-field core contract to new callers.
        if len(args) == 4 and not kwargs:
            code, path, message, next_action = args
            subject_at: SubjectAt = (
                Repository() if str(path) == "" else SubjectPath(str(path))
            )
            subject = str(path)
            rule = str(code)
            severity: Severity = "blocking"
        else:
            code = kwargs.pop("code", args[0] if len(args) > 0 else None)
            subject_at = kwargs.pop("subject_at", args[1] if len(args) > 1 else None)
            subject = kwargs.pop("subject", args[2] if len(args) > 2 else None)
            rule = kwargs.pop("rule", args[3] if len(args) > 3 else None)
            severity = kwargs.pop("severity", args[4] if len(args) > 4 else "blocking")
            message = kwargs.pop("message", args[5] if len(args) > 5 else None)
            next_action = kwargs.pop("next_action", args[6] if len(args) > 6 else None)
            if kwargs:
                raise TypeError(f"unexpected Finding fields: {tuple(kwargs)}")
            if isinstance(subject_at, Path):
                subject_at = SubjectPath(subject_at.as_posix())
            if not isinstance(subject_at, (SubjectPath, Repository)):
                raise TypeError("subject_at must be SubjectPath or Repository")
            if severity not in ("blocking", "informational"):
                raise TypeError("severity must be blocking or informational")
        object.__setattr__(self, "code", str(code))
        object.__setattr__(self, "subject_at", subject_at)
        object.__setattr__(self, "subject", str(subject))
        object.__setattr__(self, "rule", str(rule))
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "message", str(message))
        object.__setattr__(self, "next_action", next_action)

    @property
    def path(self) -> Path:
        return (
            Path(self.subject_at.value)
            if isinstance(self.subject_at, SubjectPath)
            else Path(".")
        )

    def identity(self) -> tuple[str, str, str, str]:
        location = (
            self.subject_at.value if isinstance(self.subject_at, SubjectPath) else ""
        )
        return (self.code, location, self.subject, self.rule)

    def render(self, root: Path | None = None) -> str:
        location = (
            self.subject_at.value
            if isinstance(self.subject_at, SubjectPath)
            else "repository"
        )
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
