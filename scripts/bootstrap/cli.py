"""Thin CLI adapter: argparse token grammar, effect shell, and deterministic output.

Parsing is a token grammar only.  ``argparse`` callbacks never dispatch domain
work; the single ``error``/``exit`` boundary converts parse failures into
closed ``UsageError`` values.  Pure decoding turns parsed values into exactly
one ``Intent`` constructor, the observation shell builds one closed
``SystemState``, the total decision algebra picks the transition, and the
transaction interpreter executes exactly the effect requests the machine
emits.  Text and JSON are two pure renderers of the same outcome.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, assert_never, cast, override

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.decisions import RecoveryDecision
from scripts.bootstrap.diagnostics import (
    ActionRequired,
    CommandOutcome,
    ContractFailure,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticSeverity,
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
    command_error_diagnostic,
    outcome_for_error,
)
from scripts.bootstrap.errors import (
    CommandError,
    ContractError,
    ContractErrorKind,
    InputError,
    InputErrorKind,
    InternalCode,
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
    UsageError,
    UsageErrorKind,
    sanitize_errno,
)
from scripts.bootstrap.errors import (
    InternalFailure as CoreInternalFailure,
)
from scripts.bootstrap.fs_effects import (
    ChildEntry,
    ChildKind,
    classify_child,
    fsync_directory,
    fsync_file,
    list_directory_entries,
    map_observation_error,
    open_regular_no_follow,
    read_file_bounded,
    walk_no_follow,
    write_all,
    write_file_exclusive,
)
from scripts.bootstrap.git_state import (
    ResolvedGitWorktree,
    resolve_git_worktree,
    run_git,
)
from scripts.bootstrap.identity import (
    DirectoryEntry,
    DirectoryState,
    FileContentIdentity,
    FileEntry,
    FileState,
    PosixMode,
    TargetIdentity,
    content_identity,
    sha256_hex,
    tagged_digest,
)
from scripts.bootstrap.intents import (
    Add,
    AddOptions,
    Apply,
    ApplyOptions,
    ApplyPlanOptions,
    GenerationPath,
    InitBundle,
    InitOptions,
    InspectStatus,
    Intent,
    PlanAdd,
    PlanApply,
    PlanReconcile,
    PlanRestore,
    ProjectIntent,
    Reconcile,
    ReconcileOptions,
    Recover,
    RecoverOptions,
    Restore,
    RestoreOptions,
    StatusOptions,
)
from scripts.bootstrap.journal import (
    JournalEnvelope,
    PreparationIdentity,
    PreparationRole,
    StateRootSnapshot,
    capture_state_root,
    classify_state_root,
    decode_journal,
    new_ownership_token,
    new_transaction_id,
    persist_journal,
)
from scripts.bootstrap.locking import LockGuard, acquire_lock, release_lock
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    LicensingRecord,
    ManifestAdditions,
    ManifestAnswers,
    ProfileSelection,
    ProjectFacts,
    SlotContent,
)
from scripts.bootstrap.observation import (
    CapturedDirectory,
    CapturedFile,
    ProjectObservationPass,
    StableRawProjectObservation,
    build_system_state,
    classify_project_observation,
    collect_coherent_observation,
    target_protection_for_remotes,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.plan_digest import (
    PlanReceipt,
    build_receipt,
    encode_receipt,
    plan_receipt_digest,
    reconstruct_plan,
)
from scripts.bootstrap.planner import (
    CleanMaintenance,
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    DirectoryOperation,
    ExpectedGatePass,
    FileOperation,
    ObservedDirectoryEntry,
    ObservedFileEntry,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    RetainMaintenance,
    SeedOnceInput,
    TargetSnapshot,
    apply_plan,
    compile_initial_plan,
    evaluate_expected,
)
from scripts.bootstrap.process_effects import (
    Launched,
    LaunchFailed,
    TimedOut,
    run_captured,
    signalled,
)
from scripts.bootstrap.readiness import (
    Finding,
    MechanicalReadinessResult,
    Repository,
    SubjectPath,
)
from scripts.bootstrap.recovery import (
    CandidateIntact,
    CleanupMissing,
    CleanupThirdState,
    CleanupVerified,
    ObservedArtifact,
    PreStateIntact,
    ThirdStateFound,
    cleanup_step,
    restored_verification,
    sealed_verification,
)
from scripts.bootstrap.render import (
    CoreDefinition,
    LicensingInfo,
    MaintenanceInfo,
    ProfileInfo,
    ProjectInfo,
    RenderInput,
    render_managed,
)
from scripts.bootstrap.resolver import (
    ResolvedBundle,
    resolve_bundle,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.rollback import (
    AlreadyRestored,
    RemoveCreatedTreeAtomically,
    RestoreEmptyDirectoryAtomically,
    RestoreOldFile,
    RollbackThirdState,
    derive_rollback_preparations,
    derive_rollback_specs,
    rollback_directory_step,
    rollback_file_step,
)
from scripts.bootstrap.scaffold import (
    COPIER_ANSWERS_PATH,
    MAINTENANCE_INVENTORY_PATH,
    SEED_ONCE_SLOTS,
    CleanupEntryObservation,
    classify_cleanup,
    cleanup_directory_digest,
    decode_cleanup_inventory,
)
from scripts.bootstrap.schemas import (
    BootstrapBundle,
    FileContent,
    ScaffoldContent,
)
from scripts.bootstrap.state import (
    CleanupContract,
    CleanupContractValid,
    CleanupObservation,
    CopierCondition,
    CopierExistingProject,
    InvalidManifest,
    ManagedObservation,
    NoJournal,
    ProjectObservation,
    SnapshotCondition,
    SnapshotExistingProject,
    SystemState,
    TargetEnvironment,
    TargetUnavailable,
    UnsupportedGitTarget,
)
from scripts.bootstrap.state import UnsupportedGitTarget as GitUnsupportedTarget
from scripts.bootstrap.transaction import (
    AcquireLock,
    ApplyOne,
    AttemptRollbackOne,
    CleaningForward,
    CleaningRollback,
    CleanOne,
    CleanupCompleted,
    CompiledTransaction,
    Completed,
    EffectError,
    EffectFailed,
    EffectObservation,
    EffectRequest,
    EffectRequestKind,
    Installing,
    JournalPersisted,
    LockAcquired,
    LockedTransaction,
    LockRefused,
    LockReleased,
    MutatingTransaction,
    NeedLock,
    NeedMutatingJournal,
    NeedPlannedJournal,
    NeedRestoredJournal,
    NeedSealedJournal,
    ObserveAgain,
    ObservedDirectoryAbsent,
    ObservedDirectoryPresent,
    ObservedEffect,
    ObservedFileAbsent,
    ObservedFilePresent,
    ObservedPathState,
    ObservePostState,
    OperationApplied,
    PersistJournal,
    PlannedTransaction,
    PostStateObserved,
    PreparationCompleted,
    PrepareOne,
    Preparing,
    ReleaseLock,
    Reobserved,
    RollbackAlreadyRestored,
    RollbackRestoredNow,
    RollbackStepCompleted,
    RollingBack,
    Start,
    Stopped,
    TransactionEvent,
    TransactionInstruction,
    TransactionMachineState,
    TransactionOutcome,
    TransactionTerminal,
    ValidatedLockedTransaction,
    VerifiedRestoredTransaction,
    derive_preparation_specs,
    mutating_envelope,
    planned_envelope,
    request_kind,
    restored_envelope,
    sealed_envelope,
    step_transaction,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, JournalPhase, ResourceLimits

# ---------------------------------------------------------------------------
# Command metadata and the closed usage grammar
# ---------------------------------------------------------------------------

INSPECTION_COMMANDS = frozenset({"status"})
PLANNING_COMMANDS = frozenset(
    {"plan apply", "plan add", "plan restore", "plan reconcile"}
)

HOOK_PATH = RepoPath("scripts/validate-project")
_HOOK_TIMEOUT_SECONDS = 600.0
_HOOK_STREAM_BOUND = 64 * 1024
_BUNDLE_FILE = "bootstrap.json"
_STAGE_DIR_NAME = ".agentic-template-stage"
_MARKER_NAME = "marker"
_PAYLOAD_NAME = "payload"

_ENVELOPE_SCHEMA_VERSION = 1


class _UsageErrorRaised(Exception):
    """Internal parse-boundary exception; converted to ``UsageError`` immediately."""

    error: UsageError

    def __init__(self, error: UsageError) -> None:
        super().__init__(
            str(getattr(error, "kind", None) or getattr(error, "code", None) or "error")
        )
        self.error = error


class _HelpRequested(Exception):
    """argparse already rendered help to stdout; the command exits 0."""


class _CapturingArgumentParser(argparse.ArgumentParser):
    """A token grammar whose ``error``/``exit`` callbacks never terminate the process."""

    @override
    def error(self, message: str) -> NoReturn:
        raise _UsageErrorRaised(
            UsageError(_usage_kind(message), _usage_subject(message))
        )

    @override
    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if status == 0 and message is None:
            raise _HelpRequested()
        raise _UsageErrorRaised(
            UsageError(_usage_kind(message or ""), _usage_subject(message or ""))
        )


def _usage_kind(message: str) -> UsageErrorKind:
    lowered = message.lower()
    if "invalid choice" in lowered and "choose from" in lowered:
        # argparse appends "(choose from ...)" to every invalid-choice
        # message; an "argument --option:" prefix means an invalid option
        # VALUE, while a subparser destination means an unknown command.
        if "argument --" in lowered:
            return UsageErrorKind.INVALID_VALUE
        return UsageErrorKind.UNKNOWN_COMMAND
    if "invalid choice" in lowered:
        return UsageErrorKind.INVALID_VALUE
    if "unrecognized arguments" in lowered:
        return UsageErrorKind.UNKNOWN_OPTION
    if "the following arguments are required" in lowered:
        return UsageErrorKind.MISSING_OPTION
    if (
        "expected one argument" in lowered
        or "expected at least one argument" in lowered
    ):
        return UsageErrorKind.MISSING_OPTION
    if "not allowed with" in lowered:
        return UsageErrorKind.CONFLICTING_OPTIONS
    if "argument" in lowered:
        return UsageErrorKind.INVALID_VALUE
    return UsageErrorKind.UNKNOWN_OPTION


def _usage_subject(message: str) -> str:
    return message.strip()[:200]


def _build_parser() -> _CapturingArgumentParser:
    parser = _CapturingArgumentParser(
        prog="python3 scripts/bootstrap_project.py",
        add_help=True,
        description=(
            "Deterministic capability-profile-driven project bootstrap. "
            "Global output options precede the command."
        ),
    )
    _ = parser.add_argument("--format", choices=("text", "json"), default="text")
    _ = parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto"
    )
    _ = parser.add_argument("--explain", action="store_true")
    _ = parser.add_argument("--quiet", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", add_help=True)
    _ = init.add_argument("--output", required=True)
    _ = init.add_argument("--from", required=True, dest="from_path")

    status = subparsers.add_parser("status", add_help=True)
    _ = status.add_argument("--target")

    plan = subparsers.add_parser("plan", add_help=True)
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)
    for plan_command in ("apply", "add", "restore", "reconcile"):
        plan_parser = plan_subparsers.add_parser(plan_command, add_help=True)
        _plan_arguments(plan_command, plan_parser)

    apply = subparsers.add_parser("apply", add_help=True)
    _ = apply.add_argument("--bundle", required=True)
    _ = apply.add_argument("--target")
    _ = apply.add_argument("--leave-maintenance-artifacts", action="store_true")

    add = subparsers.add_parser("add", add_help=True)
    _ = add.add_argument("--input", required=True, dest="input_path")
    _ = add.add_argument("--target")

    restore = subparsers.add_parser("restore", add_help=True)
    _ = restore.add_argument("--path", action="append", default=[])
    _ = restore.add_argument("--target")

    reconcile = subparsers.add_parser("reconcile", add_help=True)
    _ = reconcile.add_argument("--target")
    _ = reconcile.add_argument("--overwrite-drift", action="store_true")
    _ = reconcile.add_argument("--plan")

    recover = subparsers.add_parser("recover", add_help=True)
    _ = recover.add_argument("--target")
    return parser


def _plan_arguments(command: str, parser: argparse.ArgumentParser) -> None:
    if command == "apply":
        _ = parser.add_argument("--bundle", required=True)
        _ = parser.add_argument("--leave-maintenance-artifacts", action="store_true")
    elif command == "add":
        _ = parser.add_argument("--input", required=True, dest="input_path")
    elif command == "restore":
        _ = parser.add_argument("--path", action="append", default=[])
    elif command == "reconcile":
        _ = parser.add_argument("--overwrite-drift", action="store_true")
    _ = parser.add_argument("--target")
    _ = parser.add_argument("--out")


@dataclass(frozen=True, slots=True)
class PresentationOptions:
    format: Literal["text", "json"] = "text"
    color: Literal["auto", "always", "never"] = "auto"
    explain: bool = False
    quiet: bool = False


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    command: str
    presentation: PresentationOptions
    intent: Intent
    target: str | None
    bundle_path: str | None
    input_path: str | None
    out_path: str | None
    plan_path: str | None
    leave_maintenance_artifacts: bool


def parse_argv(argv: list[str]) -> Result[ParsedCommand | str, UsageError]:
    """Run the token grammar and decode primitive values into one ``Intent``.

    An ``Ok`` string result carries already-rendered help text (exit 0).
    """

    parser = _build_parser()
    try:
        namespace = parser.parse_args(argv)
    except _HelpRequested:
        # argparse already rendered help to stdout; the Ok-string result exits 0.
        return Ok("")
    except _UsageErrorRaised as raised:
        return Err(raised.error)
    presentation = PresentationOptions(
        format=cast(Literal["text", "json"], namespace.format),
        color=cast(Literal["auto", "always", "never"], namespace.color),
        explain=cast(bool, namespace.explain),
        quiet=cast(bool, namespace.quiet),
    )
    if presentation.format == "json" and (
        cast(str, namespace.color) != "auto" or cast(bool, namespace.quiet)
    ):
        return Err(
            UsageError(
                UsageErrorKind.CONFLICTING_OPTIONS,
                "JSON presentation rejects --color and --quiet",
            )
        )
    command = cast(str, namespace.command)
    if command == "plan":
        command = f"plan {cast(str, namespace.plan_command)}"
    out_path = cast(str | None, getattr(namespace, "out", None))
    if out_path == "-":
        return Err(
            UsageError(
                UsageErrorKind.INVALID_VALUE,
                "--out refuses '-' as a destination",
            )
        )
    if command == "reconcile":
        overwrite = bool(getattr(namespace, "overwrite_drift", False))
        plan_path = cast(str | None, getattr(namespace, "plan", None))
        if overwrite and plan_path is None:
            return Err(
                UsageError(
                    UsageErrorKind.MISSING_OPTION,
                    "--overwrite-drift requires --plan FILE",
                )
            )
        if plan_path is not None and not overwrite:
            return Err(
                UsageError(
                    UsageErrorKind.MISSING_OPTION,
                    "--plan FILE requires --overwrite-drift",
                )
            )
    try:
        intent = _decode_intent(command, namespace)
    except ValueError as error:
        return Err(UsageError(UsageErrorKind.INVALID_VALUE, str(error)))
    return Ok(
        ParsedCommand(
            command=command,
            presentation=presentation,
            intent=intent,
            target=cast(str | None, getattr(namespace, "target", None)),
            bundle_path=cast(
                str | None,
                getattr(namespace, "bundle", None)
                or getattr(namespace, "from_path", None),
            ),
            input_path=cast(str | None, getattr(namespace, "input_path", None)),
            out_path=cast(str | None, getattr(namespace, "out", None)),
            plan_path=cast(str | None, getattr(namespace, "plan", None)),
            leave_maintenance_artifacts=bool(
                getattr(namespace, "leave_maintenance_artifacts", False)
            ),
        )
    )


def _decode_intent(command: str, namespace: argparse.Namespace) -> Intent:
    match command:
        case "init":
            return InitBundle(InitOptions(output=RepoPath(cast(str, namespace.output))))
        case "status":
            return InspectStatus(StatusOptions())
        case "plan apply":
            return PlanApply(
                ApplyPlanOptions(
                    leave_maintenance_artifacts=cast(
                        bool, namespace.leave_maintenance_artifacts
                    )
                )
            )
        case "plan add":
            return PlanAdd(AddOptions())
        case "plan restore":
            return PlanRestore(
                RestoreOptions(_decode_restore_paths(cast(object, namespace.path)))
            )
        case "plan reconcile":
            return PlanReconcile(
                ReconcileOptions(overwrite_drift=cast(bool, namespace.overwrite_drift))
            )
        case "apply":
            return Apply(
                ApplyOptions(
                    leave_maintenance_artifacts=cast(
                        bool, namespace.leave_maintenance_artifacts
                    )
                )
            )
        case "add":
            return Add(AddOptions())
        case "restore":
            return Restore(
                RestoreOptions(_decode_restore_paths(cast(object, namespace.path)))
            )
        case "reconcile":
            return Reconcile(
                ReconcileOptions(overwrite_drift=cast(bool, namespace.overwrite_drift))
            )
        case "recover":
            return Recover(RecoverOptions())
        case _:
            raise ValueError(f"unknown command: {command}")


def _decode_restore_paths(raw: object) -> tuple[RepoPath, ...]:
    if not isinstance(raw, list):
        raise ValueError("restore paths must be a list")
    paths: list[RepoPath] = []
    for value in cast(list[object], raw):
        if not isinstance(value, str):
            raise ValueError("restore path must be a string")
        match parse_path(value):
            case Err(_):
                raise ValueError(f"unsafe restore path: {value}")
            case Ok(path):
                pass
        if path in paths:
            raise ValueError(f"repeated restore path: {value}")
        paths.append(path)
    return tuple(paths)


# ---------------------------------------------------------------------------
# Outcome and envelope values
# ---------------------------------------------------------------------------


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


def _result(
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


def render_json(result: CommandResult) -> str:
    """Serialize the canonical envelope as one JSON document."""

    return canonical_json(command_envelope(result)).decode("utf-8")


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


def render_text(
    result: CommandResult,
    *,
    quiet: bool = False,
    explain: bool = False,
    color: bool = False,
) -> str:
    """Render the outcome as deterministic, human-oriented prose.

    ``explain`` appends the typed state and decision constructors; ``color``
    styles only the outcome-class line and never changes words or ordering.
    """

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


def _color_enabled(presentation: PresentationOptions) -> bool:
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


# ---------------------------------------------------------------------------
# Shell effects: target resolution and the observation pass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedShellTarget:
    """Resolution facts for one verified target."""

    environment: TargetEnvironment
    worktree: ResolvedGitWorktree | None = None
    remotes: tuple[str, ...] = ()


def _template_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _remotes_for(worktree: ResolvedGitWorktree) -> tuple[str, ...]:
    match run_git(("remote", "--verbose"), cwd=worktree.root_abs):
        case Ok(result) if result.returncode == 0:
            pass
        case _:
            # A failed git command may carry partial output; never parse it.
            return ()
    urls: list[str] = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            urls.append(parts[1])
    return tuple(sorted(set(urls)))


def resolve_shell_target(
    target: str | None,
    *,
    cwd: str,
) -> Result[ResolvedShellTarget, ObservationError | CoreInternalFailure]:
    """Resolve the verified absolute worktree target and its protection."""

    root_abs = os.path.abspath(target if target is not None else cwd)
    match resolve_git_worktree(os.fsencode(root_abs)):
        case Err(error):
            return Err(error)
        case Ok(resolution):
            if isinstance(resolution, GitUnsupportedTarget):
                return Ok(
                    ResolvedShellTarget(
                        environment=UnsupportedGitTarget(resolution.reason)
                    )
                )
            worktree = resolution
    remotes = _remotes_for(worktree)
    protection = target_protection_for_remotes(remotes)
    from scripts.bootstrap.state import SupportedWorktree, WorktreeContext

    return Ok(
        ResolvedShellTarget(
            environment=SupportedWorktree(
                WorktreeContext(
                    target=worktree.target,
                    state_root=RepoPath("agentic-template"),
                    protection=protection,
                )
            ),
            worktree=worktree,
            remotes=remotes,
        )
    )


def _open_state_root(
    state_root_abs: bytes,
) -> Result[int | None, ObservationError | CoreInternalFailure]:
    root_fd = os.open(b"/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        components = tuple(part for part in state_root_abs.split(b"/") if part)
        match walk_no_follow(root_fd, components, allow_absent_final=True):
            case Err(error):
                return Err(error)
            case Ok(fd):
                return Ok(fd)
    finally:
        os.close(root_fd)


def _empty_state_root_snapshot(target: TargetIdentity) -> StateRootSnapshot:
    return StateRootSnapshot(
        target=target,
        entries=(),
        journal=None,
        journal_irregular=False,
        pending=None,
        pending_irregular=False,
    )


def _capture_tree(
    root_abs: bytes,
    git_dir_abs: bytes,
    limits: ResourceLimits,
) -> Result[
    tuple[tuple[CapturedFile, ...], tuple[CapturedDirectory, ...]],
    ObservationError | CoreInternalFailure,
]:
    """Capture every non-administrative path: sorted, bounded, symlink-rejecting."""

    files: list[CapturedFile] = []
    directories: list[CapturedDirectory] = []
    total_bytes = 0
    git_dir = os.fsdecode(git_dir_abs)

    def visit(
        directory: str, relative: str
    ) -> Result[None, ObservationError | CoreInternalFailure]:
        nonlocal total_bytes
        try:
            with os.scandir(directory) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as error:
            return Err(map_observation_error(error, relative or "."))
        for name in names:
            child_abs = os.path.join(directory, name)
            child_rel = f"{relative}/{name}" if relative else name
            if child_abs == git_dir or child_abs.startswith(git_dir + os.sep):
                continue
            try:
                info = os.stat(child_abs, follow_symlinks=False)
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            if stat.S_ISLNK(info.st_mode):
                return Err(
                    ObservationError(
                        ObservationErrorKind.SYMLINK_ENCOUNTERED, child_rel
                    )
                )
            if stat.S_ISDIR(info.st_mode):
                if len(directories) + len(files) >= limits.max_paths:
                    return Err(
                        ObservationError(
                            ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "paths"
                        )
                    )
                match parse_path(child_rel):
                    case Err(_):
                        return Err(
                            ObservationError(
                                ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED,
                                child_rel,
                            )
                        )
                    case Ok(path):
                        pass
                directories.append(
                    CapturedDirectory(path, PosixMode(info.st_mode & 0o7777))
                )
                match visit(child_abs, child_rel):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return Err(
                    ObservationError(
                        ObservationErrorKind.PATH_MISSING,
                        f"{child_rel} is not a regular file",
                    )
                )
            if len(directories) + len(files) >= limits.max_paths:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "paths"
                    )
                )
            if info.st_size > limits.max_file_bytes:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                    )
                )
            total_bytes += info.st_size
            if total_bytes > limits.max_unique_bytes:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "unique_bytes"
                    )
                )
            try:
                with open(child_abs, "rb") as handle:
                    content = handle.read()
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            match parse_path(child_rel):
                case Err(_):
                    return Err(
                        ObservationError(
                            ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                        )
                    )
                case Ok(path):
                    pass
            files.append(CapturedFile(path, content, PosixMode(info.st_mode & 0o7777)))
        return Ok(None)

    match visit(os.fsdecode(root_abs), ""):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    files.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    directories.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    return Ok((tuple(files), tuple(directories)))


def capture_project_pass(
    resolved: ResolvedShellTarget,
    *,
    limits: ResourceLimits,
) -> Result[ProjectObservationPass, ObservationError | CoreInternalFailure]:
    """Capture one complete bounded observation pass for a supported worktree."""

    worktree = resolved.worktree
    if worktree is None:
        return Err(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE))
    match _open_state_root(worktree.state_root_abs):
        case Err(error):
            return Err(error)
        case Ok(fd):
            pass
    if fd is None:
        state_root = _empty_state_root_snapshot(worktree.target)
    else:
        try:
            match capture_state_root(fd, worktree.target, limits=limits):
                case Err(error):
                    return Err(error)
                case Ok(captured):
                    state_root = captured
        finally:
            os.close(fd)
    match _capture_tree(worktree.root_abs, worktree.git_dir_abs, limits):
        case Err(error):
            return Err(error)
        case Ok((files, directories)):
            pass
    return Ok(
        ProjectObservationPass(
            target=worktree.target,
            remotes=resolved.remotes,
            state_root=state_root,
            files=files,
            directories=directories,
        )
    )


def _collect_pass(
    resolved: ResolvedShellTarget,
    limits: ResourceLimits,
) -> Callable[[], StableRawProjectObservation]:
    def collect() -> StableRawProjectObservation:
        match capture_project_pass(resolved, limits=limits):
            case Err(error):
                raise _PassCaptureFailed(error)
            case Ok(pass_):
                return StableRawProjectObservation(pass_, b"")

    return collect


class _PassCaptureFailed(Exception):
    error: ObservationError | CoreInternalFailure

    def __init__(self, error: ObservationError | CoreInternalFailure) -> None:
        super().__init__(
            str(getattr(error, "kind", None) or getattr(error, "code", None) or "error")
        )
        self.error = error


@dataclass(frozen=True, slots=True)
class SystemObservation:
    """One closed system observation: environment, journal, project, and state."""

    environment: TargetEnvironment
    pass_: ProjectObservationPass | None
    system: SystemState


def _scaffold_bytes(template_root: str) -> dict[RepoPath, bytes]:
    """Load the template package's seed-once scaffold content, bounded."""

    scaffold: dict[RepoPath, bytes] = {}
    for path in SEED_ONCE_SLOTS.values():
        absolute = os.path.join(template_root, path.value)
        try:
            with open(absolute, "rb") as handle:
                content = handle.read()
        except OSError:
            continue
        if len(content) <= DEFAULT_LIMITS.max_file_bytes:
            scaffold[path] = content
    return scaffold


