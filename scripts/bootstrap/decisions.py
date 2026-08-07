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
    CopierExistingProject,
    CopierSourceChanged,
    CopierSourceSame,
    ExistingProject,
    IncompatibleExistingProject,
    InvalidManifest,
    JournalAtDifferentTarget,
    JournalPending,
    ManagedDrift,
    NoSnapshotCleanup,
    ProjectAvailable,
    ProtectedTargetAvailable,
    RecognizedScaffold,
    SnapshotExistingProject,
    SnapshotSourceChanged,
    SnapshotSourceSame,
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


def _transition(kind: TransitionErrorKind, subject: str = "") -> TransitionError:
    return TransitionError(kind, subject)


def decide_bundle(intent: InitBundle, state: BundleState) -> BundleDecision:
    """Decide ``init`` without admitting project-state facts into the bundle family."""

    from scripts.bootstrap.state import OutputAvailable, OutputLocationOccupied

    if isinstance(state, OutputAvailable):
        return WriteBundle(intent.options.output)
    if isinstance(state, OutputLocationOccupied):
        return RefuseBundle(_transition(TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED))
    return assert_never(state)


def _status(intent: InspectStatus, state: SystemState) -> StatusDecision:
    return DescribeStatus(StatusView(state, intent.options.explain))


def _recovery(intent: Recover, state: SystemState) -> RecoveryDecision:
    if isinstance(state, StalePendingWrite):
        return DiscardStalePending()
    if isinstance(state, JournalPending):
        phase = state.journal.phase
        if phase == "PLANNED":
            return DiscardPreparation()
        if phase == "MUTATING":
            return RollBack()
        if phase == "RESTORED":
            return FinishRollbackCleanup()
        if phase == "SEALED":
            return FinishForward()
        return RefuseRecovery(_transition(TransitionErrorKind.RECOVERY_REQUIRED, phase))
    if isinstance(state, JournalAtDifferentTarget):
        return RefuseRecovery(_transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH))
    if isinstance(
        state, (TargetUnavailable, StateRootInvalid, ProtectedTargetAvailable)
    ):
        return RefuseRecovery(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
    if isinstance(state, (ProjectAvailable,)):
        return NoRecoveryNeeded()
    if isinstance(state, ExistingProject):
        return NoRecoveryNeeded()
    return assert_never(state)


def _blocked(state: SystemState) -> RefuseMutation:
    if isinstance(state, TargetUnavailable):
        return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
    if isinstance(state, (StalePendingWrite, JournalPending)):
        return RefuseMutation(_transition(TransitionErrorKind.RECOVERY_REQUIRED))
    if isinstance(state, JournalAtDifferentTarget):
        return RefuseMutation(_transition(TransitionErrorKind.RECOVERY_TARGET_MISMATCH))
    if isinstance(state, StateRootInvalid):
        return RefuseMutation(_transition(TransitionErrorKind.RECOVERY_REQUIRED))
    return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))


def _refuse_for(
    intent: ActionIntent, error: CommandError
) -> RefusePlan | RefuseMutation:
    if isinstance(intent, (PlanApply, PlanAdd, PlanRestore, PlanReconcile)):
        return RefusePlan(error)
    return RefuseMutation(error)


def _apply_decision(
    intent: Apply | PlanApply, state: ProjectAvailable
) -> CommandDecision:
    observation = state.observation
    if isinstance(observation, RecognizedScaffold):
        if isinstance(observation.cleanup, NoSnapshotCleanup):
            return InitialInstall(intent)
        if isinstance(observation.cleanup, CleanupContractMismatch):
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
        return InitialInstall(intent)
    if isinstance(observation, (UnsupportedManifestFree, InvalidManifest)):
        return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
    if isinstance(observation, ExistingProject):
        existing = observation.state
        if isinstance(existing, UnsafeExistingProject):
            return RefuseMutation(_transition(TransitionErrorKind.UNSUPPORTED_TARGET))
        if isinstance(existing, IncompatibleExistingProject):
            return RefuseMutation(
                _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
            )
        if isinstance(existing, (SnapshotExistingProject, CopierExistingProject)):
            condition = existing.condition
            managed = getattr(condition, "managed", None)
            if isinstance(managed, ManagedDrift):
                return RefuseMutation(_transition(TransitionErrorKind.MANAGED_DRIFT))
            if isinstance(condition, (SnapshotSourceChanged, CopierSourceChanged)):
                return RefuseMutation(_transition(TransitionErrorKind.TEMPLATE_CHANGED))
            return EquivalentVerification(intent)
    return RefuseMutation(_transition(TransitionErrorKind.OPERATION_UNAVAILABLE))


def _project_action(intent: ActionIntent, state: ProjectAvailable) -> CommandDecision:
    if isinstance(intent, (Apply, PlanApply)):
        result = _apply_decision(intent, state)
        if isinstance(intent, PlanApply):
            return (
                CompileCandidate(intent)
                if not isinstance(result, RefuseMutation)
                else RefusePlan(result.error)
            )
        return result
    if isinstance(intent, (Add, PlanAdd)):
        if isinstance(state.observation, ExistingProject) and isinstance(
            state.observation.state, CopierExistingProject
        ):
            condition = state.observation.state.condition
            if isinstance(condition, CopierSourceSame) and not isinstance(
                condition.managed, ManagedDrift
            ):
                return (
                    AddCapabilities(intent)
                    if isinstance(intent, Add)
                    else CompileCandidate(intent)
                )
        return _refuse_for(
            intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
        )
    if isinstance(intent, (Restore, PlanRestore)):
        if isinstance(state.observation, ExistingProject):
            existing = state.observation.state
            if isinstance(existing, (SnapshotExistingProject, CopierExistingProject)):
                condition = existing.condition
                if isinstance(condition, (SnapshotSourceSame, CopierSourceSame)):
                    return (
                        RestoreManaged(intent)
                        if isinstance(intent, Restore)
                        else CompileCandidate(intent)
                    )
        return _refuse_for(
            intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
        )
    if isinstance(intent, (Reconcile, PlanReconcile)):
        if isinstance(state.observation, ExistingProject) and isinstance(
            state.observation.state, CopierExistingProject
        ):
            condition = state.observation.state.condition
            if isinstance(condition, CopierSourceChanged):
                return (
                    ReconcileTemplate(intent)
                    if isinstance(intent, Reconcile)
                    else CompileCandidate(intent)
                )
        return _refuse_for(
            intent, _transition(TransitionErrorKind.OPERATION_UNAVAILABLE)
        )
    return assert_never(intent)


def decide_project(intent: ProjectIntent, state: SystemState) -> CommandDecision:
    """Evaluate only legal project states and return one operation-specific decision."""

    if isinstance(intent, InspectStatus):
        return _status(intent, state)
    if isinstance(intent, Recover):
        return _recovery(intent, state)
    if isinstance(
        state,
        (
            TargetUnavailable,
            StalePendingWrite,
            JournalPending,
            JournalAtDifferentTarget,
            StateRootInvalid,
        ),
    ):
        blocked = _blocked(state)
        return _refuse_for(intent, blocked.error)
    if isinstance(state, ProjectAvailable):
        if is_protected(state):
            return _refuse_for(
                intent, _transition(TransitionErrorKind.UNSUPPORTED_TARGET)
            )
        return _project_action(intent, state)
    if isinstance(state, ProtectedTargetAvailable):
        return _refuse_for(intent, _transition(TransitionErrorKind.UNSUPPORTED_TARGET))
    return assert_never(state)
