"""Pure Mealy-style transaction machine and phase transitions.

T11 of the deterministic-project-bootstrap plan: preparation, backup,
mutation, post-state verification, gating, and the typed state machine through
``PLANNED``, ``MUTATING``, ``RESTORED``, and ``SEALED``.  The machine never
touches the filesystem: every step emits exactly one closed ``EffectRequest``,
the shell executes it, converts the ordinary OS result into a typed
``EffectObservation``, and feeds it back.  The machine selects no phase,
rollback direction, gate outcome, or next operation itself.

Effect selection stays in the machine; the shell never decides a transition.
Each continuation accepts only the observation constructor, index, identity,
and phase belonging to its own request; any other observation is
``InternalFailure(IMPOSSIBLE_STATE)`` rather than an ignored event.  The
journal transitions are states: ``NeedPlannedJournal --PLANNED--> Preparing``,
``NeedMutatingJournal --MUTATING--> Installing``,
``NeedRestoredJournal --RESTORED--> CleaningRollback``, and
``NeedSealedJournal --SEALED--> CleaningForward``.  ``Verifying`` may enter
``NeedSealedJournal`` only on gate pass; every refusal and every post-state
mismatch enters ``RollingBack``, whose only successful terminal transition is
``NeedRestoredJournal``.

Rollback reducers and recovery cleanup are implemented in T11b; this module
owns the machine's transition decisions, preparation/cleanup inventories, and
the pure snapshot verifications that gate them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, assert_never

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.errors import (
    InternalCode,
    InternalFailure,
    ObservationError,
    TransactionError,
    TransitionError,
    TransitionErrorKind,
)
from scripts.bootstrap.identity import (
    DirectoryEntry,
    DirectoryState,
    FileContentIdentity,
    FileEntry,
    FileState,
    PosixMode,
    TreeEntry,
)
from scripts.bootstrap.journal import (
    JournalEnvelope,
    JournalTarget,
    PreparationIdentity,
    PreparationRole,
    derive_preparation_identity,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    DirectoryOperation,
    ExpectedGatePass,
    ExpectedGateRefusal,
    ExpectedValidation,
    FileOperation,
    MaterializedTree,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    TargetSnapshot,
)
from scripts.bootstrap.values import JournalPhase

_TRANSACTION_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REVALIDATION_SUBJECT = "re-observed target differs from the planned preconditions"


type EffectError = ObservationError | TransactionError | InternalFailure
type ExecutionTrace = tuple[EffectRequestKind, ...]


class EffectRequestKind(StrEnum):
    ACQUIRE_LOCK = "acquire_lock"
    OBSERVE_AGAIN = "observe_again"
    PERSIST_JOURNAL = "persist_journal"
    PREPARE_ONE = "prepare_one"
    APPLY_ONE = "apply_one"
    OBSERVE_POST_STATE = "observe_post_state"
    CLEAN_ONE = "clean_one"
    ATTEMPT_ROLLBACK_ONE = "attempt_rollback_one"
    RELEASE_LOCK = "release_lock"


@dataclass(frozen=True, slots=True)
class AcquireLock:
    pass


@dataclass(frozen=True, slots=True)
class ObserveAgain:
    pass


@dataclass(frozen=True, slots=True)
class PersistJournal:
    phase: JournalPhase

    def __post_init__(self) -> None:
        if not isinstance(self.phase, JournalPhase):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("journal persistence requires a closed phase")


@dataclass(frozen=True, slots=True)
class PrepareOne:
    pass


@dataclass(frozen=True, slots=True)
class ApplyOne:
    pass


@dataclass(frozen=True, slots=True)
class ObservePostState:
    pass


@dataclass(frozen=True, slots=True)
class CleanOne:
    pass


@dataclass(frozen=True, slots=True)
class AttemptRollbackOne:
    pass


@dataclass(frozen=True, slots=True)
class ReleaseLock:
    pass


type EffectRequest = (
    AcquireLock
    | ObserveAgain
    | PersistJournal
    | PrepareOne
    | ApplyOne
    | ObservePostState
    | CleanOne
    | AttemptRollbackOne
    | ReleaseLock
)


def request_kind(request: EffectRequest) -> EffectRequestKind:
    """Return the closed request kind used for observation matching and traces."""

    match request:
        case AcquireLock():
            return EffectRequestKind.ACQUIRE_LOCK
        case ObserveAgain():
            return EffectRequestKind.OBSERVE_AGAIN
        case PersistJournal():
            return EffectRequestKind.PERSIST_JOURNAL
        case PrepareOne():
            return EffectRequestKind.PREPARE_ONE
        case ApplyOne():
            return EffectRequestKind.APPLY_ONE
        case ObservePostState():
            return EffectRequestKind.OBSERVE_POST_STATE
        case CleanOne():
            return EffectRequestKind.CLEAN_ONE
        case AttemptRollbackOne():
            return EffectRequestKind.ATTEMPT_ROLLBACK_ONE
        case ReleaseLock():
            return EffectRequestKind.RELEASE_LOCK
    return assert_never(
        request
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


@dataclass(frozen=True, slots=True)
class LockAcquired:
    pass


@dataclass(frozen=True, slots=True)
class LockRefused:
    error: TransitionError

    def __post_init__(self) -> None:
        if self.error.kind is not TransitionErrorKind.LOCK_HELD:
            raise TypeError("lock refusal must carry LOCK_HELD")


@dataclass(frozen=True, slots=True)
class Reobserved:
    snapshot: TargetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, TargetSnapshot):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("re-observation requires a target snapshot")


@dataclass(frozen=True, slots=True)
class JournalPersisted:
    phase: JournalPhase

    def __post_init__(self) -> None:
        if not isinstance(self.phase, JournalPhase):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("journal persistence requires a closed phase")


@dataclass(frozen=True, slots=True)
class PreparationCompleted:
    identity: PreparationIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.identity, PreparationIdentity):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("preparation completion requires an identity")


@dataclass(frozen=True, slots=True)
class ObservedFileAbsent:
    pass


@dataclass(frozen=True, slots=True)
class ObservedFilePresent:
    identity: FileContentIdentity
    mode: PosixMode
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class ObservedDirectoryAbsent:
    pass


@dataclass(frozen=True, slots=True)
class ObservedDirectoryPresent:
    state: DirectoryState
    device: int
    inode: int


type ObservedFile = ObservedFileAbsent | ObservedFilePresent
type ObservedDirectory = ObservedDirectoryAbsent | ObservedDirectoryPresent
type ObservedPathState = ObservedFile | ObservedDirectory


@dataclass(frozen=True, slots=True)
class OperationApplied:
    operation_index: int
    state: ObservedPathState

    def __post_init__(self) -> None:
        if type(self.operation_index) is not int or self.operation_index < 0:
            raise TypeError("operation index must be non-negative")
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.state,
            (
                ObservedFileAbsent,
                ObservedFilePresent,
                ObservedDirectoryAbsent,
                ObservedDirectoryPresent,
            ),
        ):
            raise TypeError("operation application requires a closed path state")


@dataclass(frozen=True, slots=True)
class PostStateObserved:
    snapshot: TargetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, TargetSnapshot):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("post-state observation requires a target snapshot")


@dataclass(frozen=True, slots=True)
class CleanupCompleted:
    cleanup_index: int

    def __post_init__(self) -> None:
        if type(self.cleanup_index) is not int or self.cleanup_index < 0:
            raise TypeError("cleanup index must be non-negative")


@dataclass(frozen=True, slots=True)
class RollbackAlreadyRestored:
    pass


@dataclass(frozen=True, slots=True)
class RollbackRestoredNow:
    pass


type RollbackEffectResult = RollbackAlreadyRestored | RollbackRestoredNow


@dataclass(frozen=True, slots=True)
class RollbackStepCompleted:
    operation_index: int
    result: RollbackEffectResult

    def __post_init__(self) -> None:
        if type(self.operation_index) is not int or self.operation_index < 0:
            raise TypeError("operation index must be non-negative")
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.result, (RollbackAlreadyRestored, RollbackRestoredNow)
        ):
            raise TypeError("rollback steps require a closed result")


@dataclass(frozen=True, slots=True)
class LockReleased:
    pass


@dataclass(frozen=True, slots=True)
class EffectFailed:
    request_kind: EffectRequestKind
    error: EffectError

    def __post_init__(self) -> None:
        if not isinstance(self.request_kind, EffectRequestKind):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("failed effects require a closed request kind")
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.error, (ObservationError, TransactionError, InternalFailure)
        ):
            raise TypeError("failed effects require a closed effect error")


type EffectObservation = (
    LockAcquired
    | LockRefused
    | Reobserved
    | JournalPersisted
    | PreparationCompleted
    | OperationApplied
    | PostStateObserved
    | CleanupCompleted
    | RollbackStepCompleted
    | LockReleased
    | EffectFailed
)


@dataclass(frozen=True, slots=True)
class Start:
    pass


@dataclass(frozen=True, slots=True)
class ObservedEffect:
    observation: EffectObservation

    def __post_init__(self) -> None:
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.observation,
            (
                LockAcquired,
                LockRefused,
                Reobserved,
                JournalPersisted,
                PreparationCompleted,
                OperationApplied,
                PostStateObserved,
                CleanupCompleted,
                RollbackStepCompleted,
                LockReleased,
                EffectFailed,
            ),
        ):
            raise TypeError("observed effects require a closed observation")


type TransactionEvent = Start | ObservedEffect


@dataclass(frozen=True, slots=True)
class PreparationCursor:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise TypeError("preparation cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class OperationCursor:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise TypeError("operation cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class RollbackCursor:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise TypeError("rollback cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class CleanupCursor:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise TypeError("cleanup cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class PreparationSpec:
    """The journaled shape of one reserved stage or backup location."""

    operation_index: int
    role: PreparationRole
    expected_kind: Literal["file", "directory"]
    expected_raw_sha256: str | None
    expected_mode: PosixMode


def _preparation_specs_for_operation(
    operation: FileOperation | DirectoryOperation, index: int
) -> tuple[PreparationSpec, ...]:
    """Return the reserved stage and backup specs for one planned operation."""

    match operation:
        case CreateFileOperation(planned_new=planned):
            return (
                PreparationSpec(
                    index,
                    PreparationRole.STAGE,
                    "file",
                    planned.identity.raw_sha256,
                    planned.mode,
                ),
            )
        case ReplaceFileOperation(expected_old=expected, planned_new=planned):
            old = _old_file_state(expected)
            specs = [
                PreparationSpec(
                    index,
                    PreparationRole.STAGE,
                    "file",
                    planned.identity.raw_sha256,
                    planned.mode,
                )
            ]
            if old is not None:
                old_digest, old_mode = old
                specs.append(
                    PreparationSpec(
                        index, PreparationRole.BACKUP, "file", old_digest, old_mode
                    )
                )
            return tuple(specs)
        case DeleteFileOperation(expected_old=expected):
            old = _old_file_state(expected)
            if old is None:  # pragma: no cover — plans only delete present files
                return ()
            old_digest, old_mode = old
            return (
                PreparationSpec(
                    index, PreparationRole.BACKUP, "file", old_digest, old_mode
                ),
            )
        case CreateTreeOperation(planned_new=planned_tree):
            return (
                PreparationSpec(
                    index,
                    PreparationRole.STAGE,
                    "directory",
                    None,
                    planned_tree.root_mode,
                ),
            )
        case RemoveEmptyDirectoryOperation():
            return ()
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def derive_preparation_specs(plan: OperationPlan) -> tuple[PreparationSpec, ...]:
    """Derive the exact stage and backup specs for every planned operation.

    New content (created or replaced files, created trees) reserves a stage;
    existing content (replaced or deleted files) reserves a raw backup.  An
    operation whose old state is absent or whose new state is absent reserves
    nothing for that side; the plan encodes both absences explicitly.
    """

    return tuple(
        spec
        for index, operation in enumerate(plan.ordered_operations)
        for spec in _preparation_specs_for_operation(operation, index)
    )


def _old_file_state(expected: FileState) -> tuple[str, PosixMode] | None:
    if not expected.present:
        return None
    identity = expected.identity
    mode = expected.mode
    if (
        identity is None or mode is None
    ):  # pragma: no cover — present states always carry both
        return None  # pragma: no cover — present states always carry both
    return identity.raw_sha256, mode


def derive_preparations(
    plan: OperationPlan,
    transaction_id: str,
    ownership_tokens: tuple[bytes, ...],
) -> tuple[PreparationIdentity, ...]:
    """Derive one journaled preparation identity per reserved stage or backup."""

    specs = derive_preparation_specs(plan)
    if len(ownership_tokens) != len(specs):
        raise ValueError("one ownership token is required per preparation")
    return tuple(
        derive_preparation_identity(
            transaction_id,
            spec.operation_index,
            spec.role,
            token,
            expected_kind=spec.expected_kind,
            expected_raw_sha256=spec.expected_raw_sha256,
            expected_mode=spec.expected_mode,
        )
        for spec, token in zip(specs, ownership_tokens, strict=True)
    )


class CleanupKind(StrEnum):
    STAGE = "stage"
    BACKUP = "backup"
    TRANSACTION_DIRECTORY = "transaction_directory"
    JOURNAL = "journal"


@dataclass(frozen=True, slots=True)
class CleanupItem:
    """One indexed cleanup step; ``operation_index`` is absent for state-root items."""

    kind: CleanupKind
    operation_index: int | None = None


def derive_cleanup(plan: OperationPlan, phase: JournalPhase) -> tuple[CleanupItem, ...]:
    """Derive the ordered cleanup inventory for ``SEALED`` or ``RESTORED``.

    Stages and backups are removed in plan order, then the transaction
    directory, and ``journal.json`` last so the journal remains authoritative
    until every other artifact is gone.  T11b extends the ``RESTORED``
    inventory with rollback containers.
    """

    if phase not in (JournalPhase.RESTORED, JournalPhase.SEALED):
        raise ValueError("cleanup is derived only for RESTORED and SEALED phases")
    items: list[CleanupItem] = []
    for spec in derive_preparation_specs(plan):
        match spec.role:
            case PreparationRole.STAGE:
                items.append(CleanupItem(CleanupKind.STAGE, spec.operation_index))
            case PreparationRole.BACKUP:
                items.append(CleanupItem(CleanupKind.BACKUP, spec.operation_index))
            case PreparationRole.ROLLBACK:  # pragma: no cover — v1 preparation specs never reserve rollback containers
                pass
    items.append(CleanupItem(CleanupKind.TRANSACTION_DIRECTORY))
    items.append(CleanupItem(CleanupKind.JOURNAL))
    return tuple(items)


@dataclass(frozen=True, slots=True)
class CompiledTransaction:
    """The complete machine payload: plan, expected gate outcome, and reserved identities."""

    plan: OperationPlan
    expected_validation: ExpectedValidation
    transaction_id: str
    preparations: tuple[PreparationIdentity, ...]

    def __post_init__(self) -> None:
        if _TRANSACTION_HEX.fullmatch(self.transaction_id) is None:
            raise TypeError("transaction id must be 256-bit lowercase hex")
        specs = derive_preparation_specs(self.plan)
        if len(self.preparations) != len(specs):
            raise TypeError("preparations do not match the plan preparation specs")
        for preparation, spec in zip(self.preparations, specs, strict=True):
            if (
                preparation.transaction_id != self.transaction_id
                or preparation.operation_index != spec.operation_index
                or preparation.role is not spec.role
                or preparation.expected_kind != spec.expected_kind
                or preparation.expected_raw_sha256 != spec.expected_raw_sha256
                or preparation.expected_mode != spec.expected_mode
            ):
                raise TypeError("preparation identity does not match its plan spec")

    @classmethod
    def compile(
        cls,
        plan: OperationPlan,
        expected_validation: ExpectedValidation,
        *,
        transaction_id: str,
        ownership_tokens: tuple[bytes, ...],
    ) -> CompiledTransaction:
        """Allocate the journaled preparation identities from shell-provided tokens."""

        return cls(
            plan,
            expected_validation,
            transaction_id,
            derive_preparations(plan, transaction_id, ownership_tokens),
        )


@dataclass(frozen=True, slots=True)
class LockedTransaction:
    compiled: CompiledTransaction


@dataclass(frozen=True, slots=True)
class ValidatedLockedTransaction:
    locked: LockedTransaction
    reobserved: TargetSnapshot


@dataclass(frozen=True, slots=True)
class PlannedTransaction:
    validated: ValidatedLockedTransaction


@dataclass(frozen=True, slots=True)
class MutatingTransaction:
    planned: PlannedTransaction


@dataclass(frozen=True, slots=True)
class VerifiedRestoredTransaction:
    mutating: MutatingTransaction


@dataclass(frozen=True, slots=True)
class GatedCandidateTransaction:
    mutating: MutatingTransaction
    post_state: TargetSnapshot


@dataclass(frozen=True, slots=True)
class SealedTransaction:
    gated: GatedCandidateTransaction


@dataclass(frozen=True, slots=True)
class RestoredTransaction:
    verified: VerifiedRestoredTransaction


def _planned_tree_entry(
    entry: PlannedDirectoryEntry | PlannedFileEntry, blobs: VerifiedBlobStore
) -> TreeEntry:
    """Map one planned tree entry onto its exact observed byte identity."""

    match entry:
        case PlannedDirectoryEntry(path=path, mode=mode):
            return DirectoryEntry(path, mode)
        case PlannedFileEntry(path=path, mode=mode, content_id=content_id):
            content = blobs.get(content_id)
            if content is None:  # pragma: no cover — the planner resolved every blob
                raise ValueError(f"missing blob for {path.value}")
            return FileEntry(path, content, mode)
    return assert_never(
        entry
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _planned_directory_state(
    tree: MaterializedTree, blobs: VerifiedBlobStore
) -> DirectoryState:
    return DirectoryState(
        root_mode=tree.root_mode,
        entries=tuple(_planned_tree_entry(entry, blobs) for entry in tree.entries),
    )


def _file_state_matches(observed: FileState | None, expected: FileState) -> bool:
    if observed is not None and not observed.present:
        observed = None  # an explicit absent entry is absence
    if expected.present:
        return observed is not None and observed == expected
    return observed is None


def _precondition_matches(
    operation: FileOperation | DirectoryOperation,
    files: dict[RepoPath, FileState],
    directories: dict[RepoPath, DirectoryState],
) -> bool:
    """Return whether one operation's expected old state is observed."""

    match operation:
        case CreateFileOperation(path=path, expected_old=expected):
            return _file_state_matches(files.get(path), expected)
        case ReplaceFileOperation(path=path, expected_old=expected):
            return _file_state_matches(files.get(path), expected)
        case DeleteFileOperation(path=path, expected_old=expected):
            return _file_state_matches(files.get(path), expected)
        case CreateTreeOperation(root=root, expected_old=expected):
            observed = directories.get(root)
            if expected is None:
                return observed is None
            return (
                observed == expected
            )  # pragma: no cover — plans reserve trees only under absent roots
        case RemoveEmptyDirectoryOperation(path=path, expected_old=expected):
            return directories.get(path) == expected
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def snapshot_matches_preconditions(
    plan: OperationPlan, snapshot: TargetSnapshot
) -> bool:
    """Return whether the snapshot equals every operation's expected old state."""

    files = {entry.path: entry.state for entry in snapshot.files}
    directories = {entry.path: entry.state for entry in snapshot.directories}
    return all(
        _precondition_matches(operation, files, directories)
        for operation in plan.ordered_operations
    )