def _cleanup_observation(
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
) -> CleanupObservation:
    """Classify the snapshot maintenance inventory against observed paths."""

    from scripts.bootstrap.state import NoSnapshotCleanup

    inventory_file = files.get(MAINTENANCE_INVENTORY_PATH)
    if inventory_file is None:
        return NoSnapshotCleanup()
    match decode_cleanup_inventory(inventory_file.content):
        case Err(mismatch):
            return mismatch
        case Ok(inventory):
            pass
    observed: dict[RepoPath, CleanupEntryObservation] = {}
    for path, kind, _digest in inventory.entries:
        if kind == "file":
            entry = files.get(path)
            observed[path] = CleanupEntryObservation(
                path=path,
                present=entry is not None,
                kind="file" if entry is not None else None,
                sha256=(sha256_hex(entry.content) if entry is not None else None),
            )
        else:
            if path not in directories:
                observed[path] = CleanupEntryObservation(path, False)
                continue
            prefix = path.value + "/"
            child_files = tuple(
                (entry.path, entry.content, entry.mode.value)
                for entry in files.values()
                if entry.path.value.startswith(prefix)
            )
            child_dirs = tuple(
                (entry.path, entry.mode.value)
                for entry in directories.values()
                if entry.path.value.startswith(prefix)
            )
            observed[path] = CleanupEntryObservation(
                path=path,
                present=True,
                kind="directory",
                sha256=cleanup_directory_digest(
                    path, files=child_files, directories=child_dirs
                ),
            )
    return classify_cleanup(inventory=inventory_file.content, observed=observed)


def _retained_cleanup_contract(
    pass_: ProjectObservationPass,
) -> Result[CleanupContract, ContractError]:
    """Derive the retention contract for a cleanup inventory that no longer matches.

    ``--leave-maintenance-artifacts`` skips every cleanup deletion.  Until the
    fingerprinted source-ownership declaration lands, the retained set is the
    decoded inventory's declared paths plus the inventory itself when present.
    """

    inventory = next(
        (entry for entry in pass_.files if entry.path == MAINTENANCE_INVENTORY_PATH),
        None,
    )
    if inventory is None:
        return Err(
            ContractError(
                ContractErrorKind.CLEANUP_CONTRACT_INVALID,
                "--leave-maintenance-artifacts requires a maintenance inventory",
            )
        )
    match decode_cleanup_inventory(inventory.content):
        case Err(_):
            declared: tuple[RepoPath, ...] = ()
        case Ok(decoded):
            declared = tuple(path for path, _kind, _digest in decoded.entries)
    retained = tuple(
        sorted(
            (*declared, MAINTENANCE_INVENTORY_PATH),
            key=lambda path: path.value.encode("utf-8"),
        )
    )
    return Ok(
        CleanupContract(
            lifecycle_paths=(),
            cleanup_paths=retained,
            fingerprint=tagged_digest(b"cleanup-inventory", inventory.content),
        )
    )


def _snapshot_evidence(
    worktree: ResolvedGitWorktree,
) -> tuple[Callable[[], bool], Callable[[RepoPath], bytes | None]]:
    """Lazy Git-backed snapshot-repair evidence providers."""

    commit_cache: str | None = None
    reachable_cache: bool | None = None

    def recorded_commit() -> str | None:
        nonlocal commit_cache
        if commit_cache is None:
            match run_git(("rev-parse", "HEAD"), cwd=worktree.root_abs):
                case Ok(result) if result.returncode == 0:
                    commit_cache = result.stdout.decode("ascii", "replace").strip()
                case _:
                    commit_cache = ""
        return commit_cache or None

    def reachable() -> bool:
        nonlocal reachable_cache
        if reachable_cache is None:
            commit = recorded_commit()
            if commit is None:
                reachable_cache = False
            else:
                match run_git(
                    ("rev-parse", "--verify", f"{commit}^{{commit}}"),
                    cwd=worktree.root_abs,
                ):
                    case Ok(result):
                        reachable_cache = result.returncode == 0
                    case Err(_):
                        reachable_cache = False
        return reachable_cache

    def path_bytes(path: RepoPath) -> bytes | None:
        commit = recorded_commit()
        if commit is None:
            return None
        match run_git(("show", f"{commit}:{path.value}"), cwd=worktree.root_abs):
            case Ok(result) if result.returncode == 0:
                if len(result.stdout) <= DEFAULT_LIMITS.max_file_bytes:
                    return result.stdout
            case _:
                pass
        return None

    return reachable, path_bytes


def observe_system(
    resolved: ResolvedShellTarget,
    *,
    coherent: bool,
    template_root: str,
    limits: ResourceLimits,
) -> Result[SystemObservation, CommandError]:
    """Capture one (or a coherent pair of) pass and assemble the closed state."""

    from scripts.bootstrap.state import SupportedWorktree

    environment = resolved.environment
    match environment:
        case UnsupportedGitTarget():
            return Ok(
                SystemObservation(
                    environment=environment,
                    pass_=None,
                    system=TargetUnavailable(environment),
                )
            )
        case SupportedWorktree():
            pass
    try:
        if coherent:
            match collect_coherent_observation(_collect_pass(resolved, limits)):
                case Err(error):
                    return Err(error)
                case Ok(observed):
                    pass_ = cast(ProjectObservationPass, observed.semantic_identity)
        else:
            match capture_project_pass(resolved, limits=limits):
                case Err(error):
                    return Err(error)
                case Ok(captured):
                    pass_ = captured
    except _PassCaptureFailed as failed:
        return Err(failed.error)
    journal = classify_state_root(pass_.state_root)
    files = {entry.path: entry for entry in pass_.files}
    directories = {entry.path: entry for entry in pass_.directories}
    project: ProjectObservation | None = None
    if isinstance(journal, NoJournal):
        worktree = resolved.worktree
        assert worktree is not None  # supported environments always carry one
        reachable, path_bytes = _snapshot_evidence(worktree)
        project = classify_project_observation(
            copier_answers=(
                files[COPIER_ANSWERS_PATH].content
                if COPIER_ANSWERS_PATH in files
                else None
            ),
            manifest=(files[MANIFEST_PATH].content if MANIFEST_PATH in files else None),
            files=files,
            directories=directories,
            scaffold=_scaffold_bytes(template_root),
            cleanup=_cleanup_observation(files, directories),
            snapshot_commit_reachable=reachable,
            path_bytes_at_commit=path_bytes,
        )
    from scripts.bootstrap.state import SupportedWorktree as _SupportedWorktree

    state_root = (
        environment.context.state_root
        if isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] — deliberate runtime contract check
            environment, _SupportedWorktree
        )
        else RepoPath("agentic-template")
    )
    system = build_system_state(
        environment=environment,
        journal=journal,
        project=project,
        state_root=state_root,
    )
    return Ok(SystemObservation(environment=environment, pass_=pass_, system=system))


# ---------------------------------------------------------------------------
# Bundle decoding and initial-plan compilation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecodedBundle:
    """The strict decoded bootstrap bundle plus its bounded content bytes."""

    bundle: BootstrapBundle
    document: dict[str, object]
    content: dict[RepoPath, tuple[bytes, Literal["text", "binary"]]]
    bundle_digest: str


def _read_bundle_file(path: str, subject: str) -> Result[bytes, InputError]:
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError:
        return Err(InputError(InputErrorKind.MISSING_INPUT, subject))
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return Err(InputError(InputErrorKind.INPUT_LIMIT_EXCEEDED, subject))
    return Ok(content)


def _bundle_json_path(bundle_path: str) -> str:
    return (
        os.path.join(bundle_path, _BUNDLE_FILE)
        if os.path.isdir(bundle_path)
        else bundle_path
    )


def _input_error_from_validation(error: Exception) -> InputError:
    return InputError(InputErrorKind.SCHEMA_VIOLATION, str(error)[:200])


def _read_content_slot(
    root: str,
    raw_path: str,
    *,
    text: bool,
) -> Result[tuple[bytes, Literal["text", "binary"]], InputError]:
    match parse_path(raw_path):
        case Err(_):
            return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, raw_path))
        case Ok(relative):
            pass
    absolute = os.path.normpath(os.path.join(root, relative.value))
    if not absolute.startswith(
        os.path.normpath(root) + os.sep
    ) and absolute != os.path.normpath(root):
        return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, raw_path))
    match _read_bundle_file(absolute, relative.value):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        return Err(InputError(InputErrorKind.WRONG_KIND, relative.value))
    if text:
        try:
            _ = content.decode("utf-8")
        except UnicodeDecodeError:
            return Err(InputError(InputErrorKind.INVALID_ENCODING, relative.value))
    return Ok((content, "text" if text else "binary"))


def _declared_markers() -> tuple[tuple[RepoPath, bytes], ...]:
    from scripts.bootstrap.planner import SLOT_PLACEHOLDER_RULES

    return tuple((rule.path, rule.marker) for rule in SLOT_PLACEHOLDER_RULES)


