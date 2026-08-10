"""Closed, staged state constructors for bootstrap policy evaluation.

The values in this module are deliberately boring immutable records.  The shell may
discover many intermediate facts, but policy receives only one of these legal sums.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scripts.bootstrap.identity import TargetIdentity
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.paths import RepoPath


@dataclass(frozen=True, slots=True)
class OutputAvailable:
    pass


@dataclass(frozen=True, slots=True)
class OutputLocationOccupied:
    pass


type BundleState = OutputAvailable | OutputLocationOccupied


class TargetReason(StrEnum):
    GIT_UNAVAILABLE = "git_unavailable"
    NOT_WORKTREE = "not_a_worktree"
    BARE_REPOSITORY = "bare_repository"
    UNSUPPORTED_FILESYSTEM = "unsupported_filesystem"


@dataclass(frozen=True, slots=True)
class UnsupportedGitTarget:
    reason: TargetReason

    def __post_init__(self) -> None:
        if not isinstance(self.reason, TargetReason):
            raise TypeError("git targets require a closed target reason")


@dataclass(frozen=True, slots=True)
class OrdinaryProject:
    """A target on which mutation is permitted, subject to project state."""


@dataclass(frozen=True, slots=True)
class CanonicalTemplateSource:
    remote: str


type TargetProtection = OrdinaryProject | CanonicalTemplateSource


@dataclass(frozen=True, slots=True)
class WorktreeContext:
    target: TargetIdentity
    state_root: RepoPath
    protection: TargetProtection


@dataclass(frozen=True, slots=True)
class SupportedWorktree:
    context: WorktreeContext


type TargetEnvironment = UnsupportedGitTarget | SupportedWorktree


@dataclass(frozen=True, slots=True)
class NoJournal:
    pass


@dataclass(frozen=True, slots=True)
class PendingIdentity:
    digest: str


@dataclass(frozen=True, slots=True)
class ValidatedJournal:
    operation: str
    target: TargetIdentity
    phase: str


@dataclass(frozen=True, slots=True)
class JournalTargetMismatch:
    journal: ValidatedJournal
    target: TargetIdentity


@dataclass(frozen=True, slots=True)
class StaleJournalWrite:
    pending: PendingIdentity


@dataclass(frozen=True, slots=True)
class InvalidJournal:
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryEvidenceInvalid:
    journal: ValidatedJournal
    reason: str


@dataclass(frozen=True, slots=True)
class OrphanTransactionState:
    reason: str


type JournalObservation = (
    NoJournal
    | StaleJournalWrite
    | ValidatedJournal
    | JournalTargetMismatch
    | InvalidJournal
    | RecoveryEvidenceInvalid
    | OrphanTransactionState
)


@dataclass(frozen=True, slots=True)
class CleanupContract:
    lifecycle_paths: tuple[RepoPath, ...]
    cleanup_paths: tuple[RepoPath, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class CleanupContractMismatch:
    paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class NoSnapshotCleanup:
    pass


@dataclass(frozen=True, slots=True)
class CleanupContractValid:
    contract: CleanupContract


type CleanupObservation = (
    NoSnapshotCleanup | CleanupContractValid | CleanupContractMismatch
)


@dataclass(frozen=True, slots=True)
class ManagedVerified:
    pass


@dataclass(frozen=True, slots=True)
class PathDelta:
    paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class ManagedDrift:
    delta: PathDelta


type ManagedObservation = ManagedVerified | ManagedDrift


@dataclass(frozen=True, slots=True)
class SourceDelta:
    paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class SnapshotRepair:
    commit: str
    paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class SnapshotSourceSame:
    managed: ManagedObservation


@dataclass(frozen=True, slots=True)
class SnapshotSourceChanged:
    delta: SourceDelta
    repair: SnapshotRepair
    managed: ManagedObservation


@dataclass(frozen=True, slots=True)
class SnapshotSourceUnrecoverable:
    delta: SourceDelta
    reason: str
    managed: ManagedObservation


type SnapshotCondition = (
    SnapshotSourceSame | SnapshotSourceChanged | SnapshotSourceUnrecoverable
)


@dataclass(frozen=True, slots=True)
class CopierConflicted:
    delta: PathDelta


@dataclass(frozen=True, slots=True)
class CopierSourceSame:
    managed: ManagedObservation


@dataclass(frozen=True, slots=True)
class CopierSourceChanged:
    delta: SourceDelta
    managed: ManagedObservation


type CopierCondition = CopierConflicted | CopierSourceSame | CopierSourceChanged


@dataclass(frozen=True, slots=True)
class RecordedProjectState:
    generation: GenerationPath
    source_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class TopologyError:
    paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class ClosureError:
    reason: str


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    entries: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class UnsafeExistingProject:
    recorded: RecordedProjectState
    error: TopologyError
    snapshot: TargetSnapshot


@dataclass(frozen=True, slots=True)
class IncompatibleExistingProject:
    recorded: RecordedProjectState
    error: ClosureError
    snapshot: TargetSnapshot


@dataclass(frozen=True, slots=True)
class SnapshotExistingProject:
    recorded: RecordedProjectState
    condition: SnapshotCondition
    snapshot: TargetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(
            self.condition,
            (SnapshotSourceSame, SnapshotSourceChanged, SnapshotSourceUnrecoverable),
        ):
            raise TypeError("snapshot projects require a snapshot condition")


@dataclass(frozen=True, slots=True)
class CopierExistingProject:
    recorded: RecordedProjectState
    condition: CopierCondition
    snapshot: TargetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(
            self.condition, (CopierConflicted, CopierSourceSame, CopierSourceChanged)
        ):
            raise TypeError("Copier projects require a Copier condition")


type ExistingProjectState = (
    UnsafeExistingProject
    | IncompatibleExistingProject
    | SnapshotExistingProject
    | CopierExistingProject
)


@dataclass(frozen=True, slots=True)
class EmptyManifestFree:
    pass


@dataclass(frozen=True, slots=True)
class PopulatedManifestFree:
    entries: tuple[RepoPath, ...]


type ManifestFreeShape = EmptyManifestFree | PopulatedManifestFree


@dataclass(frozen=True, slots=True)
class RecognizedScaffold:
    generation: GenerationPath
    cleanup: CleanupObservation
    shape: ManifestFreeShape
    snapshot: tuple[RepoPath, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.generation, GenerationPath):
            raise TypeError("recognized scaffolds require a generation path")


@dataclass(frozen=True, slots=True)
class UnsupportedManifestFree:
    shape: ManifestFreeShape
    snapshot: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class InvalidManifest:
    reason: str
    snapshot: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class ExistingProject:
    state: ExistingProjectState


type ProjectObservation = (
    RecognizedScaffold | UnsupportedManifestFree | InvalidManifest | ExistingProject
)


@dataclass(frozen=True, slots=True)
class TargetUnavailable:
    target: UnsupportedGitTarget


@dataclass(frozen=True, slots=True)
class StalePendingWrite:
    worktree: WorktreeContext
    pending: PendingIdentity


@dataclass(frozen=True, slots=True)
class JournalPending:
    worktree: WorktreeContext
    journal: ValidatedJournal


@dataclass(frozen=True, slots=True)
class JournalAtDifferentTarget:
    worktree: WorktreeContext
    journal: ValidatedJournal
    target: TargetIdentity


@dataclass(frozen=True, slots=True)
class StateRootInvalid:
    worktree: WorktreeContext
    evidence: InvalidJournal | RecoveryEvidenceInvalid | OrphanTransactionState


@dataclass(frozen=True, slots=True)
class ProtectedTargetAvailable:
    worktree: WorktreeContext
    observation: ProjectObservation


@dataclass(frozen=True, slots=True)
class ProjectAvailable:
    worktree: WorktreeContext | SupportedWorktree
    observation: ProjectObservation


type SystemState = (
    TargetUnavailable
    | StalePendingWrite
    | JournalPending
    | JournalAtDifferentTarget
    | StateRootInvalid
    | ProtectedTargetAvailable
    | ProjectAvailable
)


def context_of(state: SystemState) -> WorktreeContext | None:
    if isinstance(state, TargetUnavailable):
        return None
    if isinstance(
        state,
        (StalePendingWrite, JournalPending, JournalAtDifferentTarget, StateRootInvalid),
    ):
        return state.worktree
    if isinstance(state, (ProtectedTargetAvailable, ProjectAvailable)):
        return (
            state.worktree.context
            if isinstance(state.worktree, SupportedWorktree)
            else state.worktree
        )
    return None


def is_protected(state: SystemState) -> bool:
    if isinstance(state, ProtectedTargetAvailable):
        return True
    if isinstance(state, ProjectAvailable):
        context = context_of(state)
        return context is not None and isinstance(
            context.protection, CanonicalTemplateSource
        )
    return False
