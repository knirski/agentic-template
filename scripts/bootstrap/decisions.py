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
from scripts.bootstrap.paths import RepoPath
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
    ValidatedJournal,
    is_protected,
)
from scripts.bootstrap.values import JournalPhase


@dataclass(frozen=True, slots=True)
class WriteBundle:
    output: RepoPath


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
type SameSourceCondition = SnapshotSourceSame | CopierSourceSame


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
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _status(intent: InspectStatus, state: SystemState) -> StatusDecision:
    return DescribeStatus(StatusView(state, intent.options.explain))


def _recovery(_intent: Recover, state: SystemState) -> RecoveryDecision:
    match state:
        case StalePendingWrite():
            return DiscardStalePending()
        case JournalPending(journal=journal):
            return _recovery_for_journal(journal)
        case JournalAtDifferentTarget():
            return RefuseRecovery(
                _transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH)
            )
        case TargetUnavailable() | StateRootInvalid():
            return RefuseRecovery(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case ProtectedTargetAvailable():
            # A canonical template source needs no recovery: the design maps
            # it to ``NoRecoveryNeeded`` rather than a refusal.
            return NoRecoveryNeeded()
        case ProjectAvailable():
            return NoRecoveryNeeded()
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _recovery_for_journal(journal: ValidatedJournal) -> RecoveryDecision:
    match journal.phase:
        case JournalPhase.PLANNED:
            return DiscardPreparation()
        case JournalPhase.MUTATING:
            return RollBack()
        case JournalPhase.RESTORED:
            return FinishRollbackCleanup()
        case JournalPhase.SEALED:
            return FinishForward()
        case phase:  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            # Defensive out-of-vocabulary fallback: the journal decoder
            # rejects unknown phases, but the decision layer still refuses
            # rather than crashing on a hand-constructed journal record.
            return RefuseRecovery(  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
                _transition(TransitionErrorKind.RECOVERY_REQUIRED, phase)
            )


def _blocked(state: BlockedState) -> TransitionError:
    match state:
        case TargetUnavailable():
            return _transition(TransitionErrorKind.UNSUPPORTED_TARGET)
        case StalePendingWrite() | JournalPending() | StateRootInvalid():
            return _transition(TransitionErrorKind.RECOVERY_REQUIRED)
        case JournalAtDifferentTarget():
            return _transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH)
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _refuse_for(
    intent: ActionIntent, error: CommandError
) -> RefusePlan | RefuseMutation:
    match intent:
        case PlanApply() | PlanAdd() | PlanRestore() | PlanReconcile():
            return RefusePlan(error)
        case Apply() | Add() | Restore() | Reconcile():
            return RefuseMutation(error)
    return assert_never(
        intent
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _has_managed_drift(condition: SameSourceCondition) -> bool:
    match condition:
        case (
            SnapshotSourceSame(managed=ManagedDrift())
            | CopierSourceSame(managed=ManagedDrift())
        ):
            return True
        case SnapshotSourceSame() | CopierSourceSame():
            return False
    return assert_never(
        condition
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _apply_existing_decision(
    _intent: Apply | PlanApply, existing: ExistingProjectState
) -> CommandDecision:
    match existing:
        case UnsafeExistingProject():
            return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case IncompatibleExistingProject():
            return RefuseMutation(
                _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        case SnapshotExistingProject(condition=condition):
            return _refuse_snapshot_condition(condition)
        case CopierExistingProject(condition=condition):
            return _refuse_copier_condition(condition)
    return assert_never(
        existing
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _refuse_snapshot_condition(condition: SnapshotCondition) -> RefuseMutation:
    match condition:
        case SnapshotSourceSame():
            if _has_managed_drift(condition):
                return RefuseMutation(_transition(TransitionErrorKind.MANAGED_DRIFT))
            return RefuseMutation(
                _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        case SnapshotSourceChanged() | SnapshotSourceUnrecoverable():
            return RefuseMutation(_transition(TransitionErrorKind.TEMPLATE_CHANGED))
    return assert_never(
        condition
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _refuse_copier_condition(condition: CopierCondition) -> RefuseMutation:
    match condition:
        case CopierConflicted():
            return RefuseMutation(_transition(TransitionErrorKind.COPIER_CONFLICTS))
        case CopierSourceSame():
            if _has_managed_drift(condition):
                return RefuseMutation(_transition(TransitionErrorKind.MANAGED_DRIFT))
            return RefuseMutation(
                _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        case CopierSourceChanged():
            return RefuseMutation(_transition(TransitionErrorKind.TEMPLATE_CHANGED))
    return assert_never(
        condition
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _apply_decision(
    intent: Apply | PlanApply, state: ProjectAvailable
) -> CommandDecision:
    observation = state.observation
    match observation:
        case RecognizedScaffold(cleanup=NoSnapshotCleanup()):
            return InitialInstall(intent)
        case RecognizedScaffold(cleanup=CleanupContractMismatch()):
            return _apply_cleanup_mismatch(intent)
        case RecognizedScaffold():
            return InitialInstall(intent)
        case UnsupportedManifestFree() | InvalidManifest():
            return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        case ExistingProject(state=existing):
            return _apply_existing_decision(intent, existing)
    return assert_never(
        observation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _apply_cleanup_mismatch(intent: Apply | PlanApply) -> CommandDecision:
    """A cleanup-mismatch scaffold installs only when the adopter permits leftovers."""
    match intent:
        case Apply() | PlanApply() if intent.options.leave_maintenance_artifacts:
            return InitialInstall(intent)
        case Apply() | PlanApply():
            return RefuseMutation(
                _transition(TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED)
            )


def _project_action(intent: ActionIntent, state: ProjectAvailable) -> CommandDecision:
    match intent:
        case Apply():
            return _apply_decision(intent, state)
        case PlanApply():
            return _plan_apply_decision(intent, state)
        case Add() | PlanAdd():
            return _add_decision(intent, state)
        case Restore() | PlanRestore():
            return _restore_decision(intent, state)
        case Reconcile() | PlanReconcile():
            return _reconcile_decision(intent, state)
    return assert_never(
        intent
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _plan_apply_decision(intent: PlanApply, state: ProjectAvailable) -> CommandDecision:
    """Plan-apply compiles the mutation unless the underlying apply was refused."""
    result = _apply_decision(intent, state)
    match result:
        case RefuseMutation():
            return RefusePlan(result.error)
        case _:
            return CompileCandidate(intent)


def _add_decision(intent: Add | PlanAdd, state: ProjectAvailable) -> CommandDecision:
    """Add accepts only a verified same-source Copier project without managed drift."""
    match state.observation:
        case ExistingProject(state=CopierExistingProject(condition=condition)):
            return _add_for_condition(intent, condition)
        case _:
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )


def _add_for_condition(
    intent: Add | PlanAdd, condition: CopierCondition
) -> CommandDecision:
    match condition:
        case CopierSourceSame(managed=ManagedDrift()):
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        case CopierSourceSame():
            return _accept_add(intent)
        case CopierConflicted() | CopierSourceChanged():
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )


def _accept_add(intent: Add | PlanAdd) -> CommandDecision:
    match intent:
        case Add():
            return AddCapabilities(intent)
        case PlanAdd():
            return CompileCandidate(intent)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        intent
    )


def _restore_decision(
    intent: Restore | PlanRestore, state: ProjectAvailable
) -> CommandDecision:
    """Restore accepts only a same-source condition on either generation path."""
    match state.observation:
        case ExistingProject(state=SnapshotExistingProject(condition=condition)):
            return _restore_for_condition(intent, condition)
        case ExistingProject(state=CopierExistingProject(condition=condition)):
            return _restore_for_condition(intent, condition)
        case _:
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )


def _restore_for_condition(
    intent: Restore | PlanRestore, condition: SnapshotCondition | CopierCondition
) -> CommandDecision:
    match condition:
        case SnapshotSourceSame() | CopierSourceSame():
            return _accept_restore(intent)
        case SnapshotSourceChanged(delta=delta, repair=repair):
            return _refuse_for(
                intent,
                _transition(
                    TransitionErrorKind.TEMPLATE_CHANGED,
                    "repair snapshot baseline "
                    + repair.commit
                    + " for "
                    + ",".join(path.value for path in delta.paths),
                ),
            )
        case SnapshotSourceUnrecoverable(delta=delta, reason=reason):
            return _refuse_for(
                intent,
                _transition(
                    TransitionErrorKind.TEMPLATE_CHANGED,
                    "regenerate from the current template; "
                    + reason
                    + "; paths: "
                    + ",".join(path.value for path in delta.paths),
                ),
            )
        case CopierConflicted() | CopierSourceChanged():
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )


def _accept_restore(intent: Restore | PlanRestore) -> CommandDecision:
    match intent:
        case Restore():
            return RestoreManaged(intent)
        case PlanRestore():
            return CompileCandidate(intent)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        intent
    )


def _reconcile_decision(
    intent: Reconcile | PlanReconcile, state: ProjectAvailable
) -> CommandDecision:
    """Reconcile accepts only a Copier project whose source changed."""
    match state.observation:
        case ExistingProject(
            state=CopierExistingProject(condition=CopierSourceChanged())
        ):
            return _accept_reconcile(intent)
        case _:
            return _refuse_for(
                intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )


def _accept_reconcile(intent: Reconcile | PlanReconcile) -> CommandDecision:
    match intent:
        case Reconcile():
            return ReconcileTemplate(intent)
        case PlanReconcile():
            return CompileCandidate(intent)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        intent
    )


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
            return _project_decision_for_state(intent, state)
    return assert_never(
        intent
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _project_decision_for_state(
    intent: ActionIntent, state: SystemState
) -> CommandDecision:
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
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