def _candidate_matches(
    operation: FileOperation | DirectoryOperation,
    files: dict[RepoPath, FileState],
    directories: dict[RepoPath, DirectoryState],
    blobs: VerifiedBlobStore,
) -> bool:
    """Return whether one operation's planned new state is observed."""

    match operation:
        case (
            CreateFileOperation(path=path, planned_new=planned)
            | ReplaceFileOperation(path=path, planned_new=planned)
        ):
            observed = files.get(path)
            if observed is None or not observed.present:
                return False
            return (
                observed.identity == planned.identity and observed.mode == planned.mode
            )
        case DeleteFileOperation(path=path):
            state = files.get(path)
            return state is None or not state.present
        case CreateTreeOperation(root=root, planned_new=planned_tree):
            observed = directories.get(root)
            return observed is not None and observed == _planned_directory_state(
                planned_tree, blobs
            )
        case RemoveEmptyDirectoryOperation(path=path):
            return path not in directories
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def snapshot_matches_candidate(plan: OperationPlan, snapshot: TargetSnapshot) -> bool:
    """Return whether the snapshot equals every operation's planned new state."""

    files = {entry.path: entry.state for entry in snapshot.files}
    directories = {entry.path: entry.state for entry in snapshot.directories}
    return all(
        _candidate_matches(operation, files, directories, plan.blob_store)
        for operation in plan.ordered_operations
    )


