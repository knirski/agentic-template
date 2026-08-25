"""Git state-root resolution effects for verified worktree targets.

State resolution is exactly: try ``git rev-parse --path-format=absolute
--git-path rygor``; retry with plain ``--git-path`` resolved against
the worktree root when and only when Git reports ``--path-format`` unsupported;
independently obtain ``--absolute-git-dir`` and require the state-root result
to equal its ``rygor`` child; then re-verify the state-root path
descriptor-relatively.  Linked worktrees and submodules therefore resolve
independent state roots; bare repositories, non-worktrees, and unavailable Git
are typed target failures.
"""

from __future__ import annotations

import errno
import os
import posixpath
import stat
from collections.abc import Callable
from dataclasses import dataclass

from scripts.bootstrap.errors import (
    InternalCode,
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
)
from scripts.bootstrap.fs_effects import walk_no_follow
from scripts.bootstrap.identity import TargetIdentity, target_identity
from scripts.bootstrap.process_effects import (
    Launched,
    LaunchFailed,
    TimedOut,
    run_captured,
    signalled,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import TargetReason, UnsupportedGitTarget

GIT_COMMAND_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True, slots=True)
class ResolvedGitWorktree:
    """Shell-side verified resolution facts for one worktree root."""

    root_abs: bytes
    git_dir_abs: bytes
    state_root_abs: bytes
    target: TargetIdentity


type GitTargetResolution = UnsupportedGitTarget | ResolvedGitWorktree

type GitRunner = Callable[
    [tuple[str, ...]],
    Result[GitCommandResult, UnsupportedGitTarget | ObservationError | InternalFailure],
]


def run_git(
    args: tuple[str, ...],
    *,
    cwd: bytes,
    timeout: float = GIT_COMMAND_TIMEOUT,
    env: dict[str, str] | None = None,
) -> Result[
    GitCommandResult, UnsupportedGitTarget | ObservationError | InternalFailure
]:
    """Run one bounded git command; every ordinary exit is a result value."""

    match run_captured(["git", *args], cwd=cwd, env=env, timeout=timeout):
        case LaunchFailed(filename=filename):
            return Err(UnsupportedGitTarget(_launch_target_reason(filename, cwd)))
        case TimedOut():
            return Err(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
        case Launched(returncode=returncode, stdout=stdout, stderr=stderr):
            pass
    if returncode < 0:
        match signalled(returncode):
            case signal if signal is not None:
                return Err(
                    ObservationError(
                        ObservationErrorKind.PROCESS_SIGNALLED,
                        signal=signal,
                    )
                )
            case _:
                return Err(InternalFailure(InternalCode.IMPOSSIBLE_STATE))
    return Ok(
        GitCommandResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
    )


def _launch_target_reason(filename: str | bytes | None, cwd: bytes) -> TargetReason:
    """Classify a git launch failure by the path that failed to resolve.

    A missing or non-directory working directory is a target problem; a
    missing or non-executable ``git`` executable is an environment problem.
    """

    if filename is not None and os.fsdecode(filename) == os.fsdecode(cwd):
        return TargetReason.NOT_WORKTREE
    return TargetReason.GIT_UNAVAILABLE


def _reports_true(result: GitCommandResult) -> bool:
    return result.returncode == 0 and result.stdout.strip() == b"true"


def _target_error(
    error: UnsupportedGitTarget | ObservationError | InternalFailure,
) -> Result[GitTargetResolution, ObservationError | InternalFailure]:
    match error:
        case UnsupportedGitTarget():
            return Ok(error)
        case ObservationError() | InternalFailure():
            return Err(error)


def resolve_git_worktree(
    root_abs: bytes,
    *,
    runner: GitRunner | None = None,
) -> Result[GitTargetResolution, ObservationError | InternalFailure]:
    """Resolve and verify the per-worktree administrative state root."""

    run: GitRunner = (
        runner if runner is not None else (lambda args: run_git(args, cwd=root_abs))
    )

    match run(("rev-parse", "--is-inside-work-tree")):
        case Err(error):
            return _target_error(error)
        case Ok(result) if result.returncode != 0 or result.stdout.strip() != b"true":
            match run(("rev-parse", "--is-bare-repository")):
                case Err(error):
                    return _target_error(error)
                case Ok(bare) if _reports_true(bare):
                    return Ok(UnsupportedGitTarget(TargetReason.BARE_REPOSITORY))
                case Ok(_):
                    return Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
        case Ok(_):
            pass

    match run(("rev-parse", "--path-format=absolute", "--git-path", "rygor")):
        case Err(error):
            return _target_error(error)
        case Ok(result) if result.returncode == 0:
            state_root_abs = result.stdout.strip()
        case Ok(result) if b"path-format" in result.stderr:
            match run(("rev-parse", "--git-path", "rygor")):
                case Err(error):
                    return _target_error(error)
                case Ok(fallback) if fallback.returncode != 0:
                    return Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
                case Ok(fallback):
                    relative = fallback.stdout.strip()
                    state_root_abs = posixpath.normpath(
                        posixpath.join(root_abs, relative)
                    )
        case Ok(_):
            return Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))

    match run(("rev-parse", "--absolute-git-dir")):
        case Err(error):
            return _target_error(error)
        case Ok(result) if result.returncode != 0:
            return Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
        case Ok(result):
            git_dir_abs = result.stdout.strip()

    expected = posixpath.normpath(posixpath.join(git_dir_abs, b"rygor"))
    if posixpath.normpath(state_root_abs) != expected:
        return Err(
            ObservationError(
                ObservationErrorKind.GIT_COMMAND_FAILED,
                "state-root and git-dir resolution disagree",
            )
        )

    root_fd = os.open(b"/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        components = tuple(part for part in state_root_abs.split(b"/") if part)
        match walk_no_follow(root_fd, components, allow_absent_final=True):
            case Err(error):
                return Err(error)
            case Ok(fd):
                if fd is not None:
                    os.close(fd)
    finally:
        os.close(root_fd)

    try:
        info = os.stat(root_abs, follow_symlinks=False)
    except OSError as error:
        return Err(_stat_error(error, root_abs))
    if stat.S_ISLNK(info.st_mode):
        return Err(
            ObservationError(
                ObservationErrorKind.SYMLINK_ENCOUNTERED, os.fsdecode(root_abs)
            )
        )
    target = target_identity(root_abs, device=info.st_dev, inode=info.st_ino)
    return Ok(
        ResolvedGitWorktree(
            root_abs=root_abs,
            git_dir_abs=git_dir_abs,
            state_root_abs=state_root_abs,
            target=target,
        )
    )


def _stat_error(error: OSError, subject: bytes) -> ObservationError | InternalFailure:
    mapping = {
        errno.ENOENT: ObservationErrorKind.PATH_MISSING,
        errno.EACCES: ObservationErrorKind.PERMISSION_DENIED,
        errno.EPERM: ObservationErrorKind.PERMISSION_DENIED,
        errno.ELOOP: ObservationErrorKind.SYMLINK_ENCOUNTERED,
    }
    errno_value = error.errno
    if errno_value is None:
        return InternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION)
    kind = mapping.get(errno_value)
    if kind is None:
        return InternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION)
    return ObservationError(kind, os.fsdecode(subject))
