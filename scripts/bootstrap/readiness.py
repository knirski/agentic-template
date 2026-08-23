"""Pure readiness values, ordering, multiset comparison, and gating."""

# The standalone checker is the policy adapter for the pure evaluator below;
# its local import is intentional and is kept behind the function boundary.
# pyright: reportImportCycles=false

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
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


def evaluate_project_files(
    files: Mapping[str, tuple[bytes, Literal["text", "binary"], bool]],
) -> MechanicalReadinessResult:
    """Evaluate an observed project with the canonical standalone readiness core.

    The filesystem checker owns the frozen PRD, README, and hook predicates;
    bootstrap supplies the bounded expected bytes and modes produced by its
    plan overlay.  Keeping this boundary byte-based makes both callers use the
    same evaluator without granting readiness code filesystem access.
    """

    from scripts import check_project_readiness as checker

    def text_at(path: str) -> tuple[str, Path] | None:
        entry = files.get(path)
        if entry is None:
            return None
        try:
            return entry[0].decode("utf-8"), Path(path)
        except UnicodeDecodeError as exc:
            initial_findings.append(
                checker._finding(  # pyright: ignore[reportPrivateUsage] shared pure finding constructor
                    "INTERNAL_READINESS_ERROR",
                    Path(path),
                    f"cannot read file ({exc})",
                    "fix the file and rerun validation",
                )
            )
            return None

    initial_findings: list[Finding] = []
    for path in ("docs/prd.md", "README.md", "SECURITY.md", "CONTRIBUTING.md"):
        if path not in files:
            initial_findings.append(
                checker._finding(  # pyright: ignore[reportPrivateUsage] shared pure finding constructor
                    "READINESS_MISSING_FILE",
                    Path(path),
                    "file is missing",
                    "restore the required file",
                )
            )

    hook = files.get("scripts/validate-project")
    hook_text: str | None = None
    if hook is not None:
        try:
            hook_text = hook[0].decode("utf-8")
        except UnicodeDecodeError as exc:
            initial_findings.append(
                checker._finding(  # pyright: ignore[reportPrivateUsage] shared pure finding constructor
                    "INTERNAL_READINESS_ERROR",
                    Path("scripts/validate-project"),
                    f"cannot read file ({exc})",
                    "fix the file and rerun validation",
                )
            )
    hook_state = checker.HookState(
        path=Path("scripts/validate-project"),
        exists=hook is not None,
        regular_file=hook is not None,
        executable=hook is not None and hook[2],
        text=hook_text,
    )
    findings = checker.evaluate_readiness(
        prd=text_at("docs/prd.md"),
        readme=text_at("README.md"),
        security_policy=text_at("SECURITY.md"),
        contributing=text_at("CONTRIBUTING.md"),
        hook=hook_state,
        initial_findings=tuple(initial_findings),
    )
    return MechanicalReadinessResult(1, tuple(findings))


def finding_matches_catalog(code: str) -> bool:
    """Return ``True`` if the finding code belongs to the frozen catalog."""
    from scripts.bootstrap.readiness_rules import finding_code_is_known

    return finding_code_is_known(code)