def _envelope(compiled: CompiledTransaction, phase: JournalPhase) -> JournalEnvelope:
    return JournalEnvelope(
        operation=compiled.plan.operation_kind,
        target=JournalTarget.from_identity(compiled.plan.target_identity),
        phase=phase,
        transaction_id=compiled.transaction_id,
        preparations=compiled.preparations,
    )


def planned_envelope(planned: PlannedTransaction) -> JournalEnvelope:
    return _envelope(planned.validated.locked.compiled, JournalPhase.PLANNED)


def mutating_envelope(planned: PlannedTransaction) -> JournalEnvelope:
    return _envelope(planned.validated.locked.compiled, JournalPhase.MUTATING)


def restored_envelope(verified: VerifiedRestoredTransaction) -> JournalEnvelope:
    return _envelope(
        verified.mutating.planned.validated.locked.compiled, JournalPhase.RESTORED
    )


def sealed_envelope(gated: GatedCandidateTransaction) -> JournalEnvelope:
    return _envelope(
        gated.mutating.planned.validated.locked.compiled, JournalPhase.SEALED
    )


@dataclass(frozen=True, slots=True)
class NeedLock:
    compiled: CompiledTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class NeedRevalidation:
    locked: LockedTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class NeedPlannedJournal:
    validated: ValidatedLockedTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class Preparing:
    planned: PlannedTransaction
    cursor: PreparationCursor
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class NeedMutatingJournal:
    planned: PlannedTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class Installing:
    mutating: MutatingTransaction
    cursor: OperationCursor
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class Verifying:
    mutating: MutatingTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class RollingBack:
    mutating: MutatingTransaction
    cursor: RollbackCursor
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class NeedRestoredJournal:
    verified: VerifiedRestoredTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class NeedSealedJournal:
    gated: GatedCandidateTransaction
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class CleaningForward:
    sealed: SealedTransaction
    cursor: CleanupCursor
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class CleaningRollback:
    restored: RestoredTransaction
    cursor: CleanupCursor
    trace: ExecutionTrace = ()


