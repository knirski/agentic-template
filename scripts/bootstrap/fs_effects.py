"""Descriptor-relative filesystem shell effects for bootstrap transactions.

Every operation is anchored to a held directory descriptor and opens children
with ``O_NOFOLLOW``; symlink substitution anywhere in a walked path is a typed
failure.  Observation failures use ``ObservationError``; mutation and
state-root failures use ``TransactionError``.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from enum import StrEnum

from scripts.bootstrap.errors import (
    ErrnoClass,
    InternalCode,
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    sanitize_errno,
)
from scripts.bootstrap.result import Err, Ok, Result

_O_DIRECTORY = os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_O_NOFOLLOW_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


class ChildKind(StrEnum):
    ABSENT = "absent"
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ChildEntry:
    kind: ChildKind
    nlink: int | None = None


def map_observation_error(
    error: OSError, subject: str
) -> ObservationError | InternalFailure:
    """Map a descriptor-relative observation failure onto the closed vocabulary."""

    mapping = {
        errno.ENOENT: ObservationErrorKind.PATH_MISSING,
        errno.EACCES: ObservationErrorKind.PERMISSION_DENIED,
        errno.EPERM: ObservationErrorKind.PERMISSION_DENIED,
        errno.ELOOP: ObservationErrorKind.SYMLINK_ENCOUNTERED,
        errno.ENOTDIR: ObservationErrorKind.PATH_MISSING,
    }
    kind = mapping.get(error.errno)
    if kind is None:
        return InternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION)
    return ObservationError(kind, subject)


def _transaction_error(
    primitive: TransactionPrimitive, error: OSError, subject: str = ""
) -> TransactionError:
    return TransactionError.primitive_failed(primitive, sanitize_errno(error), subject)


def classify_child(
    dir_fd: int, name: bytes
) -> Result[ChildEntry, ObservationError | InternalFailure]:
    """Classify one no-follow child entry without opening it."""

    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return Ok(ChildEntry(kind=ChildKind.ABSENT))
    except OSError as error:
        return Err(map_observation_error(error, os.fsdecode(name)))
    if stat.S_ISREG(info.st_mode):
        return Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=info.st_nlink))
    if stat.S_ISDIR(info.st_mode):
        return Ok(ChildEntry(kind=ChildKind.DIRECTORY))
    if stat.S_ISLNK(info.st_mode):
        return Ok(ChildEntry(kind=ChildKind.SYMLINK))
    return Ok(ChildEntry(kind=ChildKind.OTHER))


def open_regular_no_follow(
    dir_fd: int, name: bytes
) -> Result[int, ObservationError | InternalFailure]:
    """Open a regular no-follow child for reading, rejecting every other shape."""

    match classify_child(dir_fd, name):
        case Err(error):
            return Err(error)
        case Ok(ChildEntry(kind=ChildKind.ABSENT)):
            return Err(
                ObservationError(ObservationErrorKind.PATH_MISSING, os.fsdecode(name))
            )
        case Ok(ChildEntry(kind=ChildKind.SYMLINK)):
            return Err(
                ObservationError(
                    ObservationErrorKind.SYMLINK_ENCOUNTERED, os.fsdecode(name)
                )
            )
        case Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=nlink)) if nlink != 1:
            return Err(
                ObservationError(
                    ObservationErrorKind.HARDLINK_ENCOUNTERED, os.fsdecode(name)
                )
            )
        case Ok(ChildEntry(kind=ChildKind.REGULAR)):
            try:
                return Ok(os.open(name, _O_NOFOLLOW_READ, dir_fd=dir_fd))
            except OSError as error:
                return Err(map_observation_error(error, os.fsdecode(name)))
        case Ok(_):
            return Err(
                ObservationError(
                    ObservationErrorKind.PATH_MISSING,
                    f"{os.fsdecode(name)} is not a regular file",
                )
            )


def walk_no_follow(
    root_fd: int,
    components: tuple[bytes, ...],
    *,
    allow_absent_final: bool = False,
) -> Result[int | None, ObservationError | InternalFailure]:
    """Walk ``components`` below ``root_fd`` returning the final directory fd.

    Every component is opened with ``O_DIRECTORY`` and ``O_NOFOLLOW``.  With
    ``allow_absent_final`` a missing final component returns ``None``; a
    missing intermediate component is always a failure.
    """

    current = root_fd
    opened: list[int] = []
    try:
        for position, component in enumerate(components):
            try:
                child = os.open(
                    component,
                    _O_DIRECTORY,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if position == len(components) - 1 and allow_absent_final:
                    return Ok(None)
                return Err(
                    ObservationError(
                        ObservationErrorKind.PATH_MISSING, os.fsdecode(component)
                    )
                )
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EISDIR):
                    # O_DIRECTORY|O_NOFOLLOW reports ENOTDIR for symlinks on
                    # some kernels; classify the child instead of guessing.
                    match classify_child(current, component):
                        case Ok(ChildEntry(kind=ChildKind.SYMLINK)):
                            return Err(
                                ObservationError(
                                    ObservationErrorKind.SYMLINK_ENCOUNTERED,
                                    os.fsdecode(component),
                                )
                            )
                        case Ok(_):
                            return Err(
                                ObservationError(
                                    ObservationErrorKind.PATH_MISSING,
                                    os.fsdecode(component),
                                )
                            )
                        case Err(classify_error):
                            return Err(classify_error)
                return Err(map_observation_error(error, os.fsdecode(component)))
            opened.append(child)
            current = child
        if not opened:
            return Ok(current)
        final_fd = opened.pop()
        return Ok(final_fd)
    finally:
        for fd in opened:
            os.close(fd)


def list_directory_entries(
    dir_fd: int,
) -> Result[tuple[bytes, ...], ObservationError | InternalFailure]:
    """List a held directory descriptor, resetting the readdir cursor first.

    On btrfs an ``fdopendir``-based listing is stale for entries created after
    the descriptor was opened; the explicit seek makes listing deterministic
    across filesystems.
    """

    try:
        os.lseek(dir_fd, 0, os.SEEK_SET)
    except OSError as error:
        return Err(map_observation_error(error, "directory listing"))
    try:
        names = sorted(os.listdir(dir_fd))
    except OSError as error:
        return Err(map_observation_error(error, "directory listing"))
    return Ok(tuple(os.fsencode(name) for name in names))


def ensure_state_root(parent_fd: int, name: bytes) -> Result[int, TransactionError]:
    """Create or open the administrative state-root directory with mode 0700.

    A symlink or non-directory final component is ``InvalidStateRoot``; the
    caller must hold the verified parent descriptor.
    """

    try:
        return Ok(os.open(name, _O_DIRECTORY, dir_fd=parent_fd))
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EISDIR):
            return Err(
                TransactionError(
                    TransactionErrorKind.INVALID_STATE_ROOT, subject=os.fsdecode(name)
                )
            )
        return Err(
            _transaction_error(
                TransactionPrimitive.CREATE_DIRECTORY, error, os.fsdecode(name)
            )
        )
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as error:
        return Err(
            _transaction_error(
                TransactionPrimitive.CREATE_DIRECTORY, error, os.fsdecode(name)
            )
        )
    try:
        return Ok(os.open(name, _O_DIRECTORY, dir_fd=parent_fd))
    except OSError as error:
        return Err(
            _transaction_error(
                TransactionPrimitive.CREATE_DIRECTORY, error, os.fsdecode(name)
            )
        )


def read_file_bounded(
    fd: int, max_bytes: int, subject: str = ""
) -> Result[bytes, ObservationError | InternalFailure]:
    """Read a regular file, failing closed when it exceeds the bound."""

    chunks: list[bytes] = []
    remaining = max_bytes + 1
    while remaining > 0:
        try:
            chunk = os.read(fd, min(64 * 1024, remaining))
        except OSError as error:
            return Err(map_observation_error(error, subject))
        if not chunk:
            return Ok(b"".join(chunks))
        chunks.append(chunk)
        remaining -= len(chunk)
    return Err(
        ObservationError(ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, subject)
    )


def write_all(fd: int, data: bytes) -> Result[None, TransactionError]:
    """Write the complete payload, handling partial writes explicitly."""

    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError as error:
            return Err(_transaction_error(TransactionPrimitive.WRITE_FILE, error))
        if written <= 0:
            return Err(
                TransactionError.primitive_failed(
                    TransactionPrimitive.WRITE_FILE,
                    ErrnoClass.SHORT_WRITE,
                )
            )
        view = view[written:]
    return Ok(None)


def fsync_file(fd: int) -> Result[None, TransactionError]:
    try:
        os.fsync(fd)
    except OSError as error:
        return Err(
            TransactionError(
                TransactionErrorKind.FSYNC_FAILED,
                errno_class=sanitize_errno(error),
            )
        )
    return Ok(None)


def fsync_directory(fd: int) -> Result[None, TransactionError]:
    """Durably persist directory entry changes for the held descriptor."""

    return fsync_file(fd)
