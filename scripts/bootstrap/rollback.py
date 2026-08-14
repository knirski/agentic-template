"""Pure rollback and sealed-forward reducers for bootstrap recovery.

Every reducer is a total pure function of the journaled old/new identity and
the current observation: it either reports the terminal state, requests the
one exact shell action that restores or removes it, or reports a third state
that recovery must never overwrite.  The shell executes only the requested
action and never selects a rollback direction itself.

``RollbackStep``/``SealedStep`` expose the plan-level decision per operation;
the shell visits rollback steps in the exact reverse of the plan's dependency
order so removed parent directories are restored before their children and
created children disappear before a created parent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, assert_never

from scripts.bootstrap.identity import (
    DirectoryState,
    FileState,
    PosixMode,
    directory_tree_hash,
)
from scripts.bootstrap.journal import (
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
    FileAbsent,
    FileOperation,
    MaterializedTree,
    OperationPlan,
    PlannedFilePresent,
    PlannedFileState,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    TargetSnapshot,
)

_PLAN_TREE_HASH_KIND = (
    b"plan/tree"  # the tag the planner used for MaterializedTree identities
)

ABSENT_FILE_STATE = FileState(None, None)


def _planned_file_state(planned_new: PlannedFileState) -> FileState:
    match planned_new:
        case FileAbsent():
            return ABSENT_FILE_STATE
        case PlannedFilePresent(identity=identity, mode=mode):
            return FileState(identity=identity, mode=mode)
    return assert_never(
        planned_new
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _normalize_file(current: FileState | None) -> FileState:
    if current is None or not current.present:
        return ABSENT_FILE_STATE
    return current


@dataclass(frozen=True, slots=True)
class AlreadyRestored:
    pass


@dataclass(frozen=True, slots=True)
class RestoreOldFile:
    pass


@dataclass(frozen=True, slots=True)
class RollbackThirdState:
    observed: FileState | DirectoryState | None


type RollbackFileDecision = AlreadyRestored | RestoreOldFile | RollbackThirdState
type RollbackDirectoryDecision = (
    AlreadyRestored
    | RemoveCreatedTreeAtomically
    | RestoreEmptyDirectoryAtomically
    | RollbackThirdState
)


@dataclass(frozen=True, slots=True)
class RemoveCreatedTreeAtomically:
    pass


@dataclass(frozen=True, slots=True)
class RestoreEmptyDirectoryAtomically:
    pass


@dataclass(frozen=True, slots=True)
class AlreadyCandidate:
    pass


@dataclass(frozen=True, slots=True)
class SealedThirdState:
    observed: FileState | DirectoryState | None


type SealedFileDecision = AlreadyCandidate | SealedThirdState
type SealedDirectoryDecision = AlreadyCandidate | SealedThirdState


def rollback_file_step(
    expected_old: FileState, planned_new: PlannedFileState, current: FileState | None
) -> RollbackFileDecision:
    """Decide the rollback action for one file operation.

    ``AlreadyRestored`` when the observed state equals the exact pre-state,
    ``RestoreOldFile`` when it equals the planned candidate, and
    ``RollbackThirdState`` for anything else — recovery must preserve it.
    """

    observed = _normalize_file(current)
    if observed == expected_old:
        return AlreadyRestored()
    if observed == _planned_file_state(planned_new):
        return RestoreOldFile()
    return RollbackThirdState(observed)


def rollback_directory_step(
    operation: DirectoryOperation, current: DirectoryState | None
) -> RollbackDirectoryDecision:
    """Decide the rollback action for one directory operation.

    ``RemoveCreatedTreeAtomically`` applies only to ``CreateTree`` whose
    observed state equals the planned tree identity; ``RestoreEmptyDirectory``
    applies only to ``RemoveEmptyDirectory`` whose observed state is absence.
    """

    match operation:
        case CreateTreeOperation(expected_old=expected_old, planned_new=planned_tree):
            if current == expected_old:
                return AlreadyRestored()
            if current is not None and _tree_matches(planned_tree, current):
                return RemoveCreatedTreeAtomically()
            return RollbackThirdState(current)
        case RemoveEmptyDirectoryOperation(expected_old=expected_old):
            if current == expected_old:
                return AlreadyRestored()
            if current is None:
                return RestoreEmptyDirectoryAtomically()
            return RollbackThirdState(current)
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _tree_matches(planned_tree: MaterializedTree, current: DirectoryState) -> bool:
    return (
        directory_tree_hash(_PLAN_TREE_HASH_KIND, current)
        == planned_tree.raw_tree_sha256
    )


def sealed_file_step(
    planned_new: PlannedFileState, current: FileState | None
) -> SealedFileDecision:
    """Verify one file operation against its planned candidate without mutating."""

    observed = _normalize_file(current)
    if observed == _planned_file_state(planned_new):
        return AlreadyCandidate()
    return SealedThirdState(observed)


def sealed_directory_step(
    operation: DirectoryOperation, current: DirectoryState | None
) -> SealedDirectoryDecision:
    """Verify one directory operation against its planned candidate without mutating."""

    match operation:
        case CreateTreeOperation(planned_new=planned_tree):
            if current is not None and _tree_matches(planned_tree, current):
                return AlreadyCandidate()
            return SealedThirdState(current)
        case RemoveEmptyDirectoryOperation():
            if current is None:
                return AlreadyCandidate()
            return SealedThirdState(current)
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


@dataclass(frozen=True, slots=True)
class RollbackStep:
    operation_index: int
    path: RepoPath
    decision: RollbackFileDecision | RollbackDirectoryDecision


@dataclass(frozen=True, slots=True)
class SealedStep:
    operation_index: int
    path: RepoPath
    decision: SealedFileDecision | SealedDirectoryDecision


def _rollback_decision(
    operation: FileOperation | DirectoryOperation,
    files: dict[RepoPath, FileState],
    directories: dict[RepoPath, DirectoryState],
) -> RollbackFileDecision | RollbackDirectoryDecision:
    match operation:
        case CreateFileOperation(path=path, expected_old=expected, planned_new=planned):
            return rollback_file_step(expected, planned, files.get(path))
        case ReplaceFileOperation(
            path=path, expected_old=expected, planned_new=planned
        ):
            return rollback_file_step(expected, planned, files.get(path))
        case DeleteFileOperation(path=path, expected_old=expected, planned_new=planned):
            return rollback_file_step(expected, planned, files.get(path))
        case CreateTreeOperation(root=root):
            return rollback_directory_step(operation, directories.get(root))
        case RemoveEmptyDirectoryOperation(path=path):
            return rollback_directory_step(operation, directories.get(path))
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _sealed_decision(
    operation: FileOperation | DirectoryOperation,
    files: dict[RepoPath, FileState],
    directories: dict[RepoPath, DirectoryState],
) -> SealedFileDecision | SealedDirectoryDecision:
    match operation:
        case CreateFileOperation(path=path, planned_new=planned):
            return sealed_file_step(planned, files.get(path))
        case ReplaceFileOperation(path=path, planned_new=planned):
            return sealed_file_step(planned, files.get(path))
        case DeleteFileOperation(path=path, planned_new=planned):
            return sealed_file_step(planned, files.get(path))
        case CreateTreeOperation(root=root):
            return sealed_directory_step(operation, directories.get(root))
        case RemoveEmptyDirectoryOperation(path=path):
            return sealed_directory_step(operation, directories.get(path))
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def rollback_steps(
    plan: OperationPlan, snapshot: TargetSnapshot
) -> tuple[RollbackStep, ...]:
    """Decide the rollback action for every operation, in plan order.

    The shell executes the returned steps in reverse so that removed parents
    are restored before their children and created children disappear before
    a created parent.
    """

    files = {entry.path: entry.state for entry in snapshot.files}
    directories = {entry.path: entry.state for entry in snapshot.directories}
    return tuple(
        RollbackStep(
            index,
            _operation_path(operation),
            _rollback_decision(operation, files, directories),
        )
        for index, operation in enumerate(plan.ordered_operations)
    )


def sealed_steps(
    plan: OperationPlan, snapshot: TargetSnapshot
) -> tuple[SealedStep, ...]:
    """Verify every operation against its planned candidate, without mutation."""

    files = {entry.path: entry.state for entry in snapshot.files}
    directories = {entry.path: entry.state for entry in snapshot.directories}
    return tuple(
        SealedStep(
            index,
            _operation_path(operation),
            _sealed_decision(operation, files, directories),
        )
        for index, operation in enumerate(plan.ordered_operations)
    )


def _operation_path(operation: FileOperation | DirectoryOperation) -> RepoPath:
    match operation:
        case CreateFileOperation(path=path):
            return path
        case ReplaceFileOperation(path=path):
            return path
        case DeleteFileOperation(path=path):
            return path
        case CreateTreeOperation(root=root):
            return root
        case RemoveEmptyDirectoryOperation(path=path):
            return path
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


@dataclass(frozen=True, slots=True)
class RollbackSpec:
    """The journaled shape of one reserved rollback container."""

    operation_index: int
    role: PreparationRole
    expected_kind: Literal["file", "directory"]
    expected_raw_sha256: str | None
    expected_mode: PosixMode


def _rollback_specs_for_operation(
    operation: FileOperation | DirectoryOperation, index: int
) -> tuple[RollbackSpec, ...]:
    """Return the rollback container specs one operation needs to restore its old state."""

    match operation:
        case CreateFileOperation():
            return ()
        case ReplaceFileOperation(expected_old=expected):
            return _restore_spec(index, expected)
        case DeleteFileOperation(expected_old=expected):
            return _restore_spec(index, expected)
        case CreateTreeOperation(planned_new=planned_tree):
            return (
                RollbackSpec(
                    index,
                    PreparationRole.ROLLBACK,
                    "directory",
                    None,
                    planned_tree.root_mode,
                ),
            )
        case RemoveEmptyDirectoryOperation(expected_old=expected):
            return (
                RollbackSpec(
                    index,
                    PreparationRole.ROLLBACK,
                    "directory",
                    None,
                    expected.root_mode,
                ),
            )
    return assert_never(
        operation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _restore_spec(index: int, expected: FileState) -> tuple[RollbackSpec, ...]:
    old = _old_file_state(expected)
    if old is None:  # pragma: no cover — plans only replace or delete present files
        return ()
    old_digest, old_mode = old
    return (
        RollbackSpec(index, PreparationRole.ROLLBACK, "file", old_digest, old_mode),
    )


def derive_rollback_specs(plan: OperationPlan) -> tuple[RollbackSpec, ...]:
    """Derive the rollback containers every operation needs to restore its old state.

    Replaced or deleted files restore their raw backup into a marked adjacent
    container; created trees are renamed into one; removed empty directories
    are rebuilt inside one.  An originally absent file rolls back by removing
    the unchanged candidate and reserves no container.
    """

    return tuple(
        spec
        for index, operation in enumerate(plan.ordered_operations)
        for spec in _rollback_specs_for_operation(operation, index)
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


def derive_rollback_preparations(
    plan: OperationPlan,
    transaction_id: str,
    ownership_tokens: tuple[bytes, ...],
) -> tuple[PreparationIdentity, ...]:
    """Derive one journaled rollback-container identity per restoring operation."""

    specs = derive_rollback_specs(plan)
    if len(ownership_tokens) != len(specs):
        raise ValueError("one ownership token is required per rollback preparation")
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