@dataclass(frozen=True, slots=True)
class Releasing:
    sealed_or_restored: SealedTransaction | RestoredTransaction
    trace: ExecutionTrace = ()


type TransactionMachineState = (
    NeedLock
    | NeedRevalidation
    | NeedPlannedJournal
    | Preparing
    | NeedMutatingJournal
    | Installing
    | Verifying
    | RollingBack
    | NeedRestoredJournal
    | NeedSealedJournal
    | CleaningForward
    | CleaningRollback
    | Releasing
)


@dataclass(frozen=True, slots=True)
class TransactionInstruction:
    request: EffectRequest
    next_state: TransactionMachineState


@dataclass(frozen=True, slots=True)
class Completed:
    trace: ExecutionTrace


@dataclass(frozen=True, slots=True)
class Stopped:
    trace: ExecutionTrace
    error: EffectError | TransitionError


type TransactionOutcome = Completed | Stopped


@dataclass(frozen=True, slots=True)
class TransactionTerminal:
    outcome: TransactionOutcome


type TransactionStep = TransactionInstruction | TransactionTerminal


def _state_trace(state: TransactionMachineState) -> ExecutionTrace:
    match state:
        case NeedLock(trace=trace):
            return trace
        case NeedRevalidation(trace=trace):
            return trace
        case NeedPlannedJournal(trace=trace):
            return trace
        case Preparing(trace=trace):
            return trace
        case NeedMutatingJournal(trace=trace):
            return trace
        case Installing(trace=trace):
            return trace
        case Verifying(trace=trace):
            return trace
        case RollingBack(trace=trace):
            return trace
        case NeedRestoredJournal(trace=trace):
            return trace
        case NeedSealedJournal(trace=trace):
            return trace
        case CleaningForward(trace=trace):
            return trace
        case CleaningRollback(trace=trace):
            return trace
        case Releasing(trace=trace):
            return trace
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _awaits(trace: ExecutionTrace, kind: EffectRequestKind) -> bool:
    """Return whether the last requested effect is ``kind``."""

    return bool(trace) and trace[-1] == kind


