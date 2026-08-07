"""Total, family-specific transition functions for bootstrap commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from scripts.bootstrap.errors import CommandError, TransitionError, TransitionErrorKind
from scripts.bootstrap.intents import (
    Add,
    Apply,
    InitBundle,
    InspectStatus,
    PlanAdd,
    PlanApply,
    PlanReconcile,
    PlanRestore,
    ProjectIntent,
    Reconcile,
    Recover,
    Restore,
)
from scripts.bootstrap.state import (
    BundleState,
    CleanupContractMismatch,
    CopierCondition,
    CopierConflicted,
    CopierExistingProject,
    CopierSourceChanged,
    CopierSourceSame,
    ExistingProject,
    ExistingProjectState,
    IncompatibleExistingProject,
    InvalidManifest,
    JournalAtDifferentTarget,
    JournalPending,
    ManagedDrift,
    NoSnapshotCleanup,
    ProjectAvailable,
    ProtectedTargetAvailable,
    RecognizedScaffold,
    SnapshotCondition,
    SnapshotExistingProject,
    SnapshotSourceChanged,
    SnapshotSourceSame,
    SnapshotSourceUnrecoverable,
    StalePendingWrite,
    StateRootInvalid,
    SystemState,
    TargetUnavailable,
    UnsafeExistingProject,
    UnsupportedManifestFree,
    is_protected,
)


@dataclass(frozen=True, slots=True)
class WriteBundle:
    output: object


@dataclass(frozen=True, slots=True)
class RefusePlan:
    error: CommandError


class RefuseBundle(RefusePlan):
    pass


@dataclass(frozen=True, slots=True)
class StatusView:
    state: SystemState
    explain: bool = False


@dataclass(frozen=True, slots=True)
class DescribeStatus:
    view: StatusView


@dataclass(frozen=True, slots=True)
class RefuseStatus:
    error: CommandError
    partial: StatusView | None = None


@dataclass(frozen=True, slots=True)
class CompileCandidate:
    intent: ProjectIntent


@dataclass(frozen=True, slots=True)
class InitialInstall:
    intent: Apply | PlanApply


@dataclass(frozen=True, slots=True)
class EquivalentVerification:
    intent: Apply | PlanApply


@dataclass(frozen=True, slots=True)
class AddCapabilities:
    intent: Add | PlanAdd


@dataclass(frozen=True, slots=True)
class RestoreManaged:
    intent: Restore | PlanRestore


@dataclass(frozen=True, slots=True)
class ReconcileTemplate:
    intent: Reconcile | PlanReconcile


@dataclass(frozen=True, slots=True)
class RefuseMutation:
    error: CommandError


@dataclass(frozen=True, slots=True)
class DiscardStalePending:
    pass


@dataclass(frozen=True, slots=True)
class DiscardPreparation:
    pass


@dataclass(frozen=True, slots=True)
class RollBack:
    pass


@dataclass(frozen=True, slots=True)
class FinishRollbackCleanup:
    pass


@dataclass(frozen=True, slots=True)
class FinishForward:
    pass


@dataclass(frozen=True, slots=True)
class NoRecoveryNeeded:
    pass


@dataclass(frozen=True, slots=True)
class RefuseRecovery:
    error: CommandError


type BundleDecision = WriteBundle | RefuseBundle
type StatusDecision = DescribeStatus | RefuseStatus
type PlanningDecision = CompileCandidate | RefusePlan
type MutationDecision = (
    InitialInstall
    | EquivalentVerification
    | AddCapabilities
    | RestoreManaged
    | ReconcileTemplate
    | RefuseMutation
)
type RecoveryDecision = (
    DiscardStalePending
    | DiscardPreparation
    | RollBack
    | FinishRollbackCleanup
    | FinishForward
    | NoRecoveryNeeded
    | RefuseRecovery
)
type CommandDecision = (
    BundleDecision
    | StatusDecision
    | PlanningDecision
    | MutationDecision
    | RecoveryDecision
)
type ActionIntent = (
    Apply
    | PlanApply
    | Add
    | PlanAdd
    | Restore
    | PlanRestore
    | Reconcile
    | PlanReconcile
)
type BlockedState = (
    TargetUnavailable
    | StalePendingWrite
    | JournalPending
    | JournalAtDifferentTarget
    | StateRootInvalid
)


def _transition(kind: TransitionErrorKind, subject: str = "") -> TransitionError:
    return TransitionError(kind, subject)


def decide_bundle(intent: InitBundle, state: BundleState) -> BundleDecision:
    """Decide ``init`` without admitting project-state facts into the bundle family."""

    from scripts.bootstrap.state import OutputAvailable, OutputLocationOccupied

    match state:
        case OutputAvailable():
            return WriteBundle(intent.options.output)
        case OutputLocationOccupied():
            return RefuseBundle(
                _transition(TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED)
            )
    return assert_never(state)


def _status(intent: InspectStatus, state: SystemState) -> StatusDecision:
    return DescribeStatus(StatusView(state, intent.options.explain))


def _recovery(intent: Recover, state: SystemState) -> RecoveryDecision:
    match state:
        case StalePendingWrite():
            return DiscardStalePending()
        case JournalPending(journal=journal):
            match journal.phase:
                case "PLANNED":
                    return DiscardPreparation()
                case "MUTATING":
                    return RollBack()
                case "RESTORED":
                    return FinishRollbackCleanup()
                case "SEALED":
                    return FinishForward()
                case phase:
                    return RefuseRecovery(
                        _transition(TransitionErrorKind.RECOVERY_REQUIRED, phase)
                    )
        case JournalAtDifferentTarget():
            return RefuseRecovery(
                _transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH)
            )
        case TargetUnavailable() | StateRootInvalid() | ProtectedTargetAvailable():
            return RefuseRecovery(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case ProjectAvailable():
            return NoRecoveryNeeded()
    return assert_never(state)


def _blocked(state: BlockedState) -> TransitionError:
    match state:
        case TargetUnavailable():
            return _transition(TransitionErrorKind.UNSUPPORTED_TARGET)
        case StalePendingWrite() | JournalPending() | StateRootInvalid():
            return _transition(TransitionErrorKind.RECOVERY_REQUIRED)
        case JournalAtDifferentTarget():
            return _transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH)
    return assert_never(state)


def _refuse_for(
    intent: ActionIntent, error: CommandError
) -> RefusePlan | RefuseMutation:
    match intent:
        case PlanApply() | PlanAdd() | PlanRestore() | PlanReconcile():
            return RefusePlan(error)
        case Apply() | Add() | Restore() | Reconcile():
            return RefuseMutation(error)
    return assert_never(intent)


def _has_managed_drift(condition: SnapshotCondition | CopierCondition) -> bool:
    match condition:
        case SnapshotSourceSame(managed=managed) | CopierSourceSame(managed=managed):
            return isinstance(managed, ManagedDrift)
        case (
            SnapshotSourceChanged()
            | SnapshotSourceUnrecoverable()
            | CopierConflicted()
            | CopierSourceChanged()
        ):
            return False
    return assert_never(condition)


def _apply_existing_decision(
    intent: Apply | PlanApply, existing: ExistingProjectState
) -> CommandDecision:
    match existing:
        case UnsafeExistingProject():
            return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case IncompatibleExistingProject():
            return RefuseMutation(
                _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        case SnapshotExistingProject(condition=condition):
            match condition:
                case SnapshotSourceSame():
                    if _has_managed_drift(condition):
                        return RefuseMutation(
                            _transition(TransitionErrorKind.MANAGED_DRIFT)
                        )
                    return EquivalentVerification(intent)
                case SnapshotSourceChanged() | SnapshotSourceUnrecoverable():
                    return RefuseMutation(
                        _transition(TransitionErrorKind.TEMPLATE_CHANGED)
                    )
            return assert_never(condition)
        case CopierExistingProject(condition=condition):
            match condition:
                case CopierConflicted():
                    return RefuseMutation(
                        _transition(TransitionErrorKind.COPIER_CONFLICTS)
                    )
                case CopierSourceSame():
                    if _has_managed_drift(condition):
                        return RefuseMutation(
                            _transition(TransitionErrorKind.MANAGED_DRIFT)
                        )
                    return EquivalentVerification(intent)
                case CopierSourceChanged():
                    return RefuseMutation(
                        _transition(TransitionErrorKind.TEMPLATE_CHANGED)
                    )
            return assert_never(condition)
    return assert_never(existing)


def _apply_decision(
    intent: Apply | PlanApply, state: ProjectAvailable
) -> CommandDecision:
    observation = state.observation
    match observation:
        case RecognizedScaffold(cleanup=NoSnapshotCleanup()):
            return InitialInstall(intent)
        case RecognizedScaffold(cleanup=CleanupContractMismatch()):
            leave = (
                isinstance(intent, Apply) and intent.options.leave_maintenance_artifacts
            )
            return (
                InitialInstall(intent)
                if leave
                else RefuseMutation(
                    _transition(TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED)
                )
            )
        case RecognizedScaffold():
            return InitialInstall(intent)
        case UnsupportedManifestFree() | InvalidManifest():
            return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case ExistingProject(state=existing):
            return _apply_existing_decision(intent, existing)
    return assert_never(observation)


def _project_action(intent: ActionIntent, state: ProjectAvailable) -> CommandDecision:
    match intent:
        case Apply() | PlanApply():
            result = _apply_decision(intent, state)
            if isinstance(intent, PlanApply):
                return (
                    CompileCandidate(intent)
                    if not isinstance(result, RefuseMutation)
                    else RefusePlan(result.error)
                )
            return result
        case Add() | PlanAdd():
            match state.observation:
                case ExistingProject(
                    state=CopierExistingProject(condition=condition)
                ) if isinstance(condition, CopierSourceSame) and not isinstance(
                    condition.managed, ManagedDrift
                ):
                    return (
                        AddCapabilities(intent)
                        if isinstance(intent, Add)
                        else CompileCandidate(intent)
                    )
                case _:
                    return _refuse_for(
                        intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
                    )
        case Restore() | PlanRestore():
            match state.observation:
                case (
                    ExistingProject(state=SnapshotExistingProject(condition=condition))
                    | ExistingProject(state=CopierExistingProject(condition=condition))
                ) if isinstance(condition, (SnapshotSourceSame, CopierSourceSame)):
                    return (
                        RestoreManaged(intent)
                        if isinstance(intent, Restore)
                        else CompileCandidate(intent)
                    )
                case _:
                    return _refuse_for(
                        intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
                    )
        case Reconcile() | PlanReconcile():
            match state.observation:
                case ExistingProject(
                    state=CopierExistingProject(condition=CopierSourceChanged())
                ):
                    return (
                        ReconcileTemplate(intent)
                        if isinstance(intent, Reconcile)
                        else CompileCandidate(intent)
                    )
                case _:
                    return _refuse_for(
                        intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
                    )
    return assert_never(intent)


def decide_project(intent: ProjectIntent, state: SystemState) -> CommandDecision:
    """Evaluate only legal project states and return one operation-specific decision."""

    match intent:
        case InspectStatus():
            return _status(intent, state)
        case Recover():
            return _recovery(intent, state)
        case (
            Apply()
            | PlanApply()
            | Add()
            | PlanAdd()
            | Restore()
            | PlanRestore()
            | Reconcile()
            | PlanReconcile()
        ):
            match state:
                case (
                    TargetUnavailable()
                    | StalePendingWrite()
                    | JournalPending()
                    | JournalAtDifferentTarget()
                    | StateRootInvalid()
                ):
                    return _refuse_for(intent, _blocked(state))
                case ProjectAvailable() if is_protected(state):
                    return _refuse_for(
                        intent, _transition(TransitionErrorKind.UNSUPPORTED_TARGET)
                    )
                case ProjectAvailable():
                    return _project_action(intent, state)
                case ProtectedTargetAvailable():
                    return _refuse_for(
                        intent, _transition(TransitionErrorKind.UNSUPPORTED_TARGET)
                    )
            return assert_never(state)
    return assert_never(intent)