def decode_bundle_input(
    bundle_path: str,
) -> Result[DecodedBundle, InputError]:
    """Strictly decode a bundle file and its referenced content, rejecting markers."""

    json_path = _bundle_json_path(bundle_path)
    match _read_bundle_file(json_path, json_path):
        case Err(error):
            return Err(error)
        case Ok(raw):
            pass
    try:
        value = decode_json(raw)
    except ValueError:
        return Err(InputError(InputErrorKind.INVALID_JSON, json_path))
    if not isinstance(value, dict):
        return Err(InputError(InputErrorKind.SCHEMA_VIOLATION, json_path))
    try:
        bundle = BootstrapBundle.model_validate(value)
    except Exception as error:
        return Err(_input_error_from_validation(error))
    root = os.path.dirname(os.path.abspath(json_path))
    content: dict[RepoPath, tuple[bytes, Literal["text", "binary"]]] = {}
    declared_paths: set[RepoPath] = set()
    for slot_path in SEED_ONCE_SLOTS.values():
        choice = cast(
            FileContent | ScaffoldContent,
            getattr(bundle.content, _slot_attr(slot_path)),
        )
        if isinstance(choice, ScaffoldContent):
            continue
        match _read_content_slot(root, choice.path, text=True):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        if RepoPath(choice.path) in declared_paths:
            return Err(InputError(InputErrorKind.MARKER_COLLISION, choice.path))
        declared_paths.add(RepoPath(choice.path))
        content[slot_path] = entry
    if bundle.licensing.path is not None:
        match _read_content_slot(root, bundle.licensing.path, text=True):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        license_path = RepoPath(bundle.licensing.path)
        if license_path in declared_paths:
            return Err(
                InputError(InputErrorKind.MARKER_COLLISION, bundle.licensing.path)
            )
        content[license_path] = entry
    for path, marker in _declared_markers():
        for slot_path, (file_bytes, _kind) in content.items():
            if path == HOOK_PATH:
                found = marker in file_bytes
            else:
                found = marker.decode("ascii") in file_bytes.decode("utf-8")
            if found:
                return Err(InputError(InputErrorKind.MARKER_COLLISION, slot_path.value))
    document = bundle.model_dump(mode="json")
    match resolve_bundle(bundle):
        case Err(failure):
            return Err(
                InputError(
                    InputErrorKind.SCHEMA_VIOLATION,
                    f"{failure.kind.value}:{failure.subject}",
                )
            )
        case Ok(_):
            pass
    return Ok(
        DecodedBundle(
            bundle=bundle,
            document=document,
            content=content,
            bundle_digest=sha256_hex(canonical_json(document)),
        )
    )


def _slot_attr(path: RepoPath) -> str:
    for slot_id, slot_path in SEED_ONCE_SLOTS.items():
        if slot_path == path:
            return slot_id
    raise KeyError(path.value)


def _read_template_file(template_root: str, relative: str) -> bytes | None:
    absolute = os.path.join(template_root, relative)
    try:
        with open(absolute, "rb") as handle:
            content = handle.read()
    except OSError:
        return None
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return None
    return content


def _seed_once_inputs(
    decoded: DecodedBundle,
    scaffold: dict[RepoPath, bytes],
    blobs: VerifiedBlobStore,
    _limits: ResourceLimits,
    template_root: str,
) -> Result[tuple[tuple[SeedOnceInput, ...], VerifiedBlobStore], CommandError]:
    from scripts.bootstrap.planner import SeedOnceInput, legal_output_paths

    seed_inputs: list[SeedOnceInput] = []
    store = blobs
    for path in sorted(SEED_ONCE_SLOTS.values(), key=lambda p: p.value.encode()):
        slot_id = _slot_attr(path)
        choice = cast(
            FileContent | ScaffoldContent, getattr(decoded.bundle.content, slot_id)
        )
        executable = path == HOOK_PATH
        if isinstance(choice, ScaffoldContent):
            content = scaffold.get(path)
            if content is None:
                return Err(
                    ContractError(
                        ContractErrorKind.INVALID_TEMPLATE,
                        f"scaffold content missing for {path.value}",
                    )
                )
        else:
            content = decoded.content[path][0]
        match store.intern(content):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        seed_inputs.append(
            SeedOnceInput(
                path=path,
                kind="binary" if executable else "text",
                mode=PosixMode.EXECUTABLE if executable else PosixMode.FILE,
                content_id=content_id,
            )
        )
    legal_paths = legal_output_paths(decoded.bundle.licensing.mode)
    if legal_paths is None:
        return Err(ContractError(ContractErrorKind.INVALID_TEMPLATE, "licensing.mode"))
    for path in legal_paths:
        if path.value == "LICENSE" and decoded.bundle.licensing.path is not None:
            content = decoded.content[path][0]
        else:
            content = _read_template_file(template_root, path.value)
            if content is None:
                return Err(
                    ContractError(
                        ContractErrorKind.INVALID_TEMPLATE,
                        f"retained legal content missing: {path.value}",
                    )
                )
        match store.intern(content):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        seed_inputs.append(
            SeedOnceInput(
                path=path, kind="text", mode=PosixMode.FILE, content_id=content_id
            )
        )
    seed_inputs.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    return Ok((tuple(seed_inputs), store))


def _manifest_answers(
    decoded: DecodedBundle, resolved: ResolvedBundle
) -> ManifestAnswers:
    slots: dict[str, SlotContent] = {}
    for slot_id, path in SEED_ONCE_SLOTS.items():
        choice = cast(
            FileContent | ScaffoldContent, getattr(decoded.bundle.content, slot_id)
        )
        if isinstance(choice, ScaffoldContent):
            slots[slot_id] = SlotContent(mode="scaffold", content_sha256=None)
        else:
            slots[slot_id] = SlotContent(
                mode="file", content_sha256=sha256_hex(decoded.content[path][0])
            )
    licensing = decoded.bundle.licensing
    return ManifestAnswers(
        project=ProjectFacts(
            name=decoded.bundle.project.name,
            default_branch=decoded.bundle.project.default_branch,
        ),
        profile=ProfileSelection(id=resolved.profile_id, requested=resolved.requested),
        settings=resolved.settings,
        licensing=LicensingRecord(
            mode=licensing.mode,
            content_sha256=(
                sha256_hex(decoded.content[RepoPath(licensing.path)][0])
                if licensing.path is not None
                else None
            ),
        ),
        slots=slots,
    )


def compile_initial_install(
    *,
    generation: GenerationPath,
    decoded: DecodedBundle,
    resolved: ResolvedBundle,
    scaffold: dict[RepoPath, bytes],
    template_root: str,
    maintenance: CleanMaintenance | RetainMaintenance,
    cleanup: CleanupContract | None,
    snapshot: TargetSnapshot,
    target_identity: TargetIdentity,
    snapshot_commit: str | None,
    limits: ResourceLimits,
) -> Result[tuple[OperationPlan, MechanicalReadinessResult], CommandError]:
    """Compile the complete initial plan for one generation path."""

    blobs = VerifiedBlobStore.empty(limits)
    match _seed_once_inputs(decoded, scaffold, blobs, limits, template_root):
        case Err(error):
            return Err(error)
        case Ok((seed_once, updated)):
            blobs = updated
    answers = _manifest_answers(decoded, resolved)
    project = ProjectInfo(
        name=decoded.bundle.project.name,
        default_branch=decoded.bundle.project.default_branch,
    )
    licensing = decoded.bundle.licensing
    maintenance_info = MaintenanceInfo(
        status=("retained" if isinstance(maintenance, RetainMaintenance) else "clean"),
        retained_paths=(
            maintenance.paths if isinstance(maintenance, RetainMaintenance) else ()
        ),
    )
    profile = ProfileInfo(id=resolved.profile_id, frozen=resolved.requested)
    render_input = RenderInput(
        render_input_version=1,
        generation_path=generation,
        project=project,
        licensing=LicensingInfo(
            mode=licensing.mode,
            content_sha256=(
                sha256_hex(decoded.content[RepoPath(licensing.path)][0])
                if licensing.path is not None
                else None
            ),
        ),
        profile=profile,
        additions=(),
        effective=resolved.effective,
        definitions={},
        core=CoreDefinition(),
        settings=resolved.settings,
        contributions=(),
        documents={},
        maintenance=maintenance_info,
        slots=answers.slots,
    )
    match render_managed(render_input, blobs):
        case Err(error):
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    f"{error.kind.value}:{error.subject}",
                )
            )
        case Ok(managed):
            pass
    match compile_initial_plan(
        generation=generation,
        target_identity=target_identity,
        answers=answers,
        additions=ManifestAdditions(),
        seed_once=seed_once,
        managed=managed,
        blobs=blobs,
        source_entries=(),
        snapshot_commit=snapshot_commit,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=snapshot,
        limits=limits,
    ):
        case Err(error):
            kind = (
                ContractErrorKind.CLEANUP_CONTRACT_INVALID
                if error.kind.value == "cleanup_disagreement"
                else ContractErrorKind.INVALID_OPERATION_PLAN
            )
            return Err(ContractError(kind, error.subject))
        case Ok(plan):
            pass
    match apply_plan(snapshot, plan):
        case Err(error):
            return Err(
                ContractError(ContractErrorKind.INVALID_OPERATION_PLAN, error.subject)
            )
        case Ok(expected_target):
            pass
    match evaluate_expected(expected_target):
        case ExpectedGatePass(readiness):
            return Ok((plan, readiness))
        case _refusal:
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    "expected target fails the template contract",
                )
            )


def plan_snapshot_paths(plan: OperationPlan) -> tuple[set[RepoPath], set[RepoPath]]:
    """Return the file and directory paths the plan's preconditions reference."""

    file_paths: set[RepoPath] = set()
    dir_paths: set[RepoPath] = set()
    for operation in plan.ordered_operations:
        match operation:
            case (
                CreateFileOperation(path=path)
                | ReplaceFileOperation(path=path)
                | DeleteFileOperation(path=path)
            ):
                file_paths.add(path)
            case CreateTreeOperation(root=root, planned_new=tree):
                dir_paths.add(root)
                for entry in tree.entries:
                    match entry:
                        case PlannedFileEntry(path=path):
                            file_paths.add(path)
                        case PlannedDirectoryEntry(path=path):
                            dir_paths.add(path)
            case RemoveEmptyDirectoryOperation(path=path):
                dir_paths.add(path)
    return file_paths, dir_paths


def _observed_identity(content: bytes, mode: PosixMode) -> FileContentIdentity:
    """Derive an observed file identity whose kind matches the plan's kinds.

    Install modes decide the kind: executable files are byte-for-byte binary
    seeds, while regular files classify as text when they are valid UTF-8.
    """

    text = not (mode.value & 0o111) and _is_utf8(content)
    return content_identity(content, text=text)


def _is_utf8(content: bytes) -> bool:
    try:
        _ = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


# ---------------------------------------------------------------------------
# Transaction effect execution and the machine driver
# ---------------------------------------------------------------------------


@dataclass
class TransactionResources:
    """Mutable effect resources held across one transaction machine run."""

    worktree: ResolvedGitWorktree
    limits: ResourceLimits = DEFAULT_LIMITS
    state_root_fd: int | None = None
    lock: LockGuard | None = None
    ownership_tokens: tuple[bytes, ...] = ()
    rollback_tokens: tuple[bytes, ...] = ()
    rollback_preparations: tuple[PreparationIdentity, ...] = ()


def _err_effect[ValueT](error: EffectError) -> Result[ValueT, EffectError]:
    """Widen one closed effect error to the exact effect-union Result parameter."""

    return Err(error)


def _rollback_error[ValueT](
    error: EffectError | TransitionError,
) -> Result[ValueT, EffectError | TransitionError]:
    """Widen one rollback error to the exact rollback-union Result parameter."""

    return Err(error)


def _parent_components(path: RepoPath) -> tuple[bytes, ...]:
    return tuple(os.fsencode(part) for part in path.value.split("/")[:-1])


def _leaf_name(path: RepoPath) -> bytes:
    return os.fsencode(path.value.split("/")[-1])


def _open_parent(
    root_fd: int, path: RepoPath
) -> Result[int, ObservationError | CoreInternalFailure]:
    components = _parent_components(path)
    if not components:
        # walk_no_follow would return the caller's borrowed root descriptor;
        # return an owned duplicate so every caller may close its result.
        return Ok(os.dup(root_fd))
    match walk_no_follow(root_fd, components):
        case Err(error):
            return Err(error)
        case Ok(fd):
            if fd is None:
                return Err(
                    ObservationError(ObservationErrorKind.PATH_MISSING, path.value)
                )
            return Ok(fd)


def _stage_root_abs(worktree: ResolvedGitWorktree, path: RepoPath) -> bytes:
    parent_abs = os.path.join(worktree.root_abs, *(_parent_components(path)))
    return os.path.join(parent_abs, os.fsencode(_STAGE_DIR_NAME))


def _precondition_changed(subject: str) -> TransactionError:
    return TransactionError(TransactionErrorKind.PRECONDITION_CHANGED, subject=subject)


def _invalid_state(subject: str) -> TransactionError:
    return TransactionError(TransactionErrorKind.INVALID_STATE_ROOT, subject=subject)


def _open_directory_abs(directory: bytes) -> Result[int, TransactionError]:
    try:
        return Ok(
            os.open(
                directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        )
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.READ_BACKUP,
                sanitize_errno(error),
                os.fsdecode(directory),
            )
        )


def _write_file_exclusive(
    directory: bytes, name: bytes, content: bytes, mode: int
) -> Result[None, EffectError]:
    match _open_directory_abs(directory):
        case Err(error):
            return _err_effect(error)
        case Ok(parent_fd):
            pass
    try:
        match write_file_exclusive(parent_fd, name, content, mode):
            case Err(error):
                return _err_effect(error)
            case Ok(_):
                return Ok(None)
    finally:
        os.close(parent_fd)


def _mkdir_exclusive(
    parent: bytes, name: bytes, mode: int
) -> Result[None, EffectError]:
    match _open_directory_abs(parent):
        case Err(error):
            return _err_effect(error)
        case Ok(parent_fd):
            pass
    try:
        try:
            os.mkdir(name, mode, dir_fd=parent_fd)
        except FileExistsError:
            return _err_effect(_invalid_state(os.fsdecode(name)))
        except OSError as error:
            return Err(
                TransactionError.primitive_failed(
                    TransactionPrimitive.CREATE_DIRECTORY,
                    sanitize_errno(error),
                    os.fsdecode(name),
                )
            )
        try:
            # mkdir modes are umask-masked; pin the exact directory mode so
            # tree and stage topology never depends on the shell umask.
            os.chmod(name, mode, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            return Err(
                TransactionError.primitive_failed(
                    TransactionPrimitive.CREATE_DIRECTORY,
                    sanitize_errno(error),
                    os.fsdecode(name),
                )
            )
        return Ok(None)
    finally:
        os.close(parent_fd)


def _fsync_dir_abs(directory: bytes) -> Result[None, EffectError]:
    match _open_directory_abs(directory):
        case Err(error):
            return _err_effect(error)
        case Ok(fd):
            pass
    try:
        match fsync_directory(fd):
            case Err(error):
                return _err_effect(error)
            case Ok(_):
                return Ok(None)
    finally:
        os.close(fd)


def _ensure_directory_chain(
    base: bytes, components: tuple[bytes, ...]
) -> Result[None, EffectError]:
    current = base
    for component in components:
        current = os.path.join(current, component)
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            continue
        except OSError as error:
            return Err(
                TransactionError.primitive_failed(
                    TransactionPrimitive.CREATE_DIRECTORY,
                    sanitize_errno(error),
                    os.fsdecode(current),
                )
            )
        try:
            # mkdir modes are umask-masked; the state root stays exactly 0700.
            os.chmod(current, 0o700, follow_symlinks=False)
        except OSError as error:
            return Err(
                TransactionError.primitive_failed(
                    TransactionPrimitive.CREATE_DIRECTORY,
                    sanitize_errno(error),
                    os.fsdecode(current),
                )
            )
    return Ok(None)


def _read_file_state_at(
    root_fd: int, path: RepoPath, limits: ResourceLimits
) -> Result[
    tuple[bytes, PosixMode, int, int] | None,
    ObservationError | CoreInternalFailure,
]:
    """Read one regular file's bytes, mode, and inode anchors; absent is ``None``."""

    match _open_parent(root_fd, path):
        case Err(ObservationError(kind=ObservationErrorKind.PATH_MISSING)):
            return Ok(None)  # a missing parent means the whole path is absent
        case Err(error):
            return Err(error)
        case Ok(parent_fd):
            pass
    try:
        match open_regular_no_follow(parent_fd, _leaf_name(path)):
            case Err(error):
                if (
                    isinstance(error, ObservationError)
                    and error.kind is ObservationErrorKind.PATH_MISSING
                ):
                    return Ok(None)
                return Err(error)
            case Ok(fd):
                pass
        try:
            match read_file_bounded(fd, limits.max_file_bytes, path.value):
                case Err(error):
                    return Err(error)
                case Ok(content):
                    pass
            try:
                info = os.fstat(fd)
            except OSError as error:
                return Err(map_observation_error(error, path.value))
            return Ok(
                (
                    content,
                    PosixMode(info.st_mode & 0o7777),
                    info.st_dev,
                    info.st_ino,
                )
            )
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _stage_dir_for(
    resources: TransactionResources,
    operation: FileOperation | DirectoryOperation,
    transaction_id: str,
    operation_index: int,
    *,
    rollback: bool = False,
) -> bytes:
    """Derive the reserved adjacent stage directory for one operation."""

    match operation:
        case (
            CreateFileOperation(path=path)
            | ReplaceFileOperation(path=path)
            | DeleteFileOperation(path=path)
        ):
            base = path
        case CreateTreeOperation(root=root):
            base = root
        case RemoveEmptyDirectoryOperation(path=path):
            base = path
    stage_root = _stage_root_abs(resources.worktree, base)
    suffix = "-rollback" if rollback else ""
    return os.path.join(
        stage_root, os.fsencode(f"{transaction_id}/{operation_index}{suffix}")
    )


def _mkdir_stage_dir(
    resources: TransactionResources,
    operation: FileOperation | DirectoryOperation,
    transaction_id: str,
    operation_index: int,
    *,
    rollback: bool = False,
) -> Result[bytes, EffectError]:
    """Create one reserved stage directory exclusively and return its path."""

    match operation:
        case (
            CreateFileOperation(path=path)
            | ReplaceFileOperation(path=path)
            | DeleteFileOperation(path=path)
        ):
            base = path
        case CreateTreeOperation(root=root):
            base = root
        case RemoveEmptyDirectoryOperation(path=path):
            base = path
    stage_root = _stage_root_abs(resources.worktree, base)
    try:
        os.makedirs(stage_root, mode=0o700, exist_ok=True)
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.CREATE_DIRECTORY,
                sanitize_errno(error),
                os.fsdecode(stage_root),
            )
        )
    try:
        # mkdir modes are umask-masked; the stage root stays exactly 0700.
        os.chmod(stage_root, 0o700, follow_symlinks=False)
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.CREATE_DIRECTORY,
                sanitize_errno(error),
                os.fsdecode(stage_root),
            )
        )
    tx_dir = os.path.join(stage_root, os.fsencode(transaction_id))
    try:
        os.mkdir(tx_dir, 0o700)
    except FileExistsError:
        pass
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.CREATE_DIRECTORY,
                sanitize_errno(error),
                os.fsdecode(tx_dir),
            )
        )
    try:
        os.chmod(tx_dir, 0o700, follow_symlinks=False)
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.CREATE_DIRECTORY,
                sanitize_errno(error),
                os.fsdecode(tx_dir),
            )
        )
    suffix = "-rollback" if rollback else ""
    leaf = os.fsencode(f"{operation_index}{suffix}")
    match _mkdir_exclusive(tx_dir, leaf, 0o700):
        case Err(error):
            return _err_effect(error)
        case Ok(_):
            pass
    return Ok(os.path.join(tx_dir, leaf))


