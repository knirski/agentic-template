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
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from typing import Literal, NoReturn, cast, override

from scripts.bootstrap.bundles import (
    _BUNDLE_FILE,  # pyright: ignore[reportPrivateUsage]  shared bundle-path constant with the init executor
    HOOK_PATH,
    compile_initial_install,
    decode_bundle_input,
)
from scripts.bootstrap.canonical_json import canonical_json
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
    fsync_file,
    write_all,
)
from scripts.bootstrap.git_state import (
    ResolvedGitWorktree,
    run_git,
)
from scripts.bootstrap.identity import (
    DirectoryState,
    FileState,
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
    new_ownership_token,
    new_transaction_id,
)
from scripts.bootstrap.observation import (
    ProjectObservationPass,
    SystemObservation,
    _retained_cleanup_contract,  # pyright: ignore[reportPrivateUsage]  shared shell helpers with the mutation executor
    _scaffold_bytes,  # pyright: ignore[reportPrivateUsage]  shared shell helpers with the mutation executor
    _template_root,  # pyright: ignore[reportPrivateUsage]  shared shell helper with the command executors
    observe_system,
    resolve_shell_target,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.plan_digest import (
    PlanReceipt,
    build_receipt,
    encode_receipt,
    plan_receipt_digest,
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
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    RetainMaintenance,
    TargetSnapshot,
    apply_plan,
    evaluate_expected,
)
from scripts.bootstrap.presentation import (
    Change,
    CommandResult,
    PresentationOptions,
    _color_enabled,  # pyright: ignore[reportPrivateUsage]  shared color-resolution helper with the presentation layer
    _family_exit_code,  # pyright: ignore[reportPrivateUsage]  shared exit-code helper with the presentation layer
    _render_next_action,  # pyright: ignore[reportPrivateUsage]  shared next-action renderer with the presentation layer
    _result,  # pyright: ignore[reportPrivateUsage]  shared result constructor with the presentation layer
    render_json,
    render_text,
)
from scripts.bootstrap.process_effects import (
    Launched,
    LaunchFailed,
    TimedOut,
    run_captured,
    signalled,
)
from scripts.bootstrap.readiness import (
    MechanicalReadinessResult,
)
from scripts.bootstrap.resolver import (
    resolve_bundle,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import (
    CleanupContract,
    CleanupContractValid,
    CopierCondition,
    CopierExistingProject,
    InvalidManifest,
    ManagedObservation,
    ProjectObservation,
    SnapshotCondition,
    SnapshotExistingProject,
    SystemState,
    TargetUnavailable,
    UnsupportedGitTarget,
)
from scripts.bootstrap.transaction import (
    CompiledTransaction,
    Completed,
    Stopped,
    derive_preparation_specs,
)
from scripts.bootstrap.transaction_machine import (
    TransactionResources,
    _execute_recover,  # pyright: ignore[reportPrivateUsage]  shared recovery executor with the machine
    _fsync_dir_abs,  # pyright: ignore[reportPrivateUsage]  shared fsync helper with the machine
    _hook_not_attempted_reason,  # pyright: ignore[reportPrivateUsage]  shared hook-reason helper with the machine
    _observed_identity,  # pyright: ignore[reportPrivateUsage]  shared identity helper with the machine
    _write_file_exclusive,  # pyright: ignore[reportPrivateUsage]  shared exclusive-write helper with the machine
    run_transaction_machine,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits

# ---------------------------------------------------------------------------
# Command metadata and the closed usage grammar
# ---------------------------------------------------------------------------

PLANNING_COMMANDS = frozenset(
    {"plan apply", "plan add", "plan restore", "plan reconcile"}
)

_HOOK_TIMEOUT_SECONDS = 600.0
_HOOK_STREAM_BOUND = 64 * 1024


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


_TARGET_PARSER = _CapturingArgumentParser(add_help=False)
_ = _TARGET_PARSER.add_argument("--target")


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

    _ = subparsers.add_parser("status", add_help=True, parents=[_TARGET_PARSER])

    plan = subparsers.add_parser("plan", add_help=True)
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)
    for plan_command in ("apply", "add", "restore", "reconcile"):
        plan_parser = plan_subparsers.add_parser(
            plan_command, add_help=True, parents=[_TARGET_PARSER]
        )
        _plan_arguments(plan_command, plan_parser)

    apply = subparsers.add_parser("apply", add_help=True, parents=[_TARGET_PARSER])
    _ = apply.add_argument("--bundle", required=True)
    _ = apply.add_argument("--leave-maintenance-artifacts", action="store_true")

    add = subparsers.add_parser("add", add_help=True, parents=[_TARGET_PARSER])
    _ = add.add_argument("--input", required=True, dest="input_path")

    restore = subparsers.add_parser("restore", add_help=True, parents=[_TARGET_PARSER])
    _ = restore.add_argument("--path", action="append", default=[])

    reconcile = subparsers.add_parser(
        "reconcile", add_help=True, parents=[_TARGET_PARSER]
    )
    _ = reconcile.add_argument("--overwrite-drift", action="store_true")
    _ = reconcile.add_argument("--plan")

    _ = subparsers.add_parser("recover", add_help=True, parents=[_TARGET_PARSER])
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
    _ = parser.add_argument("--out")


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


def _transition_diagnostic(
    *,
    code: str,
    severity: DiagnosticSeverity,
    subject: str,
    details: str,
) -> tuple[Diagnostic, ...]:
    return (
        Diagnostic(
            code=code,
            category=DiagnosticCategory.TRANSITION,
            severity=severity,
            subject=subject,
            summary="bootstrap files were installed; the repository is not locally ready",
            details=details,
            next_action=RunCommand(("python3", "scripts/validate_repository.py")),
        ),
    )


def _not_ready_diagnostics(
    readiness: MechanicalReadinessResult,
) -> tuple[Diagnostic, ...]:
    if not readiness.blocking:
        return ()
    return _transition_diagnostic(
        code="BOOTSTRAP_READINESS_BLOCKING",
        severity=DiagnosticSeverity.WARNING,
        subject="repository readiness",
        details="replace every remaining placeholder and run the canonical validator",
    )


def _hook_failure_diagnostics() -> tuple[Diagnostic, ...]:
    return _transition_diagnostic(
        code="BOOTSTRAP_HOOK_FAILED",
        severity=DiagnosticSeverity.ERROR,
        subject="adopter hook",
        details="the adopter hook did not exit 0",
    )


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
        return _execute_recover(
            parsed.target, parsed.intent, template_root=root, limits=limits
        )
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
