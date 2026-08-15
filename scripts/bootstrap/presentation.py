"""Deterministic text and canonical JSON presenters for bootstrap outcomes.

``render_json`` and ``render_text`` serialize one ``CommandResult`` (the
CLI envelope) or a plain findings mapping (the shared validator values)
without any nondeterminism: colors style only the outcome line and never
change words or ordering.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Literal, assert_never, cast

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.diagnostics import (
    ActionRequired,
    CommandOutcome,
    ContractFailure,
    Diagnostic,
    HookEvidence,
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
from scripts.bootstrap.readiness import Finding, Repository, SubjectPath

INSPECTION_COMMANDS = frozenset({"status"})

_ENVELOPE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PresentationOptions:
    format: Literal["text", "json"] = "text"
    color: Literal["auto", "always", "never"] = "auto"
    explain: bool = False
    quiet: bool = False


@dataclass(frozen=True, slots=True)
class Change:
    """One deterministic, presentable change or finding line."""

    kind: str
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The complete semantic outcome shared by the text and JSON renderers."""

    command: str
    outcome: CommandOutcome
    state_document: object
    decision_document: object
    changes: tuple[Change, ...]
    findings: tuple[Finding, ...]


def _result(  # pyright: ignore[reportUnusedFunction] — shared result constructor, imported by the cli and machine shells
    command: str,
    outcome: CommandOutcome,
    *,
    state_document: object = None,
    decision_document: object = None,
    changes: tuple[Change, ...] = (),
    findings: tuple[Finding, ...] = (),
) -> CommandResult:
    return CommandResult(
        command=command,
        outcome=outcome,
        state_document=state_document,
        decision_document=decision_document,
        changes=changes,
        findings=findings,
    )


def _family_exit_code(command: str, outcome: CommandOutcome) -> int:
    code = outcome.exit_code
    if command in INSPECTION_COMMANDS and code == 1:
        # Inspection never returns 1: an advisory refusal is a hard failure.
        return 2
    return code


def _outcome_class(outcome: CommandOutcome) -> str:
    match outcome:
        case Succeeded():
            return "succeeded"
        case ActionRequired():
            return "action_required"
        case InvalidRequest():
            return "invalid_request"
        case ContractFailure():
            return "contract_failure"
        case RecoveryFailure():
            return "recovery_failure"
        case InternalFailure():
            return "internal_failure"
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        outcome
    )


def _hook_evidence_document(evidence: HookEvidence) -> object:
    match evidence:
        case NotAttempted(reason=reason):
            return {"kind": "not_attempted", "reason": reason}
        case HookExited(status=status):
            return {"kind": "exited", "status": status}
        case HookSignalled(signal=signal):
            return {"kind": "signalled", "signal": signal.value}
        case HookLaunchFailed(process_error=error):
            return {"kind": "launch_failed", "process_error": error.kind.value}
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        evidence
    )


def _next_action_document(action: NoAutomaticAction | RunCommand) -> object:
    match action:
        case NoAutomaticAction(instruction=instruction):
            return {"kind": "instruction", "instruction": instruction}
        case RunCommand(command=command):
            return {"kind": "command", "command": list(command)}
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        action
    )


def _diagnostic_document(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "category": diagnostic.category.value,
        "severity": diagnostic.severity.value,
        "subject": diagnostic.subject,
        "summary": diagnostic.summary,
        "details": diagnostic.details,
        "next_action": _next_action_document(diagnostic.next_action),
    }


def _finding_document(finding: Finding) -> dict[str, object]:
    match finding.subject_at:
        case SubjectPath():
            subject_at: object = finding.subject_at.value
        case Repository():
            subject_at = "repository"
    return {
        "code": finding.code,
        "subject_at": subject_at,
        "subject": finding.subject,
        "rule": finding.rule,
        "severity": finding.severity,
        "message": finding.message,
        "next_action": str(finding.next_action),
    }


def _outcome_diagnostics(outcome: CommandOutcome) -> tuple[Diagnostic, ...]:
    match outcome:
        case Succeeded(diagnostics=diagnostics):
            return diagnostics
        case ActionRequired(diagnostics=diagnostics):
            return diagnostics
        case InvalidRequest(diagnostics=diagnostics):
            return diagnostics
        case ContractFailure(diagnostics=diagnostics):
            return diagnostics
        case RecoveryFailure(diagnostics=diagnostics):
            return diagnostics
        case InternalFailure(diagnostics=diagnostics):
            return diagnostics
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        outcome
    )