def _write_stage_marker(
    stage_dir: bytes,
    *,
    identity: PreparationIdentity,
    token: bytes,
) -> Result[None, EffectError]:
    marker = canonical_json(
        {
            "transaction_id": identity.transaction_id,
            "operation_index": identity.operation_index,
            "role": identity.role.value,
            "token": token.hex(),
        }
    )
    return _write_file_exclusive(stage_dir, os.fsencode(_MARKER_NAME), marker, 0o600)


def _read_stage_marker(
    stage_dir: bytes,
) -> Result[tuple[str, int, str, str] | None, EffectError]:
    try:
        with open(os.path.join(stage_dir, os.fsencode(_MARKER_NAME)), "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return Ok(None)
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.READ_BACKUP, sanitize_errno(error)
            )
        )
    try:
        value = decode_json(raw)
    except ValueError:
        return _err_effect(_invalid_state("stage marker is not strict JSON"))
    if not isinstance(value, dict):
        return _err_effect(_invalid_state("stage marker is not an object"))
    transaction_id = value.get("transaction_id")
    operation_index = value.get("operation_index")
    role = value.get("role")
    token = value.get("token")
    if (
        not isinstance(transaction_id, str)
        or not isinstance(operation_index, int)
        or not isinstance(role, str)
        or not isinstance(token, str)
    ):
        return _err_effect(_invalid_state("stage marker shape"))
    return Ok((transaction_id, operation_index, role, token))


def _preparation_identity_for(
    compiled: CompiledTransaction,
    operation_index: int,
    role: PreparationRole,
) -> PreparationIdentity | None:
    for identity in compiled.preparations:
        if identity.operation_index == operation_index and identity.role is role:
            return identity
    return None


def _capture_directory_state_from_fd(
    fd: int,
    limits: ResourceLimits,
    root_path: RepoPath,
) -> Result[DirectoryState, ObservationError | CoreInternalFailure]:
    """Capture one directory's exact topology from a held descriptor."""

    entries: list[FileEntry | DirectoryEntry] = []

    def visit(
        dir_fd: int, relative: str
    ) -> Result[None, ObservationError | CoreInternalFailure]:
        match list_directory_entries(dir_fd):
            case Err(error):
                return Err(error)
            case Ok(names):
                pass
        for name in names:
            child_rel = (
                f"{relative}/{os.fsdecode(name)}" if relative else os.fsdecode(name)
            )
            full = f"{root_path.value}/{child_rel}"
            match classify_child(dir_fd, name):
                case Err(error):
                    return Err(error)
                case Ok(entry):
                    pass
            if entry.kind is ChildKind.SYMLINK:
                return Err(
                    ObservationError(
                        ObservationErrorKind.SYMLINK_ENCOUNTERED, child_rel
                    )
                )
            try:
                info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            match parse_path(full):
                case Err(_):
                    return Err(
                        ObservationError(
                            ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                        )
                    )
                case Ok(path):
                    pass
            if entry.kind is ChildKind.DIRECTORY:
                entries.append(DirectoryEntry(path, PosixMode(info.st_mode & 0o7777)))
                try:
                    child_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=dir_fd,
                    )
                except OSError as error:
                    return Err(map_observation_error(error, child_rel))
                try:
                    match visit(child_fd, child_rel):
                        case Err(error):
                            return Err(error)
                        case Ok(_):
                            pass
                finally:
                    os.close(child_fd)
                continue
            if entry.kind is not ChildKind.REGULAR or entry.nlink != 1:
                return Err(
                    ObservationError(
                        ObservationErrorKind.PATH_MISSING,
                        f"{child_rel} is not a regular file",
                    )
                )
            if info.st_size > limits.max_file_bytes:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                    )
                )
            try:
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=dir_fd,
                )
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            try:
                match read_file_bounded(child_fd, limits.max_file_bytes, child_rel):
                    case Err(error):
                        return Err(error)
                    case Ok(content):
                        pass
            finally:
                os.close(child_fd)
            entries.append(FileEntry(path, content, PosixMode(info.st_mode & 0o7777)))
        return Ok(None)

    match visit(fd, ""):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    entries.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    try:
        info = os.fstat(fd)
    except OSError as error:
        return Err(map_observation_error(error, "directory"))
    return Ok(DirectoryState(PosixMode(info.st_mode & 0o7777), tuple(entries)))


def _observe_path_state(
    resources: TransactionResources,
    path: RepoPath,
    *,
    directory: bool,
) -> Result[ObservedPathState, EffectError]:
    """Observe one post-operation path state for the machine's ``OperationApplied``."""

    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        if directory:
            components = tuple(os.fsencode(part) for part in path.value.split("/"))
            opened_new = bool(components)
            match walk_no_follow(root_fd, components, allow_absent_final=True):
                case Err(error):
                    return Err(error)
                case Ok(fd):
                    pass
            if fd is None:
                return Ok(ObservedDirectoryAbsent())
            try:
                try:
                    info = os.fstat(fd)
                except OSError as error:
                    return Err(map_observation_error(error, path.value))
                match _capture_directory_state_from_fd(fd, resources.limits, path):
                    case Err(error):
                        return Err(error)
                    case Ok(state):
                        pass
                return Ok(ObservedDirectoryPresent(state, info.st_dev, info.st_ino))
            finally:
                if opened_new:
                    os.close(fd)
        match _read_file_state_at(root_fd, path, resources.limits):
            case Err(error):
                return _err_effect(error)
            case Ok(None):
                return Ok(ObservedFileAbsent())
            case Ok(observed):
                if observed is None:
                    return Ok(ObservedFileAbsent())
                content, mode, device, inode = observed
        return Ok(
            ObservedFilePresent(_observed_identity(content, mode), mode, device, inode)
        )
    finally:
        os.close(root_fd)


def capture_plan_snapshot(
    resources: TransactionResources, plan: OperationPlan
) -> Result[
    TargetSnapshot,
    ObservationError | CoreInternalFailure | TransactionError,
]:
    """Capture exactly the plan's referenced paths from the live target."""

    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        file_paths, dir_paths = plan_snapshot_paths(plan)
        observed_files: list[ObservedFileEntry] = []
        for path in sorted(file_paths, key=lambda p: p.value.encode("utf-8")):
            match _read_file_state_at(root_fd, path, resources.limits):
                case Err(error):
                    return Err(error)
                case Ok(None):
                    continue
                case Ok(observed):
                    if observed is None:
                        continue
                    content, mode, _device, _inode = observed
            identity = _observed_identity(content, mode)
            observed_files.append(
                ObservedFileEntry(path, FileState(identity, mode), content)
            )
        tree_roots = {
            operation.root
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
        }
        observed_dirs: list[ObservedDirectoryEntry] = []
        for path in sorted(dir_paths, key=lambda p: p.value.encode("utf-8")):
            components = tuple(os.fsencode(part) for part in path.value.split("/"))
            match walk_no_follow(root_fd, components, allow_absent_final=True):
                case Err(error):
                    return Err(error)
                case Ok(fd):
                    pass
            if fd is None:
                continue
            try:
                info = os.fstat(fd)
                if not stat.S_ISDIR(info.st_mode):
                    continue
                if path in tree_roots:
                    match _capture_directory_state_from_fd(fd, resources.limits, path):
                        case Err(error):
                            return Err(error)
                        case Ok(state):
                            pass
                else:
                    state = DirectoryState(PosixMode(info.st_mode & 0o7777), ())
            finally:
                os.close(fd)
            observed_dirs.append(ObservedDirectoryEntry(path, state))
        return Ok(TargetSnapshot(tuple(observed_files), tuple(observed_dirs)))
    finally:
        os.close(root_fd)


