"""Shell effect execution for the deterministic transaction machine.

Every effect request the pure machine (``transaction.py``) emits is executed
here against the live target: preparation, apply, rollback, and cleanup use
descriptor-relative, symlink-rejecting filesystem primitives and journal
every transition through the state root.  This module is the imperative
shell; the machine never touches the filesystem.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import cast

from scripts.bootstrap.bundles import plan_snapshot_paths
from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.decisions import RecoveryDecision
from scripts.bootstrap.diagnostics import (
    ActionRequired,
    CommandOutcome,
    NotAttempted,
    RecoveryFailure,
    Succeeded,
    command_error_diagnostic,
    outcome_for_error,
)
from scripts.bootstrap.errors import (
    CommandError,
    InternalCode,
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
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
    list_directory_entries,
    map_observation_error,
    mkdir_parents_0755,
    open_regular_no_follow,
    read_file_bounded,
    walk_no_follow,
    write_file_exclusive,
)
from scripts.bootstrap.git_state import ResolvedGitWorktree
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
)
from scripts.bootstrap.intents import Intent, ProjectIntent
from scripts.bootstrap.journal import (
    JournalEnvelope,
    PreparationIdentity,
    PreparationRole,
    decode_journal,
    new_ownership_token,
    persist_journal,
)
from scripts.bootstrap.locking import LockGuard, acquire_lock, release_lock
from scripts.bootstrap.observation import (
    SystemObservation,
    observe_system,
    resolve_shell_target,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.plan_digest import reconstruct_plan
from scripts.bootstrap.planner import (
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
    TargetSnapshot,
)
from scripts.bootstrap.presentation import (
    CommandResult,
    _result,  # pyright: ignore[reportPrivateUsage]  shared result constructor with the presentation layer
)
from scripts.bootstrap.readiness import MechanicalReadinessResult
from scripts.bootstrap.recovery import (
    CleanupMissing,
    CleanupThirdState,
    CleanupVerified,
    ObservedArtifact,
    RestoredVerification,
    SealedVerification,
    ThirdStateFound,
    cleanup_step,
    restored_verification,
    sealed_verification,
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
from scripts.bootstrap.transaction import (
    AcquireLock,
    ApplyOne,
    AttemptRollbackOne,
    CleaningForward,
    CleaningRollback,
    CleanOne,
    CleanupCompleted,
    CompiledTransaction,
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
    TransactionEvent,
    TransactionInstruction,
    TransactionMachineState,
    TransactionOutcome,
    TransactionTerminal,
    ValidatedLockedTransaction,
    VerifiedRestoredTransaction,
    mutating_envelope,
    planned_envelope,
    request_kind,
    restored_envelope,
    sealed_envelope,
    step_transaction,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, JournalPhase, ResourceLimits

# ---------------------------------------------------------------------------
# Transaction effect execution and the machine driver
# ---------------------------------------------------------------------------


def _fsync_parent_of(
    resources: TransactionResources, path: RepoPath
) -> Result[None, EffectError]:
    """Durably persist the parent directory of one repository path."""

    return _fsync_dir_abs(
        os.path.join(resources.worktree.root_abs, *(_parent_components(path)))
    )


def _transaction_dir(resources: TransactionResources, transaction_id: str) -> bytes:
    return os.path.join(
        resources.worktree.state_root_abs,
        os.fsencode(f"transactions/{transaction_id}"),
    )


def _backups_path(resources: TransactionResources, transaction_id: str) -> bytes:
    return os.path.join(_transaction_dir(resources, transaction_id), b"backups")


def _prune_transaction_dirs(
    resources: TransactionResources, transaction_id: str
) -> Result[None, TransactionError]:
    """Remove the empty transaction containers up to the state root."""

    tx_dir = _transaction_dir(resources, transaction_id)
    try:
        for directory in (os.path.join(tx_dir, b"backups"), tx_dir):
            if os.path.isdir(directory) and not os.listdir(directory):
                os.rmdir(directory)
        transactions = os.path.join(resources.worktree.state_root_abs, b"transactions")
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


@contextlib.contextmanager
def _worktree_root_fd(
    resources: TransactionResources,
) -> Generator[int]:
    """Yield one symlink-rejecting descriptor on the worktree root, always closed."""

    fd = os.open(
        resources.worktree.root_abs,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        yield fd
    finally:
        os.close(fd)


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


def _create_marked_stage(
    resources: TransactionResources,
    operation: FileOperation | DirectoryOperation,
    transaction_id: str,
    operation_index: int,
    *,
    identity: PreparationIdentity,
    token: bytes,
    rollback: bool = False,
) -> Result[bytes, EffectError]:
    """Reserve one stage directory exclusively and write its ownership marker."""

    match _mkdir_stage_dir(
        resources, operation, transaction_id, operation_index, rollback=rollback
    ):
        case Err(error):
            return Err(error)
        case Ok(stage_dir):
            pass
    match _write_stage_marker(stage_dir, identity=identity, token=token):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    return Ok(stage_dir)


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

    with _worktree_root_fd(resources) as root_fd:
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
            case Ok(observed):
                pass
        if observed is None:
            return Ok(ObservedFileAbsent())
        content, mode, device, inode = observed
        return Ok(
            ObservedFilePresent(_observed_identity(content, mode), mode, device, inode)
        )


def capture_plan_snapshot(
    resources: TransactionResources, plan: OperationPlan
) -> Result[
    TargetSnapshot,
    ObservationError | CoreInternalFailure | TransactionError,
]:
    """Capture exactly the plan's referenced paths from the live target."""

    with _worktree_root_fd(resources) as root_fd:
        file_paths, dir_paths = plan_snapshot_paths(plan)
        observed_files: list[ObservedFileEntry] = []
        for path in sorted(file_paths, key=lambda p: p.value.encode("utf-8")):
            match _read_file_state_at(root_fd, path, resources.limits):
                case Err(error):
                    return Err(error)
                case Ok(observed):
                    pass
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
                case Err(ObservationError(kind=ObservationErrorKind.PATH_MISSING)):
                    # A missing intermediate directory means the whole path is
                    # absent: a deleted tree's nested directories are declared
                    # deletion targets too, so the post-mutation verification
                    # walks parents that are already gone.
                    continue
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
                match _create_marked_stage(
                    resources,
                    operation,
                    compiled.transaction_id,
                    identity.operation_index,
                    identity=identity,
                    token=token,
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(stage_dir):
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
                match _create_marked_stage(
                    resources,
                    operation,
                    compiled.transaction_id,
                    identity.operation_index,
                    identity=identity,
                    token=token,
                ):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(stage_dir):
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
                    match mkdir_parents_0755(
                        payload, tuple(os.fsencode(part) for part in parts)
                    ):
                        case Err(error):
                            return _err_effect(error)
                        case Ok(parent):
                            pass
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

            with _worktree_root_fd(resources) as root_fd:
                match _read_file_state_at(root_fd, operation.path, resources.limits):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(observed):
                        pass
            if observed is None:
                return _err_effect(_precondition_changed(operation.path.value))
            content, mode, _device, _inode = observed
            expected = operation.expected_old
            if not _old_file_matches(expected, content, mode):
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
            backups = _backups_path(resources, identity.transaction_id)
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


def _old_file_matches(expected: FileState, content: bytes, mode: PosixMode) -> bool:
    """Return whether observed bytes and mode equal the plan's expected old state."""

    return not (
        expected.identity is None
        or expected.mode is None
        or sha256_hex(content) != expected.identity.raw_sha256
        or mode != expected.mode
    )


def _verify_old_file(
    operation: FileOperation,
    resources: TransactionResources,
) -> Result[None, EffectError]:

    with _worktree_root_fd(resources) as root_fd:
        match _read_file_state_at(root_fd, operation.path, resources.limits):
            case Err(error):
                return _err_effect(error)
            case Ok(observed):
                pass
    expected = operation.expected_old
    if isinstance(operation, CreateFileOperation):
        if observed is not None:
            return _err_effect(_precondition_changed(operation.path.value))
        return Ok(None)
    if observed is None:
        return _err_effect(_precondition_changed(operation.path.value))
    content, mode, _device, _inode = observed
    if not _old_file_matches(expected, content, mode):
        return _err_effect(_precondition_changed(operation.path.value))
    return Ok(None)


def _execute_apply_one(
    operation: FileOperation | DirectoryOperation,
    compiled: CompiledTransaction,
    resources: TransactionResources,
) -> Result[ObservedPathState, EffectError]:

    with _worktree_root_fd(resources) as root_fd:
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
                match _fsync_parent_of(resources, operation.path):
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
                match _fsync_parent_of(resources, operation.path):
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
                match _fsync_parent_of(resources, operation.path):
                    case Err(error):
                        return _err_effect(error)
                    case Ok(_):
                        pass
                return _observe_path_state(resources, operation.path, directory=True)
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

    with _worktree_root_fd(resources) as root_fd:
        match _read_file_state_at(root_fd, operation.path, resources.limits):
            case Err(error):
                return _rollback_error(error)
            case Ok(observed):
                pass
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
        with _worktree_root_fd(resources) as root_fd:
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
    backups = _backups_path(resources, compiled.transaction_id)
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
    match _create_marked_stage(
        resources,
        operation,
        compiled.transaction_id,
        compiled.plan.ordered_operations.index(operation),
        identity=rollback_identity,
        token=resources.rollback_tokens[spec_index],
        rollback=True,
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(container):
            pass
    match _write_file_exclusive(
        container, os.fsencode(_PAYLOAD_NAME), backup_bytes, backup_mode.value
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(_):
            pass

    with _worktree_root_fd(resources) as root_fd:
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

    with _worktree_root_fd(resources) as root_fd:
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
    match _create_marked_stage(
        resources,
        operation,
        compiled.transaction_id,
        index,
        identity=rollback_identity,
        token=resources.rollback_tokens[spec_index],
        rollback=True,
    ):
        case Err(error):
            return _rollback_error(error)
        case Ok(container):
            pass

    with _worktree_root_fd(resources) as root_fd:
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
                _backups_path(resources, compiled.transaction_id),
                os.fsencode(str(operation_index)),
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
            match _prune_transaction_dirs(resources, compiled.transaction_id):
                case Err(error):
                    return Err(error)
                case Ok(_):
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
                    case Err(error):
                        if isinstance(error, TransitionError):
                            if error.kind is TransitionErrorKind.LOCK_HELD:
                                return LockRefused(error)
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


_STAGE_DIR_NAME = ".agentic-template-stage"
_MARKER_NAME = "marker"
_PAYLOAD_NAME = "payload"


def _execute_recover(  # pyright: ignore[reportUnusedFunction] — shared recovery executor, imported by the cli shell
    target: str | None,
    intent: Intent,
    *,
    template_root: str,
    limits: ResourceLimits,
) -> CommandResult:
    """Execute the phase-specific recovery reducer under the canonical lock."""

    command = "recover"
    match resolve_shell_target(target, cwd=os.getcwd()):
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

    decision = decide_project(cast(ProjectIntent, intent), observation.system)
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


def _verified_recovery(
    command: str,
    *,
    compiled: CompiledTransaction,
    resources: TransactionResources,
    verifier: Callable[
        [OperationPlan, TargetSnapshot], RestoredVerification | SealedVerification
    ],
) -> Result[TargetSnapshot, CommandResult]:
    """Capture the recovery snapshot and verify the phase terminal gate.

    Any observation that is not the exact phase state is a third state:
    recovery preserves it and reports ``RECOVERY_THIRD_STATE``.  The
    verified snapshot is returned for journal construction.
    """

    match capture_plan_snapshot(resources, compiled.plan):
        case Err(error):
            return Err(_result(command, _recovery_outcome(error)))
        case Ok(snapshot):
            pass
    match verifier(compiled.plan, snapshot):
        case ThirdStateFound(path=path):
            return Err(
                _result(
                    command,
                    _recovery_outcome(
                        TransitionError(
                            TransitionErrorKind.RECOVERY_THIRD_STATE, path.value
                        )
                    ),
                )
            )
        case _:
            return Ok(snapshot)


def _cleanup_recovery(
    command: str,
    *,
    compiled: CompiledTransaction,
    resources: TransactionResources,
    phase: JournalPhase,
) -> CommandResult | None:
    """Run the phase cleanup inventory; ``None`` means the phase completed."""

    match _cleanup_phase(compiled, phase, resources):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(_):
            return None


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
        match _verified_recovery(
            command,
            compiled=compiled,
            resources=resources,
            verifier=restored_verification,
        ):
            case Err(result):
                return result
            case Ok(snapshot):
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
        result = _cleanup_recovery(
            command,
            compiled=compiled,
            resources=resources,
            phase=JournalPhase.RESTORED,
        )
        if result is not None:
            return result
        return _recovery_succeeded(command)
    if isinstance(decision, FinishRollbackCleanup):
        match _verified_recovery(
            command,
            compiled=compiled,
            resources=resources,
            verifier=restored_verification,
        ):
            case Err(result):
                return result
            case Ok(_):
                pass
        result = _cleanup_recovery(
            command,
            compiled=compiled,
            resources=resources,
            phase=JournalPhase.RESTORED,
        )
        if result is not None:
            return result
        return _recovery_succeeded(command)
    if isinstance(decision, FinishForward):
        match _verified_recovery(
            command,
            compiled=compiled,
            resources=resources,
            verifier=sealed_verification,
        ):
            case Err(result):
                return result
            case Ok(_):
                pass
        result = _cleanup_recovery(
            command,
            compiled=compiled,
            resources=resources,
            phase=JournalPhase.SEALED,
        )
        if result is not None:
            return result
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
    match _prune_transaction_dirs(resources, envelope.transaction_id):
        case Err(error):
            return _result(command, _recovery_outcome(error))
        case Ok(_):
            pass
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


def _hook_not_attempted_reason(command: str) -> str:
    return f"not attempted by {command}"
