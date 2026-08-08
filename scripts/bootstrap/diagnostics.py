"""Stable diagnostics and command outcomes shared by text and JSON presenters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from scripts.bootstrap.errors import (
    CommandError,
    ContractError,
    InputError,
    ObservationError,
    ProcessError,
    SignalNumber,
    TransactionError,
    TransactionErrorKind,
    TransitionError,
    UsageError,
)
from scripts.bootstrap.errors import (
    InternalFailure as CoreInternalFailure,
)


class DiagnosticCategory(StrEnum):
    USAGE = "usage"
    INPUT = "input"
    OBSERVATION = "observation"
    CONTRACT = "contract"
    TRANSITION = "transition"
    TRANSACTION = "transaction"
    INTERNAL = "internal"


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class NoAutomaticAction:
    instruction: str


@dataclass(frozen=True, slots=True)
class RunCommand:
    command: tuple[str, ...]


type NextAction = NoAutomaticAction | RunCommand


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    subject: str
    summary: str
    details: str
    next_action: NextAction


def _category(error: CommandError) -> DiagnosticCategory:
    match error:
        case UsageError():
            return DiagnosticCategory.USAGE
        case InputError():
            return DiagnosticCategory.INPUT
        case ObservationError():
            return DiagnosticCategory.OBSERVATION
        case ContractError():
            return DiagnosticCategory.CONTRACT
        case TransitionError():
            return DiagnosticCategory.TRANSITION
        case TransactionError():
            return DiagnosticCategory.TRANSACTION
        case CoreInternalFailure():
            return DiagnosticCategory.INTERNAL
    return assert_never(error)  # pragma: no cover


def _kind_name(error: CommandError) -> str:
    match error:
        case TransactionError(
            kind=TransactionErrorKind.PRIMITIVE_FAILED,
            primitive=primitive,
        ) if primitive is not None:
            return f"{error.kind.value}_{primitive.value}"
        case TransactionError():
            return error.kind.value
        case CoreInternalFailure(code=code):
            return code.value
        case (
            UsageError()
            | InputError()
            | ObservationError()
            | ContractError()
            | TransitionError()
        ):
            return error.kind.value
    return assert_never(error)  # pragma: no cover


def command_error_diagnostic(error: CommandError) -> Diagnostic:
    """Map every closed command-error constructor to one bounded stable diagnostic."""

    category = _category(error)
    code = f"BOOTSTRAP_{category.value.upper()}_{_kind_name(error).upper()}"
    subject = getattr(error, "subject", "")
    if not isinstance(subject, str):
        subject = ""
    return Diagnostic(
        code=code,
        category=category,
        severity=DiagnosticSeverity.ERROR,
        subject=subject,
        summary=f"{category.value.title()} error",
        details=f"The requested operation could not continue ({_kind_name(error)}).",
        next_action=NoAutomaticAction(
            "inspect the diagnostic and correct the reported condition"
        ),
    )


def limit_diagnostic(kind: str, observed: int, limit: int) -> Diagnostic:
    return Diagnostic(
        code=f"BOOTSTRAP_INPUT_LIMIT_{kind.upper()}",
        category=DiagnosticCategory.INPUT,
        severity=DiagnosticSeverity.ERROR,
        subject=kind,
        summary="Resource limit exceeded",
        details=f"Observed {observed}; the configured limit is {limit}.",
        next_action=NoAutomaticAction("reduce the input or split the operation"),
    )


@dataclass(frozen=True, slots=True)
class NotAttempted:
    reason: str


@dataclass(frozen=True, slots=True)
class HookExited:
    status: int
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass(frozen=True, slots=True)
class HookSignalled:
    signal: SignalNumber
    stdout: bytes = b""
    stderr: bytes = b""


@dataclass(frozen=True, slots=True)
class HookLaunchFailed:
    process_error: ProcessError


type HookEvidence = NotAttempted | HookExited | HookSignalled | HookLaunchFailed


@dataclass(frozen=True, slots=True)
class Succeeded:
    diagnostics: tuple[Diagnostic, ...] = ()
    hook_evidence: HookEvidence = NotAttempted("not applicable")
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class ActionRequired:
    diagnostics: tuple[Diagnostic, ...]
    hook_evidence: HookEvidence = NotAttempted("not attempted")
    exit_code: int = 1


@dataclass(frozen=True, slots=True)
class InvalidRequest:
    diagnostics: tuple[Diagnostic, ...]
    exit_code: int = 2


@dataclass(frozen=True, slots=True)
class ContractFailure:
    diagnostics: tuple[Diagnostic, ...]
    exit_code: int = 2


@dataclass(frozen=True, slots=True)
class RecoveryFailure:
    diagnostics: tuple[Diagnostic, ...]
    exit_code: int = 2


@dataclass(frozen=True, slots=True)
class InternalFailure:
    diagnostics: tuple[Diagnostic, ...]
    exit_code: int = 2


type CommandOutcome = (
    Succeeded
    | ActionRequired
    | InvalidRequest
    | ContractFailure
    | RecoveryFailure
    | InternalFailure
)


def outcome_for_error(error: CommandError) -> CommandOutcome:
    diagnostic = command_error_diagnostic(error)
    match error:
        case UsageError() | InputError():
            return InvalidRequest((diagnostic,))
        case ContractError():
            return ContractFailure((diagnostic,))
        case TransactionError():
            return RecoveryFailure((diagnostic,))
        case CoreInternalFailure():
            return InternalFailure((diagnostic,))
        case ObservationError() | TransitionError():
            return ActionRequired((diagnostic,))
    return assert_never(error)  # pragma: no cover