def _execute_prepare_one(
    identity: PreparationIdentity,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> Result[None, EffectError]:
    plan = compiled.plan
    operation = plan.ordered_operations[identity.operation_index]
    token = resources.ownership_tokens[compiled.preparations.index(identity)]
    match identity.role:
        case PreparationRole.STAGE:
            if isinstance(operation, (CreateFileOperation, ReplaceFileOperation)):
                content = plan.blob_store.get(operation.planned_new.content_id)
                if content is None:
                    return _err_effect(_invalid_state("stage blob is missing"))
                match _mkdir_stage_dir(
                    resources,
                    operation,
                    compiled.transaction_id,
                    identity.operation_index,
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(stage_dir):
                        pass
                match _write_stage_marker(stage_dir, identity=identity, token=token):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                match _write_file_exclusive(
                    stage_dir,
                    os.fsencode(_PAYLOAD_NAME),
                    content,
                    identity.expected_mode.value,
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                return _fsync_dir_abs(stage_dir)
            if isinstance(operation, CreateTreeOperation):
                match _mkdir_stage_dir(
                    resources,
                    operation,
                    compiled.transaction_id,
                    identity.operation_index,
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(stage_dir):
                        pass
                match _write_stage_marker(stage_dir, identity=identity, token=token):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                match _mkdir_exclusive(stage_dir, os.fsencode(_PAYLOAD_NAME), 0o755):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                payload = os.path.join(stage_dir, os.fsencode(_PAYLOAD_NAME))
                for entry in operation.planned_new.entries:
                    relative = entry.path.value[len(operation.root.value) + 1 :]
                    parts = relative.split("/")
                    parent = payload
                    for component in parts[:-1]:
                        parent = os.path.join(parent, os.fsencode(component))
                        try:
                            os.mkdir(parent, 0o755)
                        except FileExistsError:
                            pass
                        except OSError as error:
                            return Err(
                                TransactionError.primitive_failed(
                                    TransactionPrimitive.CREATE_DIRECTORY,
                                    sanitize_errno(error),
                                    os.fsdecode(parent),
                                )
                            )
                        try:
                            # mkdir modes are umask-masked; tree directories
                            # keep their planned mode exactly.
                            os.chmod(parent, 0o755, follow_symlinks=False)
                        except OSError as error:
                            return Err(
                                TransactionError.primitive_failed(
                                    TransactionPrimitive.CREATE_DIRECTORY,
                                    sanitize_errno(error),
                                    os.fsdecode(parent),
                                )
                            )
                    match entry:
                        case PlannedFileEntry(
                            path=entry_path, mode=mode, content_id=content_id
                        ):
                            content = plan.blob_store.get(content_id)
                            if content is None:
                                return Err(
                                    _invalid_state(
                                        f"stage blob is missing: {entry_path.value}"
                                    )
                                )
                            match _write_file_exclusive(
                                parent,
                                os.fsencode(parts[-1]),
                                content,
                                mode.value,
                            ):
                                case Err(error):
                                    return _err_effect(error)
                                case Ok(_):
                                    pass
                        case PlannedDirectoryEntry(path=dir_path, mode=mode):
                            dir_relative = dir_path.value[
                                len(operation.root.value) + 1 :
                            ]
                            target = os.path.join(
                                payload,
                                *(
                                    os.fsencode(part)
                                    for part in dir_relative.split("/")
                                ),
                            )
                            try:
                                os.mkdir(target, mode.value)
                            except FileExistsError:
                                pass
                            except OSError as error:
                                return Err(
                                    TransactionError.primitive_failed(
                                        TransactionPrimitive.CREATE_DIRECTORY,
                                        sanitize_errno(error),
                                        dir_path.value,
                                    )
                                )
                            try:
                                os.chmod(target, mode.value, follow_symlinks=False)
                            except OSError as error:
                                return Err(
                                    TransactionError.primitive_failed(
                                        TransactionPrimitive.CREATE_DIRECTORY,
                                        sanitize_errno(error),
                                        dir_path.value,
                                    )
                                )
                return _fsync_dir_abs(payload)
            return _err_effect(
                _invalid_state("file stage requires a file or tree operation")
            )
        case PreparationRole.BACKUP:
            if not isinstance(operation, (ReplaceFileOperation, DeleteFileOperation)):
                return _err_effect(
                    _invalid_state("backup requires a replace or delete operation")
                )
            root_fd = os.open(
                resources.worktree.root_abs,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                match _read_file_state_at(root_fd, operation.path, resources.limits):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(None):
                        return _err_effect(_precondition_changed(operation.path.value))
                    case Ok(observed):
                        if observed is None:
                            return _err_effect(
                                _precondition_changed(operation.path.value)
                            )
                        content, mode, _device, _inode = observed
            finally:
                os.close(root_fd)
            expected = operation.expected_old
            if (
                expected.identity is None
                or expected.mode is None
                or sha256_hex(content) != expected.identity.raw_sha256
                or mode != expected.mode
            ):
                return _err_effect(_precondition_changed(operation.path.value))
            state_root = resources.worktree.state_root_abs
            match _ensure_directory_chain(
                state_root,
                (
                    b"transactions",
                    os.fsencode(identity.transaction_id),
                    b"backups",
                ),
            ):
                case Err(error):
                    return _err_effect(error)
                case Ok(_):
                    pass
            backups = os.path.join(
                state_root,
                os.fsencode(f"transactions/{identity.transaction_id}/backups"),
            )
            match _write_file_exclusive(
                backups,
                os.fsencode(str(identity.operation_index)),
                content,
                mode.value,
            ):
                case Err(error):
                    return _err_effect(error)
                case Ok(_):
                    pass
            return _fsync_dir_abs(backups)
        case PreparationRole.ROLLBACK:
            return _err_effect(
                _invalid_state("rollback containers are created during rollback")
            )
    return _err_effect(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        _invalid_state("unknown preparation role")
    )


def _verify_old_file(
    operation: FileOperation,
    resources: TransactionResources,
) -> Result[None, EffectError]:
    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        match _read_file_state_at(root_fd, operation.path, resources.limits):
            case Err(error):
                return _err_effect(error)
            case Ok(observed):
                pass
    finally:
        os.close(root_fd)
    expected = operation.expected_old
    if isinstance(operation, CreateFileOperation):
        if observed is not None:
            return _err_effect(_precondition_changed(operation.path.value))
        return Ok(None)
    if observed is None:
        return _err_effect(_precondition_changed(operation.path.value))
    content, mode, _device, _inode = observed
    if (
        expected.identity is None
        or expected.mode is None
        or sha256_hex(content) != expected.identity.raw_sha256
        or mode != expected.mode
    ):
        return _err_effect(_precondition_changed(operation.path.value))
    return Ok(None)


def _execute_apply_one(
    operation: FileOperation | DirectoryOperation,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> Result[ObservedPathState, EffectError]:
    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        match operation:
            case CreateFileOperation() | ReplaceFileOperation():
                match _open_parent(root_fd, operation.path):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(parent_fd):
                        pass
                try:
                    match _verify_old_file(operation, resources):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(_):
                            pass
                    stage_dir = _stage_dir_for(
                        resources,
                        operation,
                        compiled.transaction_id,
                        compiled.plan.ordered_operations.index(operation),
                    )
                    match _open_directory_abs(stage_dir):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(stage_fd):
                            pass
                    try:
                        try:
                            os.rename(
                                os.fsencode(_PAYLOAD_NAME),
                                _leaf_name(operation.path),
                                src_dir_fd=stage_fd,
                                dst_dir_fd=parent_fd,
                            )
                        except OSError as error:
                            return Err(
                                TransactionError.primitive_failed(
                                    TransactionPrimitive.REPLACE_PATH,
                                    sanitize_errno(error),
                                    operation.path.value,
                                )
                            )
                    finally:
                        os.close(stage_fd)
                finally:
                    os.close(parent_fd)
                match _fsync_dir_abs(
                    os.path.join(
                        resources.worktree.root_abs,
                        *(_parent_components(operation.path)),
                    )
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                return _observe_path_state(resources, operation.path, directory=False)
            case DeleteFileOperation():
                match _open_parent(root_fd, operation.path):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(parent_fd):
                        pass
                try:
                    match _verify_old_file(operation, resources):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(_):
                            pass
                    try:
                        os.unlink(_leaf_name(operation.path), dir_fd=parent_fd)
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.REMOVE_FILE,
                                sanitize_errno(error),
                                operation.path.value,
                            )
                        )
                finally:
                    os.close(parent_fd)
                match _fsync_dir_abs(
                    os.path.join(
                        resources.worktree.root_abs,
                        *(_parent_components(operation.path)),
                    )
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                return _observe_path_state(resources, operation.path, directory=False)
            case CreateTreeOperation():
                match _open_parent(root_fd, operation.root):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(parent_fd):
                        pass
                try:
                    match classify_child(parent_fd, _leaf_name(operation.root)):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(ChildEntry(kind=ChildKind.ABSENT)):
                            pass
                        case Ok(_):
                            return _err_effect(
                                _precondition_changed(operation.root.value)
                            )
                    stage_dir = _stage_dir_for(
                        resources,
                        operation,
                        compiled.transaction_id,
                        compiled.plan.ordered_operations.index(operation),
                    )
                    match _open_directory_abs(stage_dir):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(stage_fd):
                            pass
                    try:
                        try:
                            os.rename(
                                os.fsencode(_PAYLOAD_NAME),
                                _leaf_name(operation.root),
                                src_dir_fd=stage_fd,
                                dst_dir_fd=parent_fd,
                            )
                        except OSError as error:
                            return Err(
                                TransactionError.primitive_failed(
                                    TransactionPrimitive.REPLACE_PATH,
                                    sanitize_errno(error),
                                    operation.root.value,
                                )
                            )
                    finally:
                        os.close(stage_fd)
                finally:
                    os.close(parent_fd)
                return _observe_path_state(resources, operation.root, directory=True)
            case RemoveEmptyDirectoryOperation():
                match _open_parent(root_fd, operation.path):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(parent_fd):
                        pass
                try:
                    match classify_child(parent_fd, _leaf_name(operation.path)):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(ChildEntry(kind=ChildKind.DIRECTORY)):
                            pass
                        case Ok(_):
                            return _err_effect(
                                _precondition_changed(operation.path.value)
                            )
                    try:
                        info = os.stat(
                            _leaf_name(operation.path),
                            dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except OSError as error:
                        return _err_effect(
                            map_observation_error(error, operation.path.value)
                        )
                    if (
                        PosixMode(info.st_mode & 0o7777)
                        != operation.expected_old.root_mode
                    ):
                        return _err_effect(_precondition_changed(operation.path.value))
                    try:
                        child_fd = os.open(
                            _leaf_name(operation.path),
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=parent_fd,
                        )
                    except OSError as error:
                        return _err_effect(
                            map_observation_error(error, operation.path.value)
                        )
                    try:
                        match list_directory_entries(child_fd):
                            case Err(error):
                                return _err_effect(error)
                            case Ok(names):
                                pass
                    finally:
                        os.close(child_fd)
                    if names:
                        return _err_effect(_precondition_changed(operation.path.value))
                    try:
                        os.rmdir(_leaf_name(operation.path), dir_fd=parent_fd)
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.REMOVE_DIRECTORY,
                                sanitize_errno(error),
                                operation.path.value,
                            )
                        )
                finally:
                    os.close(parent_fd)
                match _fsync_dir_abs(
                    os.path.join(
                        resources.worktree.root_abs,
                        *(_parent_components(operation.path)),
                    )
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                return _observe_path_state(resources, operation.path, directory=True)
    finally:
        os.close(root_fd)
    return _err_effect(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        _invalid_state("unknown operation")
    )


def _ensure_rollback_allocations(
    compiled: CompiledTransaction, resources: TransactionResources
) -> None:
    if resources.rollback_preparations:
        return
    specs = derive_rollback_specs(compiled.plan)
    resources.rollback_tokens = tuple(new_ownership_token() for _ in specs)
    resources.rollback_preparations = derive_rollback_preparations(
        compiled.plan, compiled.transaction_id, resources.rollback_tokens
    )


def _rollback_spec_index(compiled: CompiledTransaction, operation_index: int) -> int:
    for index, spec in enumerate(derive_rollback_specs(compiled.plan)):
        if spec.operation_index == operation_index:
            return index
    return -1


def _execute_rollback_file(
    operation: FileOperation,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> Result[
    RollbackAlreadyRestored | RollbackRestoredNow, EffectError | TransitionError
]:

    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        match _read_file_state_at(root_fd, operation.path, resources.limits):
            case Err(error):
                return _rollback_error(error)
            case Ok(observed):
                pass
    finally:
        os.close(root_fd)
    current = (
        FileState(None, None)
        if observed is None
        else FileState(
            content_identity(observed[0], text=_is_utf8(observed[0])), observed[1]
        )
    )
    match rollback_file_step(operation.expected_old, operation.planned_new, current):
        case AlreadyRestored():
            return Ok(RollbackAlreadyRestored())
        case RestoreOldFile():
            pass
        case RollbackThirdState():
            return Err(
                TransitionError(
                    TransitionErrorKind.RECOVERY_THIRD_STATE, operation.path.value
                )
            )
    if isinstance(operation, CreateFileOperation):
        root_fd = os.open(
            resources.worktree.root_abs,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            match _open_parent(root_fd, operation.path):
                case Err(error):
                    return _rollback_error(error)
                case Ok(parent_fd):
                    pass
            try:
                try:
                    os.unlink(_leaf_name(operation.path), dir_fd=parent_fd)
                except OSError as error:
                    return Err(
                        TransactionError.primitive_failed(
                            TransactionPrimitive.REMOVE_FILE,
                            sanitize_errno(error),
                            operation.path.value,
                        )
                    )
            finally:
                os.close(parent_fd)
        finally:
            os.close(root_fd)
        return Ok(RollbackRestoredNow())
    # Replace/Delete: restore the verified raw backup through a marked adjacent
    # rollback container so the final rename is atomic on the same filesystem.
    identity = _preparation_identity_for(
        compiled,
        compiled.plan.ordered_operations.index(operation),
        PreparationRole.BACKUP,
    )
    if identity is None:
        return _rollback_error(_invalid_state("restore backup identity is missing"))
    backups = os.path.join(
        resources.worktree.state_root_abs,
        os.fsencode(f"transactions/{compiled.transaction_id}/backups"),
    )
    backup_path = os.path.join(backups, os.fsencode(str(identity.operation_index)))
    try:
        with open(backup_path, "rb") as handle:
            backup_bytes = handle.read()
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.READ_BACKUP, sanitize_errno(error)
            )
        )
    try:
        backup_mode = PosixMode(
            os.stat(backup_path, follow_symlinks=False).st_mode & 0o7777
        )
    except OSError as error:
        return _rollback_error(map_observation_error(error, "backup"))
    if (
        sha256_hex(backup_bytes) != identity.expected_raw_sha256
        or backup_mode != identity.expected_mode
    ):
        return _rollback_error(
            _invalid_state("restore backup does not match its identity")
        )
    _ensure_rollback_allocations(compiled, resources)
    spec_index = _rollback_spec_index(
        compiled, compiled.plan.ordered_operations.index(operation)
    )
    if spec_index < 0 or spec_index >= len(resources.rollback_preparations):
        return _rollback_error(_invalid_state("rollback container identity is missing"))
    rollback_identity = resources.rollback_preparations[spec_index]
    match _mkdir_stage_dir(
        resources,
        operation,
        compiled.transaction_id,
        compiled.plan.ordered_operations.index(operation),
        rollback=True,
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(container):
            pass
    match _write_stage_marker(
        container,
        identity=rollback_identity,
        token=resources.rollback_tokens[spec_index],
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(_):
            pass
    match _write_file_exclusive(
        container, os.fsencode(_PAYLOAD_NAME), backup_bytes, backup_mode.value
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(_):
            pass
    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        match _open_parent(root_fd, operation.path):
            case Err(error):
                return _rollback_error(error)
            case Ok(parent_fd):
                pass
        try:
            match _open_directory_abs(container):
                case Err(error):
                    return _rollback_error(error)
                case Ok(container_fd):
                    pass
            try:
                try:
                    os.rename(
                        os.fsencode(_PAYLOAD_NAME),
                        _leaf_name(operation.path),
                        src_dir_fd=container_fd,
                        dst_dir_fd=parent_fd,
                    )
                except OSError as error:
                    return Err(
                        TransactionError.primitive_failed(
                            TransactionPrimitive.REPLACE_PATH,
                            sanitize_errno(error),
                            operation.path.value,
                        )
                    )
            finally:
                os.close(container_fd)
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)
    return Ok(RollbackRestoredNow())


def _execute_rollback_directory(
    operation: CreateTreeOperation | RemoveEmptyDirectoryOperation,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> Result[
    RollbackAlreadyRestored | RollbackRestoredNow, EffectError | TransitionError
]:
    path = (
        operation.root if isinstance(operation, CreateTreeOperation) else operation.path
    )
    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        components = tuple(os.fsencode(part) for part in path.value.split("/"))
        match walk_no_follow(root_fd, components, allow_absent_final=True):
            case Err(error):
                return _rollback_error(error)
            case Ok(fd):
                pass
        current: DirectoryState | None = None
        if fd is not None:
            try:
                match _capture_directory_state_from_fd(fd, resources.limits, path):
                    case Err(error):
                        return _rollback_error(error)
                    case Ok(state):
                        current = state
            finally:
                os.close(fd)
    finally:
        os.close(root_fd)
    match rollback_directory_step(operation, current):
        case AlreadyRestored():
            return Ok(RollbackAlreadyRestored())
        case RemoveCreatedTreeAtomically():
            pass
        case RestoreEmptyDirectoryAtomically():
            pass
        case RollbackThirdState():
            return Err(
                TransitionError(TransitionErrorKind.RECOVERY_THIRD_STATE, path.value)
            )
    _ensure_rollback_allocations(compiled, resources)
    index = compiled.plan.ordered_operations.index(operation)
    spec_index = _rollback_spec_index(compiled, index)
    if spec_index < 0 or spec_index >= len(resources.rollback_preparations):
        return _rollback_error(_invalid_state("rollback container identity is missing"))
    rollback_identity = resources.rollback_preparations[spec_index]
    match _mkdir_stage_dir(
        resources, operation, compiled.transaction_id, index, rollback=True
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(container):
            pass
    match _write_stage_marker(
        container,
        identity=rollback_identity,
        token=resources.rollback_tokens[spec_index],
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(_):
            pass
    root_fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        match _open_parent(root_fd, path):
            case Err(error):
                return _rollback_error(error)
            case Ok(parent_fd):
                pass
        try:
            match _open_directory_abs(container):
                case Err(error):
                    return _rollback_error(error)
                case Ok(container_fd):
                    pass
            try:
                if isinstance(operation, CreateTreeOperation):
                    try:
                        os.rename(
                            _leaf_name(path),
                            os.fsencode(_PAYLOAD_NAME),
                            src_dir_fd=parent_fd,
                            dst_dir_fd=container_fd,
                        )
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.REPLACE_PATH,
                                sanitize_errno(error),
                                path.value,
                            )
                        )
                else:
                    try:
                        os.mkdir(
                            os.fsencode(_PAYLOAD_NAME),
                            operation.expected_old.root_mode.value,
                            dir_fd=container_fd,
                        )
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.CREATE_DIRECTORY,
                                sanitize_errno(error),
                                path.value,
                            )
                        )
                    try:
                        # mkdir modes are umask-masked; the restored directory
                        # keeps its recorded mode exactly.
                        os.chmod(
                            os.fsencode(_PAYLOAD_NAME),
                            operation.expected_old.root_mode.value,
                            dir_fd=container_fd,
                            follow_symlinks=False,
                        )
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.CREATE_DIRECTORY,
                                sanitize_errno(error),
                                path.value,
                            )
                        )
                    try:
                        os.rename(
                            os.fsencode(_PAYLOAD_NAME),
                            _leaf_name(path),
                            src_dir_fd=container_fd,
                            dst_dir_fd=parent_fd,
                        )
                    except OSError as error:
                        return Err(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.REPLACE_PATH,
                                sanitize_errno(error),
                                path.value,
                            )
                        )
            finally:
                os.close(container_fd)
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)
    return Ok(RollbackRestoredNow())


def _execute_rollback_one(
    compiled: CompiledTransaction,
    operation_index: int,
    resources: TransactionResources,
) -> Result[
    RollbackAlreadyRestored | RollbackRestoredNow, EffectError | TransitionError
]:
    operation = compiled.plan.ordered_operations[operation_index]
    match operation:
        case CreateFileOperation() | ReplaceFileOperation() | DeleteFileOperation():
            return _execute_rollback_file(operation, compiled, resources)
        case CreateTreeOperation() | RemoveEmptyDirectoryOperation():
            return _execute_rollback_directory(operation, compiled, resources)
    return _rollback_error(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        _invalid_state("unknown operation")
    )


def _artifact_observation(
    path: bytes, *, directory: bool
) -> Result[ObservedArtifact | None, EffectError]:
    """Observe one preparation artifact's kind, raw digest, and mode; absent is ``None``."""

    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return Ok(None)
    except OSError as error:
        return _err_effect(map_observation_error(error, os.fsdecode(path)))
    mode = PosixMode(info.st_mode & 0o7777)
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            return _err_effect(_invalid_state(os.fsdecode(path)))
        return Ok(ObservedArtifact("directory", None, mode))
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return _err_effect(_invalid_state(os.fsdecode(path)))
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError as error:
        return _err_effect(map_observation_error(error, os.fsdecode(path)))
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return _err_effect(_invalid_state(os.fsdecode(path)))
    return Ok(ObservedArtifact("file", sha256_hex(content), mode))


def _remove_artifact(path: bytes, *, directory: bool) -> Result[None, EffectError]:
    try:
        if directory:
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.REMOVE_FILE
                if not directory
                else TransactionPrimitive.REMOVE_DIRECTORY,
                sanitize_errno(error),
                os.fsdecode(path),
            )
        )
    return Ok(None)


def _marker_matches_identity(
    marker: tuple[str, int, str, str], identity: PreparationIdentity
) -> bool:
    transaction_id, operation_index, role, token_hex = marker
    try:
        token_hash = sha256_hex(bytes.fromhex(token_hex))
    except ValueError:
        return False
    return (
        transaction_id == identity.transaction_id
        and operation_index == identity.operation_index
        and role == identity.role.value
        and token_hash == identity.ownership_token_sha256
    )


def _execute_clean_one(
    compiled: CompiledTransaction,
    phase: JournalPhase,
    cursor: int,
    resources: TransactionResources,
) -> Result[None, EffectError]:
    from scripts.bootstrap.transaction import CleanupKind, derive_cleanup

    plan = compiled.plan
    items = derive_cleanup(plan, phase)
    item = items[cursor]
    match item.kind:
        case CleanupKind.STAGE | CleanupKind.ROLLBACK:
            operation_index = item.operation_index
            if operation_index is None:
                return _err_effect(
                    _invalid_state("cleanup item requires an operation index")
                )
            operation = plan.ordered_operations[operation_index]
            rollback = item.kind is CleanupKind.ROLLBACK
            if rollback:
                spec_index = _rollback_spec_index(compiled, operation_index)
                identity = (
                    resources.rollback_preparations[spec_index]
                    if 0 <= spec_index < len(resources.rollback_preparations)
                    else None
                )
                if identity is None:
                    return _err_effect(
                        _invalid_state("rollback cleanup identity is missing")
                    )
            else:
                identity = _preparation_identity_for(
                    compiled, operation_index, PreparationRole.STAGE
                )
                if identity is None:
                    return _err_effect(
                        _invalid_state("stage cleanup identity is missing")
                    )
            stage_dir = _stage_dir_for(
                resources,
                operation,
                compiled.transaction_id,
                operation_index,
                rollback=rollback,
            )
            match _read_stage_marker(stage_dir):
                case Err(error):
                    return _err_effect(error)
                case Ok(None):
                    return Ok(None)  # already clean: a missing stage is idempotent
                case Ok(marker):
                    pass
            assert marker is not None
            if not _marker_matches_identity(marker, identity):
                return _err_effect(_invalid_state(os.fsdecode(stage_dir)))
            payload = os.path.join(stage_dir, os.fsencode(_PAYLOAD_NAME))
            match _artifact_observation(
                payload, directory=identity.expected_kind == "directory"
            ):
                case Err(error):
                    return _err_effect(error)
                case Ok(observed):
                    pass
            match cleanup_step(identity, observed):
                case CleanupMissing():
                    # The payload was consumed by apply/rollback; only the
                    # marked stage directory remains and must go too.
                    pass
                case CleanupVerified():
                    match _remove_artifact(
                        payload, directory=identity.expected_kind == "directory"
                    ):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(_):
                            pass
                case CleanupThirdState():
                    return _err_effect(_invalid_state(os.fsdecode(payload)))
            match _remove_artifact(stage_dir, directory=True):
                case Err(error):
                    return _err_effect(error)
                case Ok(_):
                    pass
            # Prune the now-empty transaction directory and stage root so a
            # completed transaction leaves no stage litter behind.  Only empty
            # directories are removed; markerless crash evidence is preserved.
            stage_root = os.path.dirname(os.path.dirname(stage_dir))
            for directory in (
                os.path.join(stage_root, os.fsencode(compiled.transaction_id)),
                stage_root,
            ):
                with contextlib.suppress(OSError):
                    os.rmdir(directory)
            return Ok(None)
        case CleanupKind.BACKUP:
            operation_index = item.operation_index
            if operation_index is None:
                return _err_effect(
                    _invalid_state("cleanup item requires an operation index")
                )
            identity = _preparation_identity_for(
                compiled, operation_index, PreparationRole.BACKUP
            )
            if identity is None:
                return _err_effect(_invalid_state("backup cleanup identity is missing"))
            backup = os.path.join(
                resources.worktree.state_root_abs,
                os.fsencode(
                    f"transactions/{compiled.transaction_id}/backups/{operation_index}"
                ),
            )
            match _artifact_observation(backup, directory=False):
                case Err(error):
                    return _err_effect(error)
                case Ok(observed):
                    pass
            match cleanup_step(identity, observed):
                case CleanupMissing():
                    return Ok(None)
                case CleanupVerified():
                    pass
                case CleanupThirdState():
                    return _err_effect(_invalid_state(os.fsdecode(backup)))
            return _remove_artifact(backup, directory=False)
        case CleanupKind.TRANSACTION_DIRECTORY:
            tx_dir = os.path.join(
                resources.worktree.state_root_abs,
                os.fsencode(f"transactions/{compiled.transaction_id}"),
            )
            backups = os.path.join(tx_dir, b"backups")
            try:
                if os.path.isdir(backups) and not os.listdir(backups):
                    os.rmdir(backups)
                if os.path.isdir(tx_dir) and not os.listdir(tx_dir):
                    os.rmdir(tx_dir)
                transactions = os.path.join(
                    resources.worktree.state_root_abs, b"transactions"
                )
                if os.path.isdir(transactions) and not os.listdir(transactions):
                    os.rmdir(transactions)
            except OSError as error:
                return Err(
                    TransactionError.primitive_failed(
                        TransactionPrimitive.REMOVE_DIRECTORY,
                        sanitize_errno(error),
                        os.fsdecode(tx_dir),
                    )
                )
            return Ok(None)
        case CleanupKind.JOURNAL:
            fd = resources.state_root_fd
            if fd is None:
                return _err_effect(_invalid_state("state root is not open"))
            match classify_child(fd, b"journal.json"):
                case Err(error):
                    return _err_effect(error)
                case Ok(ChildEntry(kind=ChildKind.ABSENT)):
                    return Ok(None)
                case Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=1)):
                    pass
                case Ok(_):
                    return _err_effect(_invalid_state("journal.json"))
            try:
                os.unlink("journal.json", dir_fd=fd)
            except OSError as error:
                return Err(
                    TransactionError.primitive_failed(
                        TransactionPrimitive.REMOVE_FILE,
                        sanitize_errno(error),
                        "journal.json",
                    )
                )
            match fsync_directory(fd):
                case Err(error):
                    return _err_effect(error)
                case Ok(_):
                    return Ok(None)
    return _err_effect(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        _invalid_state("unknown cleanup kind")
    )