def command_envelope(result: CommandResult) -> dict[str, object]:
    """The one canonical JSON ``CommandEnvelope`` emitted by ``--format json``."""

    outcome = result.outcome
    return {
        "schema_version": _ENVELOPE_SCHEMA_VERSION,
        "command": result.command,
        "outcome_class": _outcome_class(outcome),
        "exit_code": _family_exit_code(result.command, outcome),
        "state": result.state_document,
        "decision": result.decision_document,
        "changes": [
            {"kind": change.kind, "subject": change.subject, "detail": change.detail}
            for change in result.changes
        ],
        "findings": [_finding_document(finding) for finding in result.findings],
        "diagnostics": [
            _diagnostic_document(diagnostic)
            for diagnostic in _outcome_diagnostics(outcome)
        ],
        "hook_evidence": _hook_evidence_document(
            outcome.hook_evidence
            if isinstance(outcome, (Succeeded, ActionRequired))
            else NotAttempted("not attempted")
        ),
    }


def render_json(result: CommandResult | object) -> str:
    """Serialize the canonical envelope (or a plain strict value) as JSON."""

    if isinstance(result, CommandResult):
        return canonical_json(command_envelope(result)).decode("utf-8")
    return canonical_json(result).decode("utf-8")


def _render_next_action(action: NoAutomaticAction | RunCommand) -> str:
    match action:
        case NoAutomaticAction(instruction=instruction):
            return instruction
        case RunCommand(command=command):
            return "run " + " ".join(command)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        action
    )


_OUTCOME_COLORS = {
    "succeeded": "\x1b[32m",  # green
    "action_required": "\x1b[33m",  # yellow
}
_ANSI_RESET = "\x1b[0m"


def _document_kind(document: object) -> str:
    """Extract the closed document constructor kind for the explain trace."""

    if not isinstance(document, dict):
        return "none"
    kind = cast(dict[str, object], document).get("kind")
    return kind if isinstance(kind, str) else "none"


def _render_findings_mapping(value: object) -> str:
    """Render the shared findings mapping, with the scalar JSON fallback."""

    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        raw_findings = mapping.get("findings", ())
        if isinstance(raw_findings, (list, tuple)):
            lines: list[str] = []
            for item in cast(list[object] | tuple[object, ...], raw_findings):
                if not isinstance(item, dict):
                    continue
                entry = cast(dict[str, object], item)
                code = entry.get("code")
                subject = entry.get("subject")
                if "message" in entry and "next_action" in entry:
                    lines.append(
                        f"{code}: {subject}: {entry.get('message')}; next: {entry.get('next_action')}"
                    )
                else:
                    lines.append(f"{code}: {subject}")
            if lines:
                return "\n".join(lines)
        command = mapping.get("command")
        return str(command) if command is not None else ""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def render_text(
    result: CommandResult | object,
    *,
    quiet: bool = False,
    explain: bool = False,
    color: bool = False,
) -> str:
    """Render the outcome as deterministic, human-oriented prose.

    A plain value (shared validator findings mapping or a scalar) renders
    with the legacy fallback.  ``explain`` appends the typed state and
    decision constructors; ``color`` styles only the outcome-class line and
    never changes words or ordering.
    """

    if not isinstance(result, CommandResult):
        return _render_findings_mapping(result)
    outcome = result.outcome
    lines: list[str] = []
    if not (quiet and isinstance(outcome, Succeeded) and not result.changes):
        label = _outcome_class(outcome)
        if color:
            label = f"{_OUTCOME_COLORS.get(label, '\x1b[31m')}{label}{_ANSI_RESET}"
        lines.append(label)
    for change in result.changes:
        lines.append(f"{change.kind}: {change.subject}: {change.detail}")
    for finding in result.findings:
        lines.append(finding.render())
    for diagnostic in _outcome_diagnostics(outcome):
        lines.append(
            f"{diagnostic.code}: {diagnostic.subject}: {diagnostic.summary}; next: {_render_next_action(diagnostic.next_action)}"
        )
    if explain:
        lines.append(f"state: {_document_kind(result.state_document)}")
        lines.append(f"decision: {_document_kind(result.decision_document)}")
    return "\n".join(lines)


def _color_enabled(  # pyright: ignore[reportUnusedFunction] — shared color-resolution helper, imported by the cli shell
    presentation: PresentationOptions,
) -> bool:
    """Resolve the text-presentation color request against the terminal."""

    match presentation.color:
        case "always":
            return True
        case "never":
            return False
        case "auto":
            return bool(sys.stdout.isatty()) and os.environ.get("NO_COLOR") is None
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        presentation.color
    )