def _enter_rollback(
    mutating: MutatingTransaction, trace: ExecutionTrace
) -> TransactionStep:
    operations = mutating.planned.validated.locked.compiled.plan.ordered_operations
    if operations:
        return TransactionInstruction(
            AttemptRollbackOne(),
            RollingBack(
                mutating,
                RollbackCursor(len(operations) - 1),
                (*trace, EffectRequestKind.ATTEMPT_ROLLBACK_ONE),
            ),
        )
    return TransactionInstruction(
        PersistJournal(JournalPhase.RESTORED),
        NeedRestoredJournal(
            VerifiedRestoredTransaction(mutating),
            (*trace, EffectRequestKind.PERSIST_JOURNAL),
        ),
    )


def step_transaction(
    state: TransactionMachineState, event: TransactionEvent
) -> TransactionStep:
    """Advance the transaction machine by exactly one closed event.

    Every nonterminal transition emits exactly one ``EffectRequest`` and one
    continuation state.  A continuation accepts only the observation
    constructor, index, identity, and phase belonging to its own request;
    ``EffectFailed`` is accepted only when it names the pending request kind.
    Any other pair is ``Stopped(InternalFailure(IMPOSSIBLE_STATE))`` rather
    than an ignored event.
    """

    match (state, event):
        case (NeedLock(compiled=compiled, trace=trace), Start()):
            return TransactionInstruction(
                AcquireLock(),
                NeedRevalidation(
                    LockedTransaction(compiled),
                    (*trace, EffectRequestKind.ACQUIRE_LOCK),
                ),
            )
        case (
            NeedRevalidation(locked=locked, trace=trace),
            ObservedEffect(LockAcquired()),
        ) if _awaits(trace, EffectRequestKind.ACQUIRE_LOCK):
            return TransactionInstruction(
                ObserveAgain(),
                NeedRevalidation(locked, (*trace, EffectRequestKind.OBSERVE_AGAIN)),
            )
        case (
            NeedRevalidation(locked=locked, trace=trace),
            ObservedEffect(Reobserved(snapshot=snapshot)),
        ) if _awaits(trace, EffectRequestKind.OBSERVE_AGAIN):
            if snapshot_matches_preconditions(locked.compiled.plan, snapshot):
                return TransactionInstruction(
                    PersistJournal(JournalPhase.PLANNED),
                    NeedPlannedJournal(
                        ValidatedLockedTransaction(locked, snapshot),
                        (*trace, EffectRequestKind.PERSIST_JOURNAL),
                    ),
                )
            return TransactionTerminal(
                Stopped(
                    trace,
                    TransitionError(
                        TransitionErrorKind.INPUT_CHANGED, _REVALIDATION_SUBJECT
                    ),
                )
            )
        case (
            NeedRevalidation(trace=trace),
            ObservedEffect(LockRefused(error=error)),
        ) if _awaits(trace, EffectRequestKind.ACQUIRE_LOCK):
            return TransactionTerminal(Stopped(trace, error))
        case (
            NeedPlannedJournal(validated=validated, trace=trace),
            ObservedEffect(JournalPersisted(phase=JournalPhase.PLANNED)),
        ):
            planned = PlannedTransaction(validated)
            if validated.locked.compiled.preparations:
                return TransactionInstruction(
                    PrepareOne(),
                    Preparing(
                        planned,
                        PreparationCursor(0),
                        (*trace, EffectRequestKind.PREPARE_ONE),
                    ),
                )
            return TransactionInstruction(
                PersistJournal(JournalPhase.MUTATING),
                NeedMutatingJournal(
                    planned, (*trace, EffectRequestKind.PERSIST_JOURNAL)
                ),
            )
        case (
            Preparing(planned=planned, cursor=cursor, trace=trace),
            ObservedEffect(PreparationCompleted(identity=identity)),
        ):
            preparations = planned.validated.locked.compiled.preparations
            if (
                cursor.index >= len(preparations)
                or identity != preparations[cursor.index]
            ):
                return TransactionTerminal(
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE))
                )
            if cursor.index + 1 < len(preparations):
                return TransactionInstruction(
                    PrepareOne(),
                    Preparing(
                        planned,
                        PreparationCursor(cursor.index + 1),
                        (*trace, EffectRequestKind.PREPARE_ONE),
                    ),
                )
            return TransactionInstruction(
                PersistJournal(JournalPhase.MUTATING),
                NeedMutatingJournal(
                    planned, (*trace, EffectRequestKind.PERSIST_JOURNAL)
                ),
            )
        case (
            NeedMutatingJournal(planned=planned, trace=trace),
            ObservedEffect(JournalPersisted(phase=JournalPhase.MUTATING)),
        ):
            mutating = MutatingTransaction(planned)
            if planned.validated.locked.compiled.plan.ordered_operations:
                return TransactionInstruction(
                    ApplyOne(),
                    Installing(
                        mutating,
                        OperationCursor(0),
                        (*trace, EffectRequestKind.APPLY_ONE),
                    ),
                )
            return TransactionInstruction(
                ObservePostState(),
                Verifying(mutating, (*trace, EffectRequestKind.OBSERVE_POST_STATE)),
            )
        case (
            Installing(mutating=mutating, cursor=cursor, trace=trace),
            ObservedEffect(OperationApplied(operation_index=index, state=_)),
        ):
            operations = (
                mutating.planned.validated.locked.compiled.plan.ordered_operations
            )
            if index != cursor.index or cursor.index >= len(operations):
                return TransactionTerminal(
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE))
                )
            if cursor.index + 1 < len(operations):
                return TransactionInstruction(
                    ApplyOne(),
                    Installing(
                        mutating,
                        OperationCursor(cursor.index + 1),
                        (*trace, EffectRequestKind.APPLY_ONE),
                    ),
                )
            return TransactionInstruction(
                ObservePostState(),
                Verifying(mutating, (*trace, EffectRequestKind.OBSERVE_POST_STATE)),
            )
        case (
            Verifying(mutating=mutating, trace=trace),
            ObservedEffect(PostStateObserved(snapshot=snapshot)),
        ):
            compiled = mutating.planned.validated.locked.compiled
            if snapshot_matches_candidate(compiled.plan, snapshot):
                match compiled.expected_validation:
                    case ExpectedGatePass():
                        return TransactionInstruction(
                            PersistJournal(JournalPhase.SEALED),
                            NeedSealedJournal(
                                GatedCandidateTransaction(mutating, snapshot),
                                (*trace, EffectRequestKind.PERSIST_JOURNAL),
                            ),
                        )
                    case ExpectedGateRefusal():
                        return _enter_rollback(mutating, trace)
            return _enter_rollback(mutating, trace)
        case (
            RollingBack(mutating=mutating, cursor=cursor, trace=trace),
            ObservedEffect(RollbackStepCompleted(operation_index=index, result=_)),
        ):
            if index != cursor.index or cursor.index < 0:
                return TransactionTerminal(
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE))
                )
            if cursor.index > 0:
                return TransactionInstruction(
                    AttemptRollbackOne(),
                    RollingBack(
                        mutating,
                        RollbackCursor(cursor.index - 1),
                        (*trace, EffectRequestKind.ATTEMPT_ROLLBACK_ONE),
                    ),
                )
            return TransactionInstruction(
                PersistJournal(JournalPhase.RESTORED),
                NeedRestoredJournal(
                    VerifiedRestoredTransaction(mutating),
                    (*trace, EffectRequestKind.PERSIST_JOURNAL),
                ),
            )
        case (
            NeedRestoredJournal(verified=verified, trace=trace),
            ObservedEffect(JournalPersisted(phase=JournalPhase.RESTORED)),
        ):
            restored = RestoredTransaction(verified)
            return TransactionInstruction(
                CleanOne(),
                CleaningRollback(
                    restored, CleanupCursor(0), (*trace, EffectRequestKind.CLEAN_ONE)
                ),
            )
        case (
            NeedSealedJournal(gated=gated, trace=trace),
            ObservedEffect(JournalPersisted(phase=JournalPhase.SEALED)),
        ):
            sealed = SealedTransaction(gated)
            return TransactionInstruction(
                CleanOne(),
                CleaningForward(
                    sealed, CleanupCursor(0), (*trace, EffectRequestKind.CLEAN_ONE)
                ),
            )
        case (
            CleaningForward(sealed=sealed, cursor=cursor, trace=trace),
            ObservedEffect(CleanupCompleted(cleanup_index=index)),
        ):
            plan = sealed.gated.mutating.planned.validated.locked.compiled.plan
            cleanup = derive_cleanup(plan, JournalPhase.SEALED)
            if index != cursor.index or cursor.index >= len(cleanup):
                return TransactionTerminal(
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE))
                )
            if cursor.index + 1 < len(cleanup):
                return TransactionInstruction(
                    CleanOne(),
                    CleaningForward(
                        sealed,
                        CleanupCursor(cursor.index + 1),
                        (*trace, EffectRequestKind.CLEAN_ONE),
                    ),
                )
            return TransactionInstruction(
                ReleaseLock(),
                Releasing(sealed, (*trace, EffectRequestKind.RELEASE_LOCK)),
            )
        case (
            CleaningRollback(restored=restored, cursor=cursor, trace=trace),
            ObservedEffect(CleanupCompleted(cleanup_index=index)),
        ):
            plan = restored.verified.mutating.planned.validated.locked.compiled.plan
            cleanup = derive_cleanup(plan, JournalPhase.RESTORED)
            if index != cursor.index or cursor.index >= len(cleanup):
                return TransactionTerminal(
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE))
                )
            if cursor.index + 1 < len(cleanup):
                return TransactionInstruction(
                    CleanOne(),
                    CleaningRollback(
                        restored,
                        CleanupCursor(cursor.index + 1),
                        (*trace, EffectRequestKind.CLEAN_ONE),
                    ),
                )
            return TransactionInstruction(
                ReleaseLock(),
                Releasing(restored, (*trace, EffectRequestKind.RELEASE_LOCK)),
            )
        case (
            Releasing(trace=trace),
            ObservedEffect(LockReleased()),
        ) if _awaits(trace, EffectRequestKind.RELEASE_LOCK):
            return TransactionTerminal(Completed(trace))
        case (
            _,  # pyright: ignore[reportAny] — subject tuple narrowing; the wildcard deliberately ignores the state
            ObservedEffect(EffectFailed(request_kind=kind, error=error)),
        ) if _awaits(_state_trace(state), kind):
            return TransactionTerminal(Stopped(_state_trace(state), error))
        case _:  # pyright: ignore[reportAny] — residual subject type after exhaustive narrowed cases
            return TransactionTerminal(
                Stopped(
                    _state_trace(state), InternalFailure(InternalCode.IMPOSSIBLE_STATE)
                )
            )