def _envelope_for_continuation(
    continuation: TransactionMachineState,
    _phase: JournalPhase,
    resources: TransactionResources,
) -> JournalEnvelope:
    match continuation:
        case NeedPlannedJournal(validated=validated):
            return planned_envelope(PlannedTransaction(validated))
        case NeedMutatingJournal(planned=planned):
            return mutating_envelope(planned)
        case NeedRestoredJournal(verified=verified):
            return restored_envelope(verified, resources.rollback_preparations)
        case NeedSealedJournal(gated=gated):
            return sealed_envelope(gated)
        case _:
            raise TypeError("journal persistence requires a journal continuation state")


def _execute_effect(
    request: EffectRequest,
    continuation: TransactionMachineState,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> EffectObservation:
    """Execute one closed effect request; every OS result becomes an observation."""

    plan = compiled.plan
    try:
        match request:
            case AcquireLock():
                state_root_abs = resources.worktree.state_root_abs
                if resources.state_root_fd is None:
                    match _open_directory_abs(state_root_abs):
                        case Ok(fd):
                            resources.state_root_fd = fd
                        case Err(_):
                            pass
                if resources.state_root_fd is None:
                    parent_components = tuple(
                        part for part in state_root_abs.split(b"/") if part
                    )[:-1]
                    parent = b"/" + b"/".join(parent_components)
                    match _ensure_directory_chain(parent, (b"agentic-template",)):
                        case Err(error):
                            return EffectFailed(EffectRequestKind.ACQUIRE_LOCK, error)
                        case Ok(_):
                            pass
                    match _open_directory_abs(state_root_abs):
                        case Err(error):
                            return EffectFailed(EffectRequestKind.ACQUIRE_LOCK, error)
                        case Ok(fd):
                            resources.state_root_fd = fd
                match acquire_lock(
                    resources.state_root_fd,
                    operation=plan.operation_kind,
                    target_digest=plan.target_identity.digest,
                ):
                    case Ok(guard):
                        resources.lock = guard
                        return LockAcquired()
                    case Err(
                        TransitionError(kind=TransitionErrorKind.LOCK_HELD) as held
                    ):
                        return LockRefused(held)
                    case Err(TransitionError() as error):
                        return EffectFailed(
                            EffectRequestKind.ACQUIRE_LOCK,
                            TransactionError(
                                TransactionErrorKind.INVALID_STATE_ROOT,
                                subject="lock acquisition failed",
                            ),
                        )
                    case Err(error):
                        if isinstance(error, TransitionError):
                            return EffectFailed(
                                EffectRequestKind.ACQUIRE_LOCK,
                                TransactionError(
                                    TransactionErrorKind.INVALID_STATE_ROOT,
                                    subject="lock acquisition failed",
                                ),
                            )
                        return EffectFailed(EffectRequestKind.ACQUIRE_LOCK, error)
            case ObserveAgain():
                match capture_plan_snapshot(resources, plan):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.OBSERVE_AGAIN, error)
                    case Ok(snapshot):
                        return Reobserved(snapshot)
            case PersistJournal(phase=phase):
                fd = resources.state_root_fd
                if fd is None:
                    return EffectFailed(
                        EffectRequestKind.PERSIST_JOURNAL,
                        _invalid_state("state root is not open"),
                    )
                envelope = _envelope_for_continuation(continuation, phase, resources)
                match persist_journal(fd, envelope):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.PERSIST_JOURNAL, error)
                    case Ok(_):
                        return JournalPersisted(phase)
            case PrepareOne():
                if not isinstance(continuation, Preparing):
                    return EffectFailed(
                        EffectRequestKind.PREPARE_ONE,
                        CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE),
                    )
                identity = compiled.preparations[continuation.cursor.index]
                match _execute_prepare_one(identity, compiled, resources):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.PREPARE_ONE, error)
                    case Ok(_):
                        return PreparationCompleted(identity)
            case ApplyOne():
                if not isinstance(continuation, Installing):
                    return EffectFailed(
                        EffectRequestKind.APPLY_ONE,
                        CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE),
                    )
                index = continuation.cursor.index
                match _execute_apply_one(
                    plan.ordered_operations[index], compiled, resources
                ):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.APPLY_ONE, error)
                    case Ok(state):
                        return OperationApplied(index, state)
            case ObservePostState():
                match capture_plan_snapshot(resources, plan):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.OBSERVE_POST_STATE, error)
                    case Ok(snapshot):
                        return PostStateObserved(snapshot)
            case CleanOne():
                if not isinstance(continuation, (CleaningForward, CleaningRollback)):
                    return EffectFailed(
                        EffectRequestKind.CLEAN_ONE,
                        CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE),
                    )
                phase = (
                    JournalPhase.SEALED
                    if isinstance(continuation, CleaningForward)
                    else JournalPhase.RESTORED
                )
                match _execute_clean_one(
                    compiled, phase, continuation.cursor.index, resources
                ):
                    case Err(error):
                        return EffectFailed(EffectRequestKind.CLEAN_ONE, error)
                    case Ok(_):
                        return CleanupCompleted(continuation.cursor.index)
            case AttemptRollbackOne():
                if not isinstance(continuation, RollingBack):
                    return EffectFailed(
                        EffectRequestKind.ATTEMPT_ROLLBACK_ONE,
                        CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE),
                    )
                index = continuation.cursor.index
                match _execute_rollback_one(compiled, index, resources):
                    case Err(error):
                        if isinstance(error, TransitionError):
                            return EffectFailed(
                                EffectRequestKind.ATTEMPT_ROLLBACK_ONE,
                                TransactionError(
                                    TransactionErrorKind.INVALID_STATE_ROOT,
                                    subject=error.subject,
                                ),
                            )
                        return EffectFailed(
                            EffectRequestKind.ATTEMPT_ROLLBACK_ONE, error
                        )
                    case Ok(result):
                        return RollbackStepCompleted(index, result)
            case ReleaseLock():
                if resources.lock is not None:
                    release_lock(resources.lock)
                    resources.lock = None
                return LockReleased()
        return EffectFailed(  # pragma: no cover  # the closed grammar is exhaustive
            EffectRequestKind.RELEASE_LOCK,
            CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE),
        )
    except OSError as error:
        return EffectFailed(
            request_kind(request),
            ObservationError(
                ObservationErrorKind.UNSUPPORTED_FILESYSTEM, str(error)[:200]
            ),
        )


def run_transaction_machine(
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> TransactionOutcome:
    """Drive the Mealy machine: execute each request and feed the observation back."""

    state: TransactionMachineState = NeedLock(compiled)
    event: TransactionEvent = Start()
    while True:
        step = step_transaction(state, event)
        match step:
            case TransactionTerminal(outcome):
                return outcome
            case TransactionInstruction(request, next_state):
                observation = _execute_effect(request, next_state, compiled, resources)
                state = next_state
                event = ObservedEffect(observation)


def _run_hook(worktree: ResolvedGitWorktree) -> HookEvidence:
    """Attempt the adopter hook once; evidence is bounded and never replayed."""

    hook_abs = os.fsdecode(worktree.root_abs) + "/" + HOOK_PATH.value
    match run_captured(
        [hook_abs],
        cwd=os.fsdecode(worktree.root_abs),
        timeout=_HOOK_TIMEOUT_SECONDS,
        stream_bound=_HOOK_STREAM_BOUND,
    ):
        case LaunchFailed(process_error=process_error):
            return HookLaunchFailed(process_error)
        case TimedOut():
            return HookExited(124)  # the bounded-timeout marker, matching timeout(1)
        case Launched(returncode=returncode, stdout=stdout, stderr=stderr):
            pass
    signal = signalled(returncode)
    if signal is not None:
        return HookSignalled(signal, stdout, stderr)
    return HookExited(returncode, stdout, stderr)


def _not_ready_diagnostics(
    readiness: MechanicalReadinessResult,
) -> tuple[Diagnostic, ...]:
    if not readiness.blocking:
        return ()
    return (
        Diagnostic(
            code="BOOTSTRAP_READINESS_BLOCKING",
            category=DiagnosticCategory.TRANSITION,
            severity=DiagnosticSeverity.WARNING,
            subject="repository readiness",
            summary="bootstrap files were installed; the repository is not locally ready",
            details="replace every remaining placeholder and run the canonical validator",
            next_action=RunCommand(("python3", "scripts/validate_repository.py")),
        ),
    )


def _hook_failure_diagnostics() -> tuple[Diagnostic, ...]:
    return (
        Diagnostic(
            code="BOOTSTRAP_HOOK_FAILED",
            category=DiagnosticCategory.TRANSITION,
            severity=DiagnosticSeverity.ERROR,
            subject="adopter hook",
            summary="bootstrap files were installed; the repository is not locally ready",
            details="the adopter hook did not exit 0",
            next_action=RunCommand(("python3", "scripts/validate_repository.py")),
        ),
    )


def _hook_not_attempted_reason(command: str) -> str:
    return f"not attempted by {command}"


def _already_installed_next_action(system: SystemState) -> RunCommand | None:
    """Name the canonical next action when apply meets a healthy installed project."""

    from scripts.bootstrap.state import (
        CopierExistingProject,
        CopierSourceSame,
        ExistingProject,
        ManagedVerified,
        ProjectAvailable,
        SnapshotExistingProject,
        SnapshotSourceSame,
    )

    match system:
        case ProjectAvailable(observation=ExistingProject(state=existing)):
            match existing:
                case (
                    SnapshotExistingProject(
                        condition=SnapshotSourceSame(managed=ManagedVerified())
                    )
                    | CopierExistingProject(
                        condition=CopierSourceSame(managed=ManagedVerified())
                    )
                ):
                    return RunCommand(("python3", "scripts/validate_repository.py"))
                case _:
                    return None
        case _:
            return None


def _cleanup_mismatch_diagnostic(system: SystemState) -> Diagnostic | None:
    """Name the differing declared paths when a cleanup inventory no longer matches.

    The mutating family keeps the refusal at exit 1 (user-correctable: re-run
    with ``--leave-maintenance-artifacts``), but the diagnostic is the cleanup
    contract kind and names every differing repository-relative path.
    """

    from scripts.bootstrap.state import (
        CleanupContractMismatch,
        ProjectAvailable,
        RecognizedScaffold,
    )

    match system:
        case ProjectAvailable(
            observation=RecognizedScaffold(cleanup=CleanupContractMismatch(paths=paths))
        ):
            return Diagnostic(
                code=(
                    f"BOOTSTRAP_{DiagnosticCategory.CONTRACT.value.upper()}"
                    + "_CLEANUP_CONTRACT_INVALID"
                ),
                category=DiagnosticCategory.CONTRACT,
                severity=DiagnosticSeverity.ERROR,
                subject=",".join(path.value for path in paths),
                summary="Cleanup contract invalid",
                details=(
                    "the maintenance inventory no longer matches the declared "
                    "paths; nothing was deleted"
                ),
                next_action=NoAutomaticAction(
                    "re-run apply with --leave-maintenance-artifacts to retain the declared paths"
                ),
            )
        case _:
            return None


def _execute_mutation(
    parsed: ParsedCommand,
    *,
    template_root: str,
    limits: ResourceLimits,
) -> CommandResult:
    """Execute ``plan apply`` or ``apply``: observe, decide, compile, interpret."""

    command = parsed.command
    # Argument invariants are decided before target observation: an occupied
    # ``--out`` destination is a usage error, never a plan precondition.
    if parsed.out_path is not None and os.path.lexists(parsed.out_path):
        return _result(
            command,
            outcome_for_error(
                UsageError(
                    UsageErrorKind.INVALID_VALUE, "--out destination is occupied"
                )
            ),
        )
    match resolve_shell_target(parsed.target, cwd=os.getcwd()):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok(resolved):
            pass
    match observe_system(
        resolved, coherent=True, template_root=template_root, limits=limits
    ):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok(observation):
            pass
    from scripts.bootstrap.decisions import (
        CompileCandidate,
        InitialInstall,
        RefuseMutation,
        RefusePlan,
        decide_project,
    )

    match decide_project(cast(ProjectIntent, parsed.intent), observation.system):
        case RefusePlan(error=error) | RefuseMutation(error=error):
            mismatch = _cleanup_mismatch_diagnostic(observation.system)
            if mismatch is not None:
                return _result(command, ActionRequired((mismatch,)))
            next_action = _already_installed_next_action(observation.system)
            if next_action is None:
                return _result(command, outcome_for_error(error))
            base = command_error_diagnostic(error)
            return _result(
                command,
                ActionRequired(
                    (
                        Diagnostic(
                            code=base.code,
                            category=base.category,
                            severity=base.severity,
                            subject=base.subject,
                            summary=base.summary,
                            details=(
                                f"{base.details}; inspect with `status` or run the "
                                "canonical validation"
                            ),
                            next_action=next_action,
                        ),
                    )
                ),
            )
        case CompileCandidate() | InitialInstall():
            pass
        case (
            decision
        ):  # pragma: no cover — a new decision variant must never fall through to mutation
            del decision
            return _result(
                command,
                outcome_for_error(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE)),
            )
    assert parsed.bundle_path is not None
    match decode_bundle_input(parsed.bundle_path):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok(decoded):
            pass
    match resolve_bundle(decoded.bundle):
        case Err(failure):
            return _result(
                command,
                outcome_for_error(
                    InputError(
                        InputErrorKind.SCHEMA_VIOLATION,
                        f"{failure.kind.value}:{failure.subject}",
                    )
                ),
            )
        case Ok(resolved_bundle):
            pass
    from scripts.bootstrap.state import (
        ProjectAvailable as _ProjectAvailable,
    )
    from scripts.bootstrap.state import (
        ProtectedTargetAvailable,
    )
    from scripts.bootstrap.state import (
        RecognizedScaffold as _RecognizedScaffold,
    )

    generation: GenerationPath
    cleanup: CleanupContract | None
    match observation.system:
        case _ProjectAvailable(
            worktree=worktree,
            observation=(
                _RecognizedScaffold(
                    generation=recognized_generation,
                    cleanup=cleanup_observation,
                )
            ),
        ):
            generation = recognized_generation
            del worktree
        case _:
            return _result(
                command,
                outcome_for_error(
                    TransitionError(
                        TransitionErrorKind.OPERATION_UNAVAILABLE,
                        "initial install requires a recognized scaffold",
                    )
                ),
            )
    from scripts.bootstrap.state import (
        CleanupContractMismatch,
    )

    match cleanup_observation:
        case CleanupContractValid(contract=contract):
            cleanup = contract
        case CleanupContractMismatch() if parsed.leave_maintenance_artifacts:
            assert observation.pass_ is not None
            match _retained_cleanup_contract(observation.pass_):
                case Err(error):
                    return _result(command, outcome_for_error(error))
                case Ok(contract):
                    cleanup = contract
        case _:
            cleanup = None
    if isinstance(observation.system, ProtectedTargetAvailable):
        return _result(
            command,
            outcome_for_error(
                TransitionError(
                    TransitionErrorKind.UNSUPPORTED_TARGET, "protected target"
                )
            ),
        )
    maintenance: CleanMaintenance | RetainMaintenance = (
        RetainMaintenance(cleanup.cleanup_paths)
        if parsed.leave_maintenance_artifacts and cleanup is not None
        else CleanMaintenance()
    )
    if parsed.leave_maintenance_artifacts and cleanup is None:
        return _result(
            command,
            outcome_for_error(
                ContractError(
                    ContractErrorKind.CLEANUP_CONTRACT_INVALID,
                    "--leave-maintenance-artifacts requires a maintenance inventory",
                )
            ),
        )
    assert observation.pass_ is not None
    worktree = resolved.worktree
    assert worktree is not None
    snapshot_commit: str | None = None
    if generation is GenerationPath.GITHUB:
        match run_git(("rev-parse", "HEAD"), cwd=worktree.root_abs):
            case Ok(result) if result.returncode == 0:
                snapshot_commit = result.stdout.decode("ascii", "replace").strip()
            case _:
                snapshot_commit = None
    scaffold = _scaffold_bytes(template_root)
    match compile_initial_install(
        generation=generation,
        decoded=decoded,
        resolved=resolved_bundle,
        scaffold=scaffold,
        template_root=template_root,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=_snapshot_from_pass(observation.pass_),
        target_identity=observation.pass_.target,
        snapshot_commit=snapshot_commit,
        limits=limits,
    ):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok((plan, readiness)):
            pass
    if command in PLANNING_COMMANDS:
        receipt = build_receipt(plan)
        digest = plan_receipt_digest(receipt)
        changes = tuple(
            Change(
                _operation_change_kind(operation),
                _operation_subject(operation),
                "planned",
            )
            for operation in plan.ordered_operations
        )
        if parsed.out_path is not None:
            match _write_receipt_exclusive(parsed.out_path, receipt):
                case Err(error):
                    return _result(command, outcome_for_error(error))
                case Ok(_):
                    pass
            changes = (
                *changes,
                Change("receipt", parsed.out_path, digest),
            )
        return _result(
            command,
            Succeeded(hook_evidence=NotAttempted(_hook_not_attempted_reason(command))),
            state_document={"kind": "plan_receipt", "receipt": receipt},
            decision_document={"kind": "compile_candidate"},
            changes=changes,
            findings=readiness.blocking,
        )
    # Mutating apply: drive the transaction machine, then attempt the hook once.
    specs = derive_preparation_specs(plan)
    tokens = tuple(new_ownership_token() for _ in specs)
    match apply_plan(_snapshot_from_pass(observation.pass_), plan):
        case Err(error):
            return _result(
                command,
                outcome_for_error(
                    ContractError(
                        ContractErrorKind.INVALID_OPERATION_PLAN, error.subject
                    )
                ),
            )
        case Ok(expected_target):
            pass
    match evaluate_expected(expected_target):
        case ExpectedGatePass(_):
            pass
        case _refusal:
            return _result(
                command,
                outcome_for_error(
                    ContractError(
                        ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                        "expected target fails the template contract",
                    )
                ),
            )
    compiled = CompiledTransaction.compile(
        plan,
        ExpectedGatePass(readiness),
        transaction_id=new_transaction_id(),
        ownership_tokens=tokens,
    )
    resources = TransactionResources(
        worktree=worktree, limits=limits, ownership_tokens=tokens
    )
    outcome = run_transaction_machine(compiled, resources)
    if resources.state_root_fd is not None:
        os.close(resources.state_root_fd)
    match outcome:
        case Stopped(error=error):
            return _result(command, outcome_for_error(error))
        case Completed():
            pass
    hook_evidence = _run_hook(worktree)
    blocking = readiness.blocking
    if (
        not blocking
        and isinstance(hook_evidence, HookExited)
        and hook_evidence.status == 0
    ):
        return _result(
            command,
            Succeeded(hook_evidence=hook_evidence),
            state_document={"kind": "installed"},
            decision_document={"kind": "initial_install"},
            changes=tuple(
                Change(
                    _operation_change_kind(operation),
                    _operation_subject(operation),
                    "installed",
                )
                for operation in plan.ordered_operations
            ),
        )
    diagnostics = (
        *_not_ready_diagnostics(readiness),
        *(
            _hook_failure_diagnostics()
            if not (isinstance(hook_evidence, HookExited) and hook_evidence.status == 0)
            else ()
        ),
    )
    return _result(
        command,
        ActionRequired(diagnostics, hook_evidence=hook_evidence),
        state_document={"kind": "installed_not_ready"},
        decision_document={"kind": "initial_install"},
        changes=tuple(
            Change(
                _operation_change_kind(operation),
                _operation_subject(operation),
                "installed",
            )
            for operation in plan.ordered_operations
        ),
    )


