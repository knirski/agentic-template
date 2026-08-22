"""Never-unlinked flock-based state-root locking.

``state-root/lock`` is a regular file opened ``O_CREAT | O_RDWR | O_NOFOLLOW``
without ``O_EXCL`` and acquired with nonblocking ``flock``.  PID, operation,
and target identity are informational lock contents; flock ownership is
authoritative.  A dead process releases the flock, so its existing inode is
reused.  The lock file is never unlinked.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
from dataclasses import dataclass

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.errors import (
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
    sanitize_errno,
)
from scripts.bootstrap.fs_effects import write_all
from scripts.bootstrap.result import Err, Ok, Result

_LOCK_FLAGS = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class LockGuard:
    """The held lock; release by closing the descriptor, never by unlinking."""

    fd: int

    def __enter__(self) -> LockGuard:
        return self

    def __exit__(self, *exc: object) -> None:
        release_lock(self)


def _primitive_failed(error: OSError, subject: str) -> TransactionError:
    return TransactionError.primitive_failed(
        TransactionPrimitive.WRITE_FILE, sanitize_errno(error), subject
    )


def _try_acquire(
    fd: int, *, operation: str, target_digest: str
) -> Result[LockGuard, TransitionError | ObservationError | TransactionError]:
    """Acquire and label an already-opened lock descriptor."""

    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except InterruptedError:
            continue
        except OSError as error:
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                return Err(TransitionError(TransitionErrorKind.LOCK_HELD, "lock"))
            if error.errno in (errno.ENOTSUP, errno.EINVAL, errno.ENOLCK):
                return Err(
                    ObservationError(
                        ObservationErrorKind.UNSUPPORTED_FILESYSTEM, "flock"
                    )
                )
            return Err(_primitive_failed(error, "flock"))
    content = canonical_json(
        {"pid": os.getpid(), "operation": operation, "target": target_digest}
    )
    try:
        os.ftruncate(fd, 0)
    except OSError as error:
        return Err(_primitive_failed(error, "lock content"))
    match write_all(fd, content):
        case Err(error):
            return Err(error)
        case Ok(_):
            return Ok(LockGuard(fd=fd))


def acquire_lock(
    state_root_fd: int,
    *,
    operation: str,
    target_digest: str,
) -> Result[LockGuard, TransitionError | ObservationError | TransactionError]:
    """Acquire the canonical state-root lock without blocking.

    The descriptor is closed on every failed acquisition; only the returned
    ``LockGuard`` keeps it open.
    """

    try:
        fd = os.open("lock", _LOCK_FLAGS, 0o600, dir_fd=state_root_fd)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.EISDIR, errno.ENOTDIR):
            return Err(
                TransactionError(
                    TransactionErrorKind.INVALID_STATE_ROOT, subject="lock"
                )
            )
        return Err(_primitive_failed(error, "lock"))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(fd)
            return Err(
                TransactionError(
                    TransactionErrorKind.INVALID_STATE_ROOT, subject="lock"
                )
            )
        outcome = _try_acquire(fd, operation=operation, target_digest=target_digest)
    except BaseException:
        os.close(fd)
        raise
    match outcome:
        case Ok(guard):
            return Ok(guard)
        case Err(_):
            os.close(fd)
            return outcome


def release_lock(guard: LockGuard) -> None:
    """Release the lock; closing the descriptor drops the flock and reuses the inode."""

    os.close(guard.fd)