def _snapshot_from_pass(pass_: ProjectObservationPass) -> TargetSnapshot:
    """Overlay the complete observed pass as a full pre-state snapshot."""

    observed_files: list[ObservedFileEntry] = []
    for entry in pass_.files:
        identity = _observed_identity(entry.content, entry.mode)
        observed_files.append(
            ObservedFileEntry(
                entry.path, FileState(identity, entry.mode), entry.content
            )
        )
    observed_dirs: list[ObservedDirectoryEntry] = []
    for entry in pass_.directories:
        observed_dirs.append(
            ObservedDirectoryEntry(entry.path, DirectoryState(entry.mode, ()))
        )
    return TargetSnapshot(tuple(observed_files), tuple(observed_dirs))


def _operation_change_kind(
    operation: FileOperation | DirectoryOperation,
) -> str:
    match operation:
        case CreateFileOperation():
            return "create_file"
        case ReplaceFileOperation():
            return "replace_file"
        case DeleteFileOperation():
            return "delete_file"
        case CreateTreeOperation():
            return "create_tree"
        case RemoveEmptyDirectoryOperation():
            return "remove_empty_directory"
    return "operation"  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _operation_subject(operation: FileOperation | DirectoryOperation) -> str:
    match operation:
        case (
            CreateFileOperation(path=path)
            | ReplaceFileOperation(path=path)
            | DeleteFileOperation(path=path)
        ):
            return path.value
        case CreateTreeOperation(root=root):
            return root.value
        case RemoveEmptyDirectoryOperation(path=path):
            return path.value
    return ""  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _write_receipt_exclusive(
    out_path: str, receipt: PlanReceipt
) -> Result[None, CommandError]:
    """Install the canonical receipt with exclusive sibling staging and no overwrite."""

    absolute = os.path.abspath(out_path)
    parent = os.path.dirname(absolute)
    try:
        fd, temporary = tempfile.mkstemp(prefix=".bootstrap-receipt-", dir=parent)
    except OSError:
        return Err(
            UsageError(
                UsageErrorKind.INVALID_VALUE,
                f"--out destination is not writable: {out_path}",
            )
        )
    try:
        match write_all(fd, encode_receipt(receipt)):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        match fsync_file(fd):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
    finally:
        os.close(fd)
    try:
        os.link(temporary, absolute)
    except FileExistsError:
        os.unlink(temporary)
        return Err(
            UsageError(UsageErrorKind.INVALID_VALUE, "--out destination is occupied")
        )
    except OSError as error:
        os.unlink(temporary)
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.REPLACE_PATH,
                sanitize_errno(error),
                absolute,
            )
        )
    os.unlink(temporary)
    return Ok(None)


def _execute_init(
    parsed: ParsedCommand,
) -> CommandResult:
    """Write a complete reviewable bundle with exclusive sibling staging."""

    assert parsed.bundle_path is not None
    match decode_bundle_input(parsed.bundle_path):
        case Err(error):
            return _result("init", outcome_for_error(error))
        case Ok(decoded):
            pass
    output = parsed.intent
    output_path = cast(InitBundle, output).options.output.value
    absolute = os.path.abspath(output_path)
    if os.path.exists(absolute) and (
        not os.path.isdir(absolute) or os.listdir(absolute)
    ):
        return _result(
            "init",
            outcome_for_error(
                TransitionError(TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED, absolute)
            ),
        )
    parent = os.path.dirname(absolute)
    try:
        stage = tempfile.mkdtemp(prefix=".bootstrap-bundle-", dir=parent)
    except OSError:
        return _result(
            "init",
            outcome_for_error(
                UsageError(
                    UsageErrorKind.INVALID_VALUE,
                    f"--output destination is not writable: {output_path}",
                )
            ),
        )
    try:
        bundle_document = decoded.document
        match _write_file_exclusive(
            os.fsencode(stage),
            os.fsencode(_BUNDLE_FILE),
            canonical_json(bundle_document),
            0o644,
        ):
            case Err(error):
                return _result("init", outcome_for_error(error))
            case Ok(_):
                pass
        written: list[Change] = [Change("file", _BUNDLE_FILE, "bundle document")]
        for path, (content, _kind) in sorted(
            decoded.content.items(), key=lambda item: item[0].value.encode()
        ):
            target_parent = stage
            for component in path.value.split("/")[:-1]:
                target_parent = os.path.join(target_parent, component)
                try:
                    os.mkdir(target_parent, 0o755)
                except FileExistsError:
                    pass
                except OSError as error:
                    return _result(
                        "init",
                        outcome_for_error(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.CREATE_DIRECTORY,
                                sanitize_errno(error),
                                component,
                            )
                        ),
                    )
                try:
                    # mkdir modes are umask-masked; the bundle layout keeps
                    # its deterministic 0755 directories.
                    os.chmod(target_parent, 0o755, follow_symlinks=False)
                except OSError as error:
                    return _result(
                        "init",
                        outcome_for_error(
                            TransactionError.primitive_failed(
                                TransactionPrimitive.CREATE_DIRECTORY,
                                sanitize_errno(error),
                                component,
                            )
                        ),
                    )
            match _write_file_exclusive(
                os.fsencode(target_parent),
                os.fsencode(path.value.split("/")[-1]),
                content,
                0o644,
            ):
                case Err(error):
                    return _result("init", outcome_for_error(error))
                case Ok(_):
                    pass
            written.append(Change("file", path.value, f"{len(content)} bytes"))
        match _fsync_dir_abs(os.fsencode(stage)):
            case Err(error):
                return _result("init", outcome_for_error(error))
            case Ok(_):
                pass
        if os.path.isdir(absolute):
            try:
                os.rmdir(absolute)
            except OSError as error:
                return _result(
                    "init",
                    outcome_for_error(
                        TransactionError.primitive_failed(
                            TransactionPrimitive.REMOVE_DIRECTORY,
                            sanitize_errno(error),
                            absolute,
                        )
                    ),
                )
        try:
            os.rename(stage, absolute)
        except OSError as error:
            return _result(
                "init",
                outcome_for_error(
                    TransactionError.primitive_failed(
                        TransactionPrimitive.REPLACE_PATH,
                        sanitize_errno(error),
                        absolute,
                    )
                ),
            )
        return _result(
            "init",
            Succeeded(hook_evidence=NotAttempted(_hook_not_attempted_reason("init"))),
            state_document={"kind": "bundle_written"},
            decision_document={"kind": "write_bundle"},
            changes=tuple(written),
        )
    finally:
        if os.path.isdir(stage):
            shutil.rmtree(stage, ignore_errors=True)


def _status_changes(
    observation: SystemObservation,
) -> tuple[Change, ...]:
    """Render one deterministic status line per relevant observation fact."""

    from scripts.bootstrap.state import (
        JournalAtDifferentTarget,
        JournalPending,
        ProjectAvailable,
        ProtectedTargetAvailable,
        StalePendingWrite,
        StateRootInvalid,
        TargetUnavailable,
        UnsupportedGitTarget,
        ValidatedJournal,
    )

    changes: list[Change] = []
    system = observation.system
    match system:
        case TargetUnavailable(target=UnsupportedGitTarget(reason=reason)):
            return (Change("target", "unsupported", reason.value),)
        case StalePendingWrite(pending=pending):
            return (Change("pending", "journal.pending", pending.digest),)
        case JournalPending(journal=ValidatedJournal(phase=phase, operation=operation)):
            return (Change("journal", phase.value, f"operation: {operation}"),)
        case JournalAtDifferentTarget(journal=ValidatedJournal(phase=phase)):
            return (Change("journal", "target mismatch", f"phase: {phase.value}"),)
        case StateRootInvalid(evidence=evidence):
            return (Change("state_root", "invalid", str(evidence.__class__.__name__)),)
        case ProtectedTargetAvailable(worktree=_context, observation=project):
            changes.append(
                Change("protected", "canonical template source", "mutation refused")
            )
            return (*changes, *_project_changes(project))
        case ProjectAvailable(worktree=_context, observation=project):
            return _project_changes(project)
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison]
            return (
                Change("state", "unknown", "unclassified system state"),
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _project_changes(project: ProjectObservation) -> tuple[Change, ...]:
    from scripts.bootstrap.state import (
        CleanupContractMismatch,
        CleanupContractValid,
        NoSnapshotCleanup,
        PopulatedManifestFree,
    )
    from scripts.bootstrap.state import (
        ExistingProject as _ExistingProject,
    )
    from scripts.bootstrap.state import (
        RecognizedScaffold as _Scaffold,
    )
    from scripts.bootstrap.state import (
        UnsupportedManifestFree as _UnsupportedManifestFree,
    )

    match project:
        case _Scaffold(generation=generation, cleanup=cleanup, shape=shape):
            changes = [Change("scaffold", generation.value, "uninstalled")]
            match cleanup:
                case CleanupContractValid(contract=contract):
                    changes.append(
                        Change(
                            "cleanup",
                            "valid",
                            f"{len(contract.cleanup_paths)} declared paths",
                        )
                    )
                case CleanupContractMismatch(paths=paths):
                    changes.append(
                        Change(
                            "cleanup",
                            "mismatch",
                            ",".join(path.value for path in paths),
                        )
                    )
                case NoSnapshotCleanup():
                    pass
            if isinstance(shape, PopulatedManifestFree):
                changes.append(
                    Change("shape", "populated", f"{len(shape.entries)} entries")
                )
            else:
                changes.append(Change("shape", "empty", "no project files"))
            return tuple(changes)
        case _UnsupportedManifestFree(shape=shape):
            if isinstance(shape, PopulatedManifestFree):
                return (
                    Change(
                        "unsupported",
                        "populated greenfield",
                        f"{len(shape.entries)} entries",
                    ),
                )
            return (
                Change("unsupported", "empty greenfield", "generate a fresh scaffold"),
            )
        case InvalidManifest(reason=reason):
            return (Change("manifest", "invalid", reason),)
        case _ExistingProject(state=state):
            changes = [Change("project", "installed", "recorded project")]
            match state:
                case SnapshotExistingProject(recorded=recorded, condition=condition):
                    changes.append(
                        Change("generation", "github", recorded.source_fingerprint[:16])
                    )
                    changes.extend(_condition_changes(condition))
                case CopierExistingProject(recorded=recorded, condition=condition):
                    changes.append(
                        Change("generation", "copier", recorded.source_fingerprint[:16])
                    )
                    changes.extend(_condition_changes(condition))
                case _:
                    changes.append(
                        Change("project", "unavailable", "unsafe or incompatible")
                    )
            return tuple(changes)
    return (
        Change("project", "unclassified", "unknown observation"),
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _condition_changes(
    condition: SnapshotCondition | CopierCondition,
) -> tuple[Change, ...]:
    """Render one deterministic change line per relevant source condition."""

    from scripts.bootstrap.state import (
        CopierConflicted,
        CopierSourceChanged,
        CopierSourceSame,
        ManagedDrift,
        ManagedVerified,
        SnapshotSourceChanged,
        SnapshotSourceSame,
        SnapshotSourceUnrecoverable,
    )

    changes: list[Change] = []
    managed: ManagedObservation | None
    match condition:
        case CopierConflicted(delta=delta):
            changes.append(
                Change("copier", "conflict", ",".join(p.value for p in delta.paths))
            )
            managed = None
        case (
            SnapshotSourceChanged(delta=delta, managed=managed)
            | CopierSourceChanged(delta=delta, managed=managed)
        ):
            changes.append(
                Change("source", "changed", ",".join(p.value for p in delta.paths))
            )
        case SnapshotSourceUnrecoverable(delta=delta, managed=managed):
            changes.append(
                Change(
                    "source",
                    "unrecoverable",
                    ",".join(p.value for p in delta.paths),
                )
            )
        case SnapshotSourceSame(managed=managed) | CopierSourceSame(managed=managed):
            changes.append(Change("source", "same", "no source drift"))
    match managed:
        case ManagedDrift(delta=delta):
            changes.append(
                Change("managed", "drift", ",".join(p.value for p in delta.paths))
            )
        case ManagedVerified():
            changes.append(Change("managed", "verified", "no managed drift"))
        case None:
            pass
    return tuple(changes)


def _status_evidence(system: SystemState) -> CommandOutcome | None:
    """Return the exit-2 evidence outcome for unreadable state, else ``None``.

    The inspection family still renders the structured evidence (the status
    changes), but an invalid state root, journal, or manifest exits 2.
    """

    from scripts.bootstrap.state import (
        InvalidManifest as _InvalidManifest,
    )
    from scripts.bootstrap.state import (
        ProjectAvailable as _ProjectAvailable,
    )
    from scripts.bootstrap.state import (
        StateRootInvalid as _StateRootInvalid,
    )

    match system:
        case _StateRootInvalid():
            return RecoveryFailure(
                (
                    command_error_diagnostic(
                        TransactionError(
                            TransactionErrorKind.INVALID_STATE_ROOT,
                            subject="state root evidence",
                        )
                    ),
                )
            )
        case _ProjectAvailable(observation=_InvalidManifest(reason=reason)):
            return ContractFailure(
                (
                    command_error_diagnostic(
                        ContractError(ContractErrorKind.INVALID_MANIFEST, reason)
                    ),
                )
            )
        case _:
            return None


def _execute_status(
    parsed: ParsedCommand,
    *,
    template_root: str,
    limits: ResourceLimits,
) -> CommandResult:
    match resolve_shell_target(parsed.target, cwd=os.getcwd()):
        case Err(error):
            return _result("status", _inspection_outcome(error))
        case Ok(resolved):
            pass
    match observe_system(
        resolved, coherent=False, template_root=template_root, limits=limits
    ):
        case Err(error):
            return _result("status", _inspection_outcome(error))
        case Ok(observation):
            pass
    changes = _status_changes(observation)
    outcome = _status_evidence(observation.system)
    if outcome is None:
        outcome = Succeeded(
            hook_evidence=NotAttempted(
                "adopter hook: not evaluated; run python3 scripts/validate_repository.py"
            ),
        )
    changes = (
        *changes,
        Change(
            "hook",
            "not evaluated",
            "run python3 scripts/validate_repository.py",
        ),
    )
    return _result(
        "status",
        outcome,
        state_document={"kind": "status"},
        decision_document={"kind": "describe_status"},
        changes=changes,
    )


def _inspection_outcome(error: CommandError) -> CommandOutcome:
    """Inspection never returns 1; every hard error is exit 2."""

    outcome = outcome_for_error(error)
    if isinstance(outcome, ActionRequired):
        return RecoveryFailure(outcome.diagnostics)
    return outcome


def _execute_lifecycle_refusal(
    parsed: ParsedCommand,
    *,
    template_root: str,
    limits: ResourceLimits,
) -> CommandResult:
    """Wire add/restore/reconcile through observe+decide; transitions land in T17/T18."""

    command = parsed.command
    match resolve_shell_target(parsed.target, cwd=os.getcwd()):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok(resolved):
            pass
    match observe_system(
        resolved, coherent=True, template_root=template_root, limits=limits
    ):
        case Err(error):
            return _result(command, outcome_for_error(error))
        case Ok(observation):
            pass
    from scripts.bootstrap.decisions import (
        AddCapabilities,
        CompileCandidate,
        ReconcileTemplate,
        RefuseMutation,
        RefusePlan,
        RestoreManaged,
        decide_project,
    )

    match decide_project(cast(ProjectIntent, parsed.intent), observation.system):
        case RefusePlan(error=error) | RefuseMutation(error=error):
            return _result(command, outcome_for_error(error))
        case (
            AddCapabilities()
            | CompileCandidate()
            | RestoreManaged()
            | ReconcileTemplate()
        ):
            pass
        case (
            decision
        ):  # pragma: no cover — a new decision variant must never fall through silently
            del decision
            return _result(
                command,
                outcome_for_error(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE)),
            )
    # The accepted add/restore/reconcile transitions are implemented in T17/T18;
    # until then the typed refusal keeps every other command behavior honest.
    return _result(
        command,
        outcome_for_error(
            TransitionError(
                TransitionErrorKind.OPERATION_UNAVAILABLE,
                f"the {command} transition lands in a later lifecycle task",
            )
        ),
    )


def _execute_recover(
    parsed: ParsedCommand,
    *,
    template_root: str,
    limits: ResourceLimits,
) -> CommandResult:
    """Execute the phase-specific recovery reducer under the canonical lock."""

    command = "recover"
    match resolve_shell_target(parsed.target, cwd=os.getcwd()):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(resolved):
            pass
    match observe_system(
        resolved, coherent=True, template_root=template_root, limits=limits
    ):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(observation):
            pass
    from scripts.bootstrap.state import StateRootInvalid as _StateRootInvalid

    if isinstance(observation.system, _StateRootInvalid):
        # Invalid journal/evidence or orphan transaction state is exit 2 with
        # every artifact preserved; automatic recovery is not blocked, it is
        # impossible without valid evidence.
        return _result(
            command,
            RecoveryFailure(
                (
                    command_error_diagnostic(
                        TransactionError(
                            TransactionErrorKind.INVALID_STATE_ROOT,
                            subject="state root evidence",
                        )
                    ),
                )
            ),
        )
    from scripts.bootstrap.decisions import (
        DiscardPreparation,
        DiscardStalePending,
        FinishForward,
        FinishRollbackCleanup,
        NoRecoveryNeeded,
        RefuseRecovery,
        RollBack,
        decide_project,
    )

    decision = decide_project(cast(ProjectIntent, parsed.intent), observation.system)
    match decision:
        case RefuseRecovery(error=error):
            return _result(command, _recovery_outcome(error))
        case NoRecoveryNeeded():
            return _result(
                command,
                Succeeded(
                    hook_evidence=NotAttempted(_hook_not_attempted_reason(command))
                ),
                state_document={"kind": "recovery"},
                decision_document={"kind": "no_recovery_needed"},
            )
        case (
            DiscardStalePending()
            | DiscardPreparation()
            | RollBack()
            | FinishRollbackCleanup()
            | FinishForward()
        ):
            pass
        case decision:  # pragma: no cover — every recovery decision is enumerated above
            del decision
            return _result(
                command,
                _recovery_outcome(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE)),
            )
    worktree = resolved.worktree
    assert worktree is not None
    resources = TransactionResources(worktree=worktree, limits=limits)
    lock_error: EffectError | TransitionError | None = None
    state_root_abs = worktree.state_root_abs
    match _open_directory_abs(state_root_abs):
        case Ok(fd):
            resources.state_root_fd = fd
        case Err(_):
            pass
    if resources.state_root_fd is None:
        match _ensure_directory_chain(
            _parent_of(state_root_abs), (b"agentic-template",)
        ):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        match _open_directory_abs(state_root_abs):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(fd):
                resources.state_root_fd = fd
    match acquire_lock(
        resources.state_root_fd,
        operation="recover",
        target_digest=observation.pass_.target.digest
        if observation.pass_ is not None
        else "",
    ):
        case Ok(guard):
            resources.lock = guard
        case Err(error):
            lock_error = error
    if lock_error is not None:
        return _result(command, _recovery_outcome(lock_error))
    try:
        return _execute_recovery_phase(
            cast(RecoveryDecision, decision), observation, resources
        )
    finally:
        if resources.lock is not None:
            release_lock(resources.lock)
        if resources.state_root_fd is not None:  # pyright: ignore[reportUnnecessaryComparison] — deliberate runtime contract check
            os.close(resources.state_root_fd)


def _parent_of(state_root_abs: bytes) -> bytes:
    parts = tuple(part for part in state_root_abs.split(b"/") if part)
    return b"/" + b"/".join(parts[:-1])


def _recovery_outcome(error: CommandError) -> CommandOutcome:
    """Recovery exit mapping: blocked recovery is 1, evidence failure is 2."""

    match error:
        case TransitionError(
            kind=TransitionErrorKind.RECOVERY_TARGET_MISMATCH
            | TransitionErrorKind.RECOVERY_THIRD_STATE
            | TransitionErrorKind.UNSUPPORTED_TARGET
        ):
            return ActionRequired((command_error_diagnostic(error),))
        case _:
            outcome = outcome_for_error(error)
            if isinstance(outcome, ActionRequired):
                return RecoveryFailure(outcome.diagnostics)
            return outcome


def _journal_envelope(
    observation: SystemObservation,
) -> Result[JournalEnvelope, CommandError]:
    if observation.pass_ is None or observation.pass_.state_root is None:  # pyright: ignore[reportUnnecessaryComparison] — deliberate runtime contract check
        return Err(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE))
    journal = observation.pass_.state_root.journal
    if journal is None:
        return Err(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE))
    match decode_journal(journal):
        case Err(error):
            return Err(
                TransactionError(
                    TransactionErrorKind.INVALID_JOURNAL, subject=error.reason
                )
            )
        case Ok(envelope):
            return Ok(envelope)


def _recovered_plan(
    envelope: JournalEnvelope, target: TargetIdentity
) -> Result[OperationPlan, CommandError]:
    if envelope.receipt is None:
        return Err(
            TransactionError(
                TransactionErrorKind.INVALID_JOURNAL,
                subject="the journal carries no plan receipt",
            )
        )
    match reconstruct_plan(envelope.receipt, target=target):
        case Err(error):
            return Err(
                TransactionError(
                    TransactionErrorKind.INVALID_JOURNAL,
                    subject=f"plan receipt: {error.kind.value}",
                )
            )
        case Ok(plan):
            return Ok(plan)


def _cleanup_phase(
    compiled: CompiledTransaction,
    phase: JournalPhase,
    resources: TransactionResources,
) -> Result[None, EffectError]:
    from scripts.bootstrap.transaction import derive_cleanup

    items = derive_cleanup(compiled.plan, phase)
    for cursor in range(len(items)):
        match _execute_clean_one(compiled, phase, cursor, resources):
            case Err(error):
                return _err_effect(error)
            case Ok(_):
                pass
    return Ok(None)


def _execute_recovery_phase(
    decision: RecoveryDecision,
    observation: SystemObservation,
    resources: TransactionResources,
) -> CommandResult:
    """Execute one phase-specific recovery action under the held lock."""

    command = "recover"
    from scripts.bootstrap.decisions import (
        DiscardPreparation,
        DiscardStalePending,
        FinishForward,
        FinishRollbackCleanup,
        RollBack,
    )

    target = observation.pass_.target if observation.pass_ is not None else None
    if target is None:
        return _result(
            command,
            _recovery_outcome(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE)),
        )
    fd = resources.state_root_fd
    if fd is None:
        return _result(
            command,
            _recovery_outcome(_invalid_state("state root is not open")),
        )
    if isinstance(decision, DiscardStalePending):
        match classify_child(fd, b"journal.pending"):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=1)):
                pass
            case Ok(_):
                return _result(
                    command,
                    _recovery_outcome(_invalid_state("journal.pending")),
                )
        try:
            os.unlink("journal.pending", dir_fd=fd)
        except OSError as error:
            return _result(
                command,
                _recovery_outcome(
                    TransactionError.primitive_failed(
                        TransactionPrimitive.REMOVE_FILE,
                        sanitize_errno(error),
                        "journal.pending",
                    )
                ),
            )
        match fsync_directory(fd):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        return _result(
            command,
            Succeeded(hook_evidence=NotAttempted(_hook_not_attempted_reason(command))),
            state_document={"kind": "recovery"},
            decision_document={"kind": "discard_stale_pending"},
        )
    match _journal_envelope(observation):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(envelope):
            pass
    if isinstance(decision, DiscardPreparation):
        match _recovered_plan(envelope, target):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(plan):
                pass
        for identity in envelope.preparations:
            if identity.role is PreparationRole.BACKUP:
                backup = os.path.join(
                    resources.worktree.state_root_abs,
                    os.fsencode(
                        f"transactions/{envelope.transaction_id}/backups/{identity.operation_index}"
                    ),
                )
                match _artifact_observation(backup, directory=False):
                    case Err(error):
                        return _result(command, _recovery_outcome(error))
                    case Ok(observed):
                        pass
                match cleanup_step(identity, observed):
                    case CleanupMissing():
                        continue
                    case CleanupVerified():
                        pass
                    case CleanupThirdState():
                        return _result(
                            command,
                            _recovery_outcome(_invalid_state(os.fsdecode(backup))),
                        )
                match _remove_artifact(backup, directory=False):
                    case Err(error):
                        return _result(command, _recovery_outcome(error))
                    case Ok(_):
                        pass
            else:
                if identity.operation_index >= len(plan.ordered_operations):
                    return _result(
                        command,
                        _recovery_outcome(
                            TransactionError(
                                TransactionErrorKind.INVALID_JOURNAL,
                                subject="preparation operation index",
                            )
                        ),
                    )
                operation = plan.ordered_operations[identity.operation_index]
                stage_dir = _stage_dir_for(
                    resources,
                    operation,
                    envelope.transaction_id,
                    identity.operation_index,
                )
                match _read_stage_marker(stage_dir):
                    case Err(error):
                        return _result(command, _recovery_outcome(error))
                    case Ok(None):
                        continue
                    case Ok(marker):
                        pass
                assert marker is not None
                if not _marker_matches_identity(marker, identity):
                    return _result(
                        command,
                        _recovery_outcome(_invalid_state(os.fsdecode(stage_dir))),
                    )
                match _remove_artifact(stage_dir, directory=True):
                    case Err(error):
                        return _result(command, _recovery_outcome(error))
                    case Ok(_):
                        pass
        return _finish_recovery_cleanup(command, envelope, resources)
    match _recovered_plan(envelope, target):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(plan):
            pass
    compiled = CompiledTransaction(
        plan,
        ExpectedGatePass(MechanicalReadinessResult(1, ())),
        envelope.transaction_id,
        # The journaled identities carry the original ownership-token hashes;
        # stage markers written before a crash can only be matched against
        # them, never against freshly allocated tokens.
        envelope.preparations,
    )
    if isinstance(decision, RollBack):
        specs = derive_rollback_specs(plan)
        resources.rollback_tokens = tuple(new_ownership_token() for _ in specs)
        resources.rollback_preparations = derive_rollback_preparations(
            plan, envelope.transaction_id, resources.rollback_tokens
        )
        for index in range(len(plan.ordered_operations) - 1, -1, -1):
            match _execute_rollback_one(compiled, index, resources):
                case Err(error):
                    return _result(
                        command,
                        _recovery_outcome(error),
                    )
                case Ok(_):
                    pass
        match capture_plan_snapshot(resources, plan):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(snapshot):
                pass
        match restored_verification(plan, snapshot):
            case ThirdStateFound(path=path):
                return _result(
                    command,
                    _recovery_outcome(
                        TransitionError(
                            TransitionErrorKind.RECOVERY_THIRD_STATE, path.value
                        )
                    ),
                )
            case PreStateIntact():
                pass
        restored = restored_envelope(
            VerifiedRestoredTransaction(
                MutatingTransaction(
                    PlannedTransaction(
                        ValidatedLockedTransaction(
                            LockedTransaction(compiled), snapshot
                        )
                    )
                )
            ),
            resources.rollback_preparations,
        )
        match persist_journal(fd, restored):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        match _cleanup_phase(compiled, JournalPhase.RESTORED, resources):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        return _recovery_succeeded(command)
    if isinstance(decision, FinishRollbackCleanup):
        match capture_plan_snapshot(resources, plan):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(snapshot):
                pass
        match restored_verification(plan, snapshot):
            case ThirdStateFound(path=path):
                return _result(
                    command,
                    _recovery_outcome(
                        TransitionError(
                            TransitionErrorKind.RECOVERY_THIRD_STATE, path.value
                        )
                    ),
                )
            case PreStateIntact():
                pass
        match _cleanup_phase(compiled, JournalPhase.RESTORED, resources):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        return _recovery_succeeded(command)
    if isinstance(decision, FinishForward):
        match capture_plan_snapshot(resources, plan):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(snapshot):
                pass
        match sealed_verification(plan, snapshot):
            case ThirdStateFound(path=path):
                return _result(
                    command,
                    _recovery_outcome(
                        TransitionError(
                            TransitionErrorKind.RECOVERY_THIRD_STATE, path.value
                        )
                    ),
                )
            case CandidateIntact():
                pass
        match _cleanup_phase(compiled, JournalPhase.SEALED, resources):
            case Err(error):
                return _result(command, _recovery_outcome(error))
            case Ok(_):
                pass
        return _recovery_succeeded(command)
    return _result(
        command,
        _recovery_outcome(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE)),
    )


def _finish_recovery_cleanup(
    command: str,
    envelope: JournalEnvelope,
    resources: TransactionResources,
) -> CommandResult:
    """Remove the transaction directory and the journal last, then report."""

    fd = resources.state_root_fd
    if fd is None:
        return _result(
            command,
            _recovery_outcome(_invalid_state("state root is not open")),
        )
    tx_dir = os.path.join(
        resources.worktree.state_root_abs,
        os.fsencode(f"transactions/{envelope.transaction_id}"),
    )
    try:
        for directory in (os.path.join(tx_dir, b"backups"), tx_dir):
            if os.path.isdir(directory) and not os.listdir(directory):
                os.rmdir(directory)
        transactions = os.path.join(resources.worktree.state_root_abs, b"transactions")
        if os.path.isdir(transactions) and not os.listdir(transactions):
            os.rmdir(transactions)
    except OSError as error:
        return _result(
            command,
            _recovery_outcome(
                TransactionError.primitive_failed(
                    TransactionPrimitive.REMOVE_DIRECTORY,
                    sanitize_errno(error),
                    os.fsdecode(tx_dir),
                )
            ),
        )
    match classify_child(fd, b"journal.json"):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=1)):
            pass
        case Ok(_):
            return _result(
                command,
                _recovery_outcome(_invalid_state("journal.json")),
            )
    try:
        os.unlink("journal.json", dir_fd=fd)
    except OSError as error:
        return _result(
            command,
            _recovery_outcome(
                TransactionError.primitive_failed(
                    TransactionPrimitive.REMOVE_FILE,
                    sanitize_errno(error),
                    "journal.json",
                )
            ),
        )
    match fsync_directory(fd):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(_):
            pass
    return _recovery_succeeded(command)


def _recovery_succeeded(command: str) -> CommandResult:
    return _result(
        command,
        Succeeded(hook_evidence=NotAttempted(_hook_not_attempted_reason(command))),
        state_document={"kind": "recovery"},
        decision_document={"kind": "phase_completed"},
    )


def execute_command(
    parsed: ParsedCommand,
    *,
    template_root: str | None = None,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> CommandResult:
    """Dispatch one parsed command to its executor."""

    root = template_root if template_root is not None else _template_root()
    if parsed.command == "init":
        return _execute_init(parsed)
    if parsed.command == "status":
        return _execute_status(parsed, template_root=root, limits=limits)
    if parsed.command in ("plan apply", "apply"):
        return _execute_mutation(parsed, template_root=root, limits=limits)
    if parsed.command in (
        "plan add",
        "add",
        "plan restore",
        "restore",
        "plan reconcile",
        "reconcile",
    ):
        return _execute_lifecycle_refusal(parsed, template_root=root, limits=limits)
    if parsed.command == "recover":
        return _execute_recover(parsed, template_root=root, limits=limits)
    return _result(
        parsed.command,
        outcome_for_error(UsageError(UsageErrorKind.UNKNOWN_COMMAND, parsed.command)),
    )


def main(argv: list[str]) -> int:
    """The adapter entry point: parse, execute, render, and choose the exit code."""

    match parse_argv(argv):
        case Err(error):
            # Usage errors render as plain deterministic text on stderr: the
            # JSON envelope guarantee applies to successfully parsed commands.
            diagnostic = command_error_diagnostic(error)
            print(
                f"{diagnostic.code}: {diagnostic.subject}: {diagnostic.summary}; next: {_render_next_action(diagnostic.next_action)}",
                file=sys.stderr,
            )
            return 2
        case Ok(parsed):
            pass
    if isinstance(parsed, str):
        return 0  # help already rendered by argparse
    try:
        result = execute_command(parsed)
    except Exception:  # every escape is one classified internal failure at the boundary
        # One classified internal failure, never a traceback: the design maps
        # an unclassified exception at the outer boundary to exit 2.
        result = _result(
            parsed.command,
            outcome_for_error(CoreInternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION)),
        )
    exit_code = _family_exit_code(parsed.command, result.outcome)
    if parsed.presentation.format == "json":
        print(render_json(result))
    else:
        text = render_text(
            result,
            quiet=parsed.presentation.quiet,
            explain=parsed.presentation.explain,
            color=_color_enabled(parsed.presentation),
        )
        if text:
            print(text)
    return exit_code
