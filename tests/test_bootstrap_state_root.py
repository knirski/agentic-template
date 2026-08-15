"""State-root resolution, never-unlinked locking, journal persistence, and fs effects.

Covers batch 5 validation: linked-worktree independence, submodule and
bare/non-worktree cases, lock reuse after process death, stale
pending/orphan/corrupt journal behavior, path substitution and no-follow
checks, and state-root durability and evidence preservation.
"""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import posixpath
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Literal, TextIO, cast
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from scripts.bootstrap.errors import (
    ErrnoClass,
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
    SignalNumber,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
)
from scripts.bootstrap.fs_effects import (
    ChildKind,
    classify_child,
    ensure_state_root,
    fsync_directory,
    fsync_file,
    list_directory_entries,
    map_observation_error,
    mkdir_parents_0755,
    open_regular_no_follow,
    read_file_bounded,
    walk_no_follow,
    write_all,
)
from scripts.bootstrap.git_state import (
    GitCommandResult,
    ResolvedGitWorktree,
    _stat_error,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    resolve_git_worktree,
    run_git,
)
from scripts.bootstrap.identity import PosixMode, TargetIdentity, target_identity
from scripts.bootstrap.journal import (
    JournalEnvelope,
    JournalTarget,
    PreparationIdentity,
    PreparationRole,
    StateRootSnapshot,
    backup_relative_path,
    capture_state_root,
    classify_state_root,
    collect_state_root_observation,
    decode_journal,
    derive_preparation_identity,
    encode_journal,
    new_ownership_token,
    new_transaction_id,
    persist_journal,
)
from scripts.bootstrap.locking import acquire_lock, release_lock
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import (
    InvalidJournal,
    JournalTargetMismatch,
    NoJournal,
    OrphanTransactionState,
    PendingIdentity,
    StaleJournalWrite,
    TargetReason,
    UnsupportedGitTarget,
    ValidatedJournal,
)
from scripts.bootstrap.values import JournalPhase, ResourceLimits

O_DIRECTORY = os.O_DIRECTORY | os.O_RDONLY | os.O_CLOEXEC


def _ok[ValueT, ErrorT](result: Result[ValueT, ErrorT]) -> ValueT:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise AssertionError(f"expected Ok, got Err({error!r})")


def _err[ValueT, ErrorT](result: Result[ValueT, ErrorT]) -> ErrorT:
    match result:
        case Err(error):
            return error
        case Ok(value):
            raise AssertionError(f"expected Err, got Ok({value!r})")


def _open_dir(path: str) -> int:
    return os.open(path, O_DIRECTORY)


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as handle:
        _ = handle.write(data)


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class FsEffectsTests(unittest.TestCase):
    def test_walk_returns_fd_of_final_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "a", "b", "c"))
            fd = _ok(walk_no_follow(_open_dir(tmp), (b"a", b"b", b"c")))
            assert fd is not None
            _write(os.path.join(tmp, "a", "b", "c", "f"), b"x")
            _ = os.lseek(fd, 0, os.SEEK_SET)
            self.assertEqual(os.listdir(fd), ["f"])

    def test_walk_rejects_missing_intermediate_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = cast(
                ObservationError, _err(walk_no_follow(_open_dir(tmp), (b"a", b"b")))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_walk_rejects_symlink_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "real"))
            os.symlink(os.path.join(tmp, "real"), os.path.join(tmp, "link"))
            error = cast(
                ObservationError,
                _err(walk_no_follow(_open_dir(tmp), (b"link", b"child"))),
            )
            self.assertEqual(error.kind, ObservationErrorKind.SYMLINK_ENCOUNTERED)

    def test_observation_error_without_errno_is_internal_failure(self) -> None:
        # An OSError raised from a bare message carries errno=None; the closed
        # vocabulary must map it to InternalFailure rather than an unmapped
        # ObservationError kind.
        mapped = map_observation_error(OSError("no errno attached"), "subject")
        self.assertIsInstance(mapped, InternalFailure)

    def test_mkdir_parents_creates_prefixes_and_returns_leaf_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = _ok(mkdir_parents_0755(os.fsencode(tmp), (b"a", b"b", b"leaf")))
            self.assertEqual(os.fsdecode(parent), os.path.join(tmp, "a", "b"))
            self.assertTrue(os.path.isdir(os.path.join(tmp, "a", "b")))
            self.assertEqual(
                stat.S_IMODE(os.stat(os.path.join(tmp, "a", "b")).st_mode), 0o755
            )
            self.assertFalse(os.path.exists(os.path.join(tmp, "a", "b", "leaf")))

    def test_mkdir_parents_tolerates_existing_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "a"))
            parent = _ok(mkdir_parents_0755(os.fsencode(tmp), (b"a", b"b", b"leaf")))
            self.assertEqual(os.fsdecode(parent), os.path.join(tmp, "a", "b"))

    def test_mkdir_parents_rejects_oversized_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = _err(mkdir_parents_0755(os.fsencode(tmp), (b"x" * 300, b"leaf")))
            self.assertEqual(error.primitive, TransactionPrimitive.CREATE_DIRECTORY)

    def test_mkdir_parents_maps_chmod_failure_to_create_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "scripts.bootstrap.fs_effects.os.chmod",
                side_effect=OSError(errno.EPERM, "permission denied"),
            ):
                error = _err(mkdir_parents_0755(os.fsencode(tmp), (b"a", b"leaf")))
            self.assertEqual(error.primitive, TransactionPrimitive.CREATE_DIRECTORY)

    def test_stat_error_without_errno_is_internal_failure(self) -> None:
        # Same guarantee for the git-state stat path: an errno-less OSError
        # must not produce an unbounded ObservationError kind.
        mapped = _stat_error(OSError("no errno attached"), b"subject")
        self.assertIsInstance(mapped, InternalFailure)

    def test_walk_rejects_symlink_final_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "real"))
            os.symlink(os.path.join(tmp, "real"), os.path.join(tmp, "link"))
            error = cast(
                ObservationError, _err(walk_no_follow(_open_dir(tmp), (b"link",)))
            )
            self.assertEqual(error.kind, ObservationErrorKind.SYMLINK_ENCOUNTERED)

    def test_walk_allows_absent_final_component(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = walk_no_follow(
                _open_dir(tmp), (b"missing",), allow_absent_final=True
            )
            self.assertEqual(result, Ok(None))

    def test_classify_child_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"x")
            os.mkdir(os.path.join(tmp, "d"))
            os.symlink(os.path.join(tmp, "f"), os.path.join(tmp, "l"))
            os.mkfifo(os.path.join(tmp, "p"))
            fd = _open_dir(tmp)
            self.assertEqual(_ok(classify_child(fd, b"f")).kind, ChildKind.REGULAR)
            self.assertEqual(_ok(classify_child(fd, b"d")).kind, ChildKind.DIRECTORY)
            self.assertEqual(_ok(classify_child(fd, b"l")).kind, ChildKind.SYMLINK)
            self.assertEqual(_ok(classify_child(fd, b"p")).kind, ChildKind.OTHER)
            self.assertEqual(_ok(classify_child(fd, b"absent")).kind, ChildKind.ABSENT)

    def test_open_regular_reads_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"content")
            fd = _ok(open_regular_no_follow(_open_dir(tmp), b"f"))
            self.assertEqual(os.read(fd, 64), b"content")

    def test_open_regular_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"x")
            os.symlink(os.path.join(tmp, "f"), os.path.join(tmp, "l"))
            error = cast(
                ObservationError, _err(open_regular_no_follow(_open_dir(tmp), b"l"))
            )
            self.assertEqual(error.kind, ObservationErrorKind.SYMLINK_ENCOUNTERED)

    def test_open_regular_rejects_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"x")
            os.link(os.path.join(tmp, "f"), os.path.join(tmp, "h"))
            error = cast(
                ObservationError, _err(open_regular_no_follow(_open_dir(tmp), b"h"))
            )
            self.assertEqual(error.kind, ObservationErrorKind.HARDLINK_ENCOUNTERED)

    def test_open_regular_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "d"))
            error = cast(
                ObservationError, _err(open_regular_no_follow(_open_dir(tmp), b"d"))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_open_regular_missing_is_path_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = cast(
                ObservationError,
                _err(open_regular_no_follow(_open_dir(tmp), b"absent")),
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_read_file_bounded_returns_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"abc")
            fd = os.open(os.path.join(tmp, "f"), os.O_RDONLY)
            try:
                self.assertEqual(_ok(read_file_bounded(fd, 16)), b"abc")
            finally:
                os.close(fd)

    def test_read_file_bounded_rejects_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"abc")
            fd = os.open(os.path.join(tmp, "f"), os.O_RDONLY)
            try:
                error = cast(ObservationError, _err(read_file_bounded(fd, 2)))
                self.assertEqual(
                    error.kind, ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED
                )
            finally:
                os.close(fd)

    def test_write_all_writes_complete_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "f"), os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
            try:
                self.assertEqual(_ok(write_all(fd, b"payload")), None)
            finally:
                os.close(fd)
            self.assertEqual(_read(os.path.join(tmp, "f")), b"payload")

    def test_open_regular_rejects_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "f"), b"x")
            os.chmod(os.path.join(tmp, "f"), 0o000)
            error = cast(
                ObservationError, _err(open_regular_no_follow(_open_dir(tmp), b"f"))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_ensure_state_root_rejects_unwritable_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o500)
            error = _err(ensure_state_root(_open_dir(tmp), b"state-root"))
            self.assertEqual(error.kind, TransactionErrorKind.PRIMITIVE_FAILED)
            self.assertEqual(error.primitive, TransactionPrimitive.CREATE_DIRECTORY)

    def test_classify_child_rejects_unsearchable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "d"))
            fd = _open_dir(os.path.join(tmp, "d"))
            os.chmod(os.path.join(tmp, "d"), 0o400)
            error = cast(ObservationError, _err(classify_child(fd, b"x")))
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_fsync_file_and_directory_succeed_on_real_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "f"), os.O_CREAT | os.O_WRONLY)
            try:
                self.assertEqual(_ok(fsync_file(fd)), None)
            finally:
                os.close(fd)
            self.assertEqual(_ok(fsync_directory(_open_dir(tmp))), None)

    def test_ensure_state_root_creates_with_mode_0700(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = _ok(ensure_state_root(_open_dir(tmp), b"state-root"))
            self.assertEqual(os.listdir(tmp), ["state-root"])
            mode = stat.S_IMODE(os.stat(os.path.join(tmp, "state-root")).st_mode)
            self.assertEqual(mode, 0o700)
            os.close(fd)

    def test_ensure_state_root_opens_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "state-root"), 0o700)
            fd = _ok(ensure_state_root(_open_dir(tmp), b"state-root"))
            os.close(fd)

    def test_ensure_state_root_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.mkdir(os.path.join(tmp, "real"))
            os.symlink(os.path.join(tmp, "real"), os.path.join(tmp, "state-root"))
            error = _err(ensure_state_root(_open_dir(tmp), b"state-root"))
            self.assertEqual(error.kind, TransactionErrorKind.INVALID_STATE_ROOT)

    def test_ensure_state_root_rejects_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "state-root"), b"x")
            error = _err(ensure_state_root(_open_dir(tmp), b"state-root"))
            self.assertEqual(error.kind, TransactionErrorKind.INVALID_STATE_ROOT)

    def test_classify_child_on_closed_descriptor_is_internal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = _open_dir(tmp)
            os.close(fd)
            error = _err(classify_child(fd, b"f"))
            self.assertIsInstance(error, InternalFailure)

    def test_open_regular_rejects_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.mkfifo(os.path.join(tmp, "p"))
            error = cast(
                ObservationError, _err(open_regular_no_follow(_open_dir(tmp), b"p"))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)
            self.assertIn("not a regular file", error.subject)

    def test_open_regular_propagates_classify_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = _open_dir(tmp)
            os.close(fd)
            self.assertIsInstance(
                _err(open_regular_no_follow(fd, b"f")), InternalFailure
            )

    def test_walk_regular_file_intermediate_is_path_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write(os.path.join(tmp, "file"), b"x")
            error = cast(
                ObservationError,
                _err(walk_no_follow(_open_dir(tmp), (b"file", b"child"))),
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_walk_oversized_component_is_internal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            error = _err(walk_no_follow(_open_dir(tmp), (b"x" * 300,)))
            self.assertIsInstance(error, InternalFailure)

    def test_walk_empty_components_returns_root_fd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_fd = _open_dir(tmp)
            result = walk_no_follow(root_fd, ())
            self.assertEqual(result, Ok(root_fd))

    def test_list_directory_entries_on_closed_descriptor_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = _open_dir(tmp)
            os.close(fd)
            self.assertIsInstance(_err(list_directory_entries(fd)), InternalFailure)

    def test_ensure_state_root_on_closed_descriptor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = _open_dir(tmp)
            os.close(fd)
            error = _err(ensure_state_root(fd, b"state-root"))
            self.assertEqual(error.kind, TransactionErrorKind.PRIMITIVE_FAILED)
            self.assertEqual(error.primitive, TransactionPrimitive.CREATE_DIRECTORY)

    def test_read_file_bounded_on_closed_descriptor_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "f"), os.O_CREAT | os.O_RDONLY)
            os.close(fd)
            self.assertIsInstance(_err(read_file_bounded(fd, 16)), InternalFailure)

    def test_write_all_on_closed_descriptor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "f"), os.O_CREAT | os.O_WRONLY)
            os.close(fd)
            error = _err(write_all(fd, b"x"))
            self.assertEqual(error.kind, TransactionErrorKind.PRIMITIVE_FAILED)
            self.assertEqual(error.primitive, TransactionPrimitive.WRITE_FILE)

    def test_fsync_on_closed_descriptor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fd = os.open(os.path.join(tmp, "f"), os.O_CREAT | os.O_WRONLY)
            os.close(fd)
            self.assertEqual(
                _err(fsync_file(fd)).kind, TransactionErrorKind.FSYNC_FAILED
            )
            dir_fd = _open_dir(tmp)
            os.close(dir_fd)
            self.assertEqual(
                _err(fsync_directory(dir_fd)).kind, TransactionErrorKind.FSYNC_FAILED
            )


class LockingTests(unittest.TestCase):
    def _state_root(self, tmp: str) -> int:
        parent = _open_dir(tmp)
        state = _ok(ensure_state_root(parent, b"state-root"))
        return state

    def test_acquire_and_release_never_unlinks_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            guard = _ok(acquire_lock(state, operation="apply", target_digest="d" * 64))
            release_lock(guard)
            self.assertEqual(os.listdir(os.path.join(tmp, "state-root")), ["lock"])
            reacquired = _ok(
                acquire_lock(state, operation="apply", target_digest="d" * 64)
            )
            release_lock(reacquired)

    def test_second_acquire_while_held_is_lock_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            first = _ok(acquire_lock(state, operation="apply", target_digest="d" * 64))
            second = acquire_lock(state, operation="apply", target_digest="d" * 64)
            match second:
                case Err(error):
                    self.assertEqual(error.kind, TransitionErrorKind.LOCK_HELD)
                case Ok(_):
                    raise AssertionError("second acquire succeeded while held")
            release_lock(first)
            third = _ok(acquire_lock(state, operation="apply", target_digest="d" * 64))
            release_lock(third)

    def test_lock_content_is_informational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            guard = _ok(acquire_lock(state, operation="apply", target_digest="ab" * 32))
            try:
                content = cast(
                    dict[str, object],
                    json.loads(_read(os.path.join(tmp, "state-root", "lock"))),
                )
            finally:
                release_lock(guard)
            self.assertEqual(content["operation"], "apply")
            self.assertEqual(content["target"], "ab" * 32)
            self.assertEqual(content["pid"], os.getpid())

    def test_lock_reuse_after_process_death(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            lock_path = os.path.join(tmp, "state-root", "lock")
            script = (
                "import fcntl, os, sys, time\n"
                "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR)\n"
                "fcntl.flock(fd, fcntl.LOCK_EX)\n"
                "print('READY', flush=True)\n"
                "time.sleep(2)\n"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", script, lock_path],
                stdout=subprocess.PIPE,
                text=True,
            )
            stdout = child.stdout
            assert stdout is not None
            stdout = cast(TextIO, stdout)
            try:
                self.assertEqual(stdout.readline().strip(), "READY")
                deadline = time.monotonic() + 5
                held: TransitionError | None = None
                while time.monotonic() < deadline:
                    attempt = acquire_lock(
                        state, operation="apply", target_digest="d" * 64
                    )
                    if isinstance(attempt, Err):
                        if isinstance(attempt.error, TransitionError):
                            held = attempt.error
                            break
                        self.fail(f"unexpected lock error: {attempt.error!r}")
                    release_lock(attempt.value)
                    time.sleep(0.02)
                self.assertIsNotNone(held)
                assert held is not None
                self.assertEqual(held.kind, TransitionErrorKind.LOCK_HELD)
            finally:
                _ = child.wait(timeout=10)
            reacquired = _ok(
                acquire_lock(state, operation="apply", target_digest="d" * 64)
            )
            release_lock(reacquired)

    def test_lock_context_manager_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            with _ok(acquire_lock(state, operation="apply", target_digest="d" * 64)):
                pass
            again = _ok(acquire_lock(state, operation="apply", target_digest="d" * 64))
            release_lock(again)

    def test_lock_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "elsewhere"), b"x")
            os.symlink(
                os.path.join(tmp, "elsewhere"), os.path.join(tmp, "state-root", "lock")
            )
            error = _err(acquire_lock(state, operation="apply", target_digest="d" * 64))
            self.assertEqual(error.kind, TransactionErrorKind.INVALID_STATE_ROOT)

    def test_lock_on_closed_state_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.close(state)
            error = cast(
                TransactionError,
                _err(acquire_lock(state, operation="apply", target_digest="d" * 64)),
            )
            self.assertEqual(error.kind, TransactionErrorKind.PRIMITIVE_FAILED)
            self.assertEqual(error.primitive, TransactionPrimitive.WRITE_FILE)
            self.assertEqual(error.errno_class, ErrnoClass.OTHER_SANITIZED_ERRNO)

    def test_failed_acquisitions_do_not_leak_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            first = _ok(acquire_lock(state, operation="apply", target_digest="d" * 64))
            try:
                before = len(os.listdir("/proc/self/fd"))
                for _ in range(50):
                    error = _err(
                        acquire_lock(state, operation="apply", target_digest="d" * 64)
                    )
                    self.assertEqual(error.kind, TransitionErrorKind.LOCK_HELD)
                after = len(os.listdir("/proc/self/fd"))
                self.assertEqual(after, before)
            finally:
                release_lock(first)


class GitStateTests(unittest.TestCase):
    def _git(
        self, *args: str, cwd: str | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            check=False,
        )

    def _init_repo(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        _ = self._git("init", "-q", path)
        _ = self._git("config", "user.email", "test@example.com", cwd=path)
        _ = self._git("config", "user.name", "Test", cwd=path)

    def test_resolves_state_root_of_real_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            _write(os.path.join(repo, "f"), b"x")
            _ = self._git("add", "f", cwd=repo)
            _ = self._git("commit", "-qm", "init", cwd=repo)
            root = os.fsencode(repo)
            result = resolve_git_worktree(root)
            assert isinstance(result, Ok)
            resolved = result.value
            assert isinstance(resolved, ResolvedGitWorktree)
            git_dir = self._git(
                "rev-parse", "--absolute-git-dir", cwd=repo
            ).stdout.strip()
            expected = posixpath.join(git_dir, b"agentic-template")
            self.assertEqual(resolved.state_root_abs, expected)
            st = os.stat(repo, follow_symlinks=False)
            self.assertEqual(resolved.target.root_os_bytes, root)
            self.assertEqual(resolved.target.device, st.st_dev)
            self.assertEqual(resolved.target.inode, st.st_ino)

    def test_state_root_may_be_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            _write(os.path.join(repo, "f"), b"x")
            _ = self._git("add", "f", cwd=repo)
            _ = self._git("commit", "-qm", "init", cwd=repo)
            resolved = _ok(resolve_git_worktree(os.fsencode(repo)))
            assert isinstance(resolved, ResolvedGitWorktree)
            self.assertFalse(os.path.exists(resolved.state_root_abs))

    def test_linked_worktrees_have_independent_state_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            _write(os.path.join(repo, "f"), b"x")
            _ = self._git("add", "f", cwd=repo)
            _ = self._git("commit", "-qm", "init", cwd=repo)
            other = os.path.join(tmp, "other")
            _ = self._git("worktree", "add", "-q", other, cwd=repo)
            first = _ok(resolve_git_worktree(os.fsencode(repo)))
            second = _ok(resolve_git_worktree(os.fsencode(other)))
            assert isinstance(first, ResolvedGitWorktree)
            assert isinstance(second, ResolvedGitWorktree)
            self.assertNotEqual(first.state_root_abs, second.state_root_abs)
            self.assertIn(b"worktrees", second.git_dir_abs)
            self.assertNotEqual(first.target, second.target)

    def test_submodule_uses_its_own_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "sub")
            self._init_repo(sub)
            _write(os.path.join(sub, "f"), b"x")
            _ = self._git("add", "f", cwd=sub)
            _ = self._git("commit", "-qm", "init", cwd=sub)
            main = os.path.join(tmp, "main")
            self._init_repo(main)
            _write(os.path.join(main, "f"), b"x")
            _ = self._git("add", "f", cwd=main)
            _ = self._git("commit", "-qm", "init", cwd=main)
            _ = self._git(
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                "-q",
                sub,
                "submodule",
                cwd=main,
            )
            resolved = _ok(
                resolve_git_worktree(os.fsencode(os.path.join(main, "submodule")))
            )
            assert isinstance(resolved, ResolvedGitWorktree)
            self.assertIn(b"modules", resolved.git_dir_abs)

    def test_bare_repository_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bare = os.path.join(tmp, "bare.git")
            _ = self._git("init", "-q", "--bare", bare)
            result = resolve_git_worktree(os.fsencode(bare))
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.BARE_REPOSITORY))
            )

    def test_git_directory_is_not_a_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            result = resolve_git_worktree(os.fsencode(os.path.join(repo, ".git")))
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_non_repository_directory_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = resolve_git_worktree(os.fsencode(tmp))
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_unavailable_git_is_reported(self) -> None:
        result = run_git(
            ("--version",), cwd=os.fsencode(tempfile.gettempdir()), env={"PATH": ""}
        )
        self.assertEqual(
            result, Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
        )

    def test_missing_working_directory_is_an_unsupported_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.fsencode(os.path.join(tmp, "absent"))
            result = run_git(("--version",), cwd=missing)
            self.assertEqual(
                result, Err(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_file_as_working_directory_is_an_unsupported_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.fsencode(os.path.join(tmp, "file"))
            _write(os.path.join(tmp, "file"), b"x")
            result = run_git(("--version",), cwd=cwd)
            self.assertEqual(
                result, Err(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_non_executable_git_is_reported_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            _write(os.path.join(bindir, "git"), b"#!/bin/sh\n")
            result = run_git(("--version",), cwd=os.fsencode(tmp), env={"PATH": bindir})
            self.assertEqual(
                result, Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_hung_git_is_an_unsupported_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            script = os.path.join(bindir, "git")
            _write(
                script,
                f"#!{sys.executable}\nimport time\ntime.sleep(5)\n".encode(),
            )
            os.chmod(script, 0o755)
            result = run_git(
                ("--version",), cwd=os.fsencode(tmp), env={"PATH": bindir}, timeout=0.2
            )
            self.assertEqual(
                result, Err(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_signalled_git_is_a_typed_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            script = os.path.join(bindir, "git")
            _write(script, b"#!/bin/sh\nkill -TERM $$\n")
            os.chmod(script, 0o755)
            result = run_git(("--version",), cwd=os.fsencode(tmp), env={"PATH": bindir})
            match result:
                case Err(error):
                    assert isinstance(error, ObservationError)
                    self.assertEqual(error.kind, ObservationErrorKind.PROCESS_SIGNALLED)
                    self.assertEqual(error.signal, SignalNumber(15))
                case Ok(_):
                    raise AssertionError("signalled git returned a result")

    def test_runner_target_error_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_runner_observation_error_is_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Err(
                        ObservationError(ObservationErrorKind.GIT_COMMAND_FAILED)
                    )
                raise AssertionError(f"unexpected git call: {args}")

            error = cast(
                ObservationError, _err(resolve_git_worktree(root, runner=runner))
            )
            self.assertEqual(error.kind, ObservationErrorKind.GIT_COMMAND_FAILED)

    def test_bare_probe_failure_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"false\n", b""))
                if args == ("rev-parse", "--is-bare-repository"):
                    return Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_path_format_other_failure_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(128, b"", b"fatal: not a git repository\n")
                    )
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_fallback_failure_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(
                            129, b"", b"error: unknown option `path-format'\n"
                        )
                    )
                if args == ("rev-parse", "--git-path", "agentic-template"):
                    return Ok(GitCommandResult(128, b"", b"fatal\n"))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_absolute_git_dir_failure_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(GitCommandResult(0, b"/x/agentic-template\n", b""))
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(GitCommandResult(128, b"", b"fatal\n"))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )

    def test_state_root_walk_failure_is_propagated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)
            _write(os.path.join(tmp, "afile"), b"x")

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(
                            0,
                            os.path.join(tmp, "afile", "agentic-template").encode()
                            + b"\n",
                            b"",
                        )
                    )
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(
                        GitCommandResult(
                            0, os.path.join(tmp, "afile").encode() + b"\n", b""
                        )
                    )
                raise AssertionError(f"unexpected git call: {args}")

            error = cast(
                ObservationError, _err(resolve_git_worktree(root, runner=runner))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_path_format_probe_failure_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_fallback_probe_failure_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(
                            129, b"", b"error: unknown option `path-format'\n"
                        )
                    )
                if args == ("rev-parse", "--git-path", "agentic-template"):
                    return Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_git_dir_probe_failure_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(GitCommandResult(0, b"/x/agentic-template\n", b""))
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Err(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
                raise AssertionError(f"unexpected git call: {args}")

            result = resolve_git_worktree(root, runner=runner)
            self.assertEqual(
                result, Ok(UnsupportedGitTarget(TargetReason.GIT_UNAVAILABLE))
            )

    def test_missing_root_is_a_typed_observation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(os.path.join(tmp, "missing"))
            state_root = os.path.join(tmp, "tree", "agentic-template")
            os.makedirs(state_root, exist_ok=True)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(GitCommandResult(0, os.fsencode(state_root) + b"\n", b""))
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(
                        GitCommandResult(
                            0, os.fsencode(os.path.join(tmp, "tree")) + b"\n", b""
                        )
                    )
                raise AssertionError(f"unexpected git call: {args}")

            error = cast(
                ObservationError, _err(resolve_git_worktree(root, runner=runner))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PATH_MISSING)

    def test_unsearchable_root_is_permission_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "denied"))
            os.chmod(os.path.join(tmp, "denied"), 0o000)
            root = os.fsencode(os.path.join(tmp, "denied", "repo"))
            state_root = os.path.join(tmp, "tree", "agentic-template")
            os.makedirs(state_root, exist_ok=True)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(GitCommandResult(0, os.fsencode(state_root) + b"\n", b""))
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(
                        GitCommandResult(
                            0, os.fsencode(os.path.join(tmp, "tree")) + b"\n", b""
                        )
                    )
                raise AssertionError(f"unexpected git call: {args}")

            error = cast(
                ObservationError, _err(resolve_git_worktree(root, runner=runner))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_symlinked_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            _write(os.path.join(repo, "f"), b"x")
            _ = self._git("add", "f", cwd=repo)
            _ = self._git("commit", "-qm", "init", cwd=repo)
            link = os.path.join(tmp, "link")
            os.symlink(repo, link)
            error = cast(
                ObservationError, _err(resolve_git_worktree(os.fsencode(link)))
            )
            self.assertEqual(error.kind, ObservationErrorKind.SYMLINK_ENCOUNTERED)

    def test_run_git_reports_nonzero_exit_as_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_git(
                ("rev-parse", "--is-inside-work-tree"), cwd=os.fsencode(tmp)
            )
            assert isinstance(result, Ok)
            self.assertNotEqual(result.value.returncode, 0)

    def test_path_format_fallback_resolves_against_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)
            os.makedirs(os.path.join(tmp, ".git", "agentic-template"), exist_ok=True)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(
                            129, b"", b"error: unknown option `path-format'\n"
                        )
                    )
                if args == ("rev-parse", "--git-path", "agentic-template"):
                    return Ok(GitCommandResult(0, b".git/agentic-template\n", b""))
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(
                        GitCommandResult(
                            0, os.path.join(tmp, ".git").encode() + b"\n", b""
                        )
                    )
                raise AssertionError(f"unexpected git call: {args}")

            resolved = _ok(resolve_git_worktree(root, runner=runner))
            assert isinstance(resolved, ResolvedGitWorktree)
            self.assertEqual(
                resolved.state_root_abs,
                posixpath.normpath(posixpath.join(root, b".git", b"agentic-template")),
            )

    def test_inconsistent_git_answers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = os.fsencode(tmp)

            def runner(
                args: tuple[str, ...],
            ) -> Result[
                GitCommandResult,
                UnsupportedGitTarget | ObservationError | InternalFailure,
            ]:
                if args == ("rev-parse", "--is-inside-work-tree"):
                    return Ok(GitCommandResult(0, b"true\n", b""))
                if args == (
                    "rev-parse",
                    "--path-format=absolute",
                    "--git-path",
                    "agentic-template",
                ):
                    return Ok(
                        GitCommandResult(0, b"/elsewhere/agentic-template\n", b"")
                    )
                if args == ("rev-parse", "--absolute-git-dir"):
                    return Ok(GitCommandResult(0, b"/somewhere/.git\n", b""))
                raise AssertionError(f"unexpected git call: {args}")

            error = cast(
                ObservationError, _err(resolve_git_worktree(root, runner=runner))
            )
            self.assertEqual(error.kind, ObservationErrorKind.GIT_COMMAND_FAILED)

    def test_state_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            self._init_repo(repo)
            _write(os.path.join(repo, "f"), b"x")
            _ = self._git("add", "f", cwd=repo)
            _ = self._git("commit", "-qm", "init", cwd=repo)
            os.makedirs(os.path.join(tmp, "elsewhere"), exist_ok=True)
            os.symlink(
                os.path.join(tmp, "elsewhere"),
                os.path.join(repo, ".git", "agentic-template"),
            )
            # git canonicalizes the symlink away, so the resolved state root no
            # longer equals the git-dir child and the equality check fails closed.
            error = cast(
                ObservationError, _err(resolve_git_worktree(os.fsencode(repo)))
            )
            self.assertEqual(error.kind, ObservationErrorKind.GIT_COMMAND_FAILED)


_HEX64 = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


@st.composite
def _journal_envelopes(draw: DrawFn) -> tuple[JournalEnvelope, str]:
    operation = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz-", min_size=1, max_size=16)
    )
    phase = draw(st.sampled_from(list(JournalPhase)))
    root = draw(st.binary(min_size=1, max_size=64))
    device = draw(st.integers(min_value=0, max_value=2**53 - 1))
    inode = draw(st.integers(min_value=0, max_value=2**53 - 1))
    identity = target_identity(root, device=device, inode=inode)
    transaction_id = draw(_HEX64)
    token = draw(st.binary(min_size=32, max_size=32))
    index = draw(st.integers(min_value=0, max_value=100))
    mode = draw(st.integers(min_value=0, max_value=0o7777))
    kind: Literal["file", "directory"] = draw(st.sampled_from(["file", "directory"]))
    raw = draw(_HEX64) if kind == "file" else None
    preparation = derive_preparation_identity(
        transaction_id,
        index,
        draw(st.sampled_from(list(PreparationRole))),
        token,
        expected_kind=kind,
        expected_raw_sha256=raw,
        expected_mode=PosixMode(mode),
    )
    envelope = JournalEnvelope(
        operation=operation,
        target=JournalTarget.from_identity(identity),
        phase=phase,
        transaction_id=transaction_id,
        preparations=(preparation,),
    )
    return envelope, transaction_id


def _sample_envelope() -> JournalEnvelope:
    """A fixed valid envelope for deterministic example tests."""

    identity = target_identity(b"/sample", device=1, inode=2)
    return JournalEnvelope(
        operation="apply",
        target=JournalTarget.from_identity(identity),
        phase=JournalPhase.PLANNED,
        transaction_id="a" * 64,
        preparations=(
            derive_preparation_identity(
                "a" * 64,
                0,
                PreparationRole.BACKUP,
                b"t" * 32,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            ),
        ),
    )


class JournalTests(unittest.TestCase):
    def _state_root(self, tmp: str) -> int:
        parent = _open_dir(tmp)
        return _ok(ensure_state_root(parent, b"state-root"))

    def _target(self) -> TargetIdentity:
        return target_identity(b"/tmp/repo", device=1, inode=2)

    def test_transaction_ids_are_lowercase_256_bit_hex(self) -> None:
        first = new_transaction_id()
        second = new_transaction_id()
        self.assertRegex(first, r"[0-9a-f]{64}")
        self.assertRegex(second, r"[0-9a-f]{64}")
        self.assertNotEqual(first, second)

    def test_ownership_tokens_are_32_bytes(self) -> None:
        token = new_ownership_token()
        self.assertEqual(len(token), 32)
        self.assertNotEqual(token, new_ownership_token())

    def test_preparation_identity_hashes_token_and_never_retains_it(self) -> None:
        token = b"t" * 32
        identity = derive_preparation_identity(
            "a" * 64,
            3,
            PreparationRole.BACKUP,
            token,
            expected_kind="file",
            expected_raw_sha256="b" * 64,
            expected_mode=PosixMode(0o644),
        )
        self.assertEqual(identity.operation_index, 3)
        self.assertEqual(identity.role, PreparationRole.BACKUP)
        self.assertEqual(
            identity.ownership_token_sha256, hashlib.sha256(token).hexdigest()
        )
        fields = tuple(field.name for field in dataclasses.fields(identity))
        self.assertNotIn("ownership_token", fields)

    def test_backup_relative_path_derivation(self) -> None:
        self.assertEqual(
            backup_relative_path("a" * 64, 7),
            RepoPath(f"transactions/{'a' * 64}/backups/7"),
        )

    def test_encode_is_stable_canonical_json(self) -> None:
        expected = (
            b'{"operation":"apply","phase":"PLANNED","preparations":[{"expected_kind":"file","expected_mode":420,"expected_raw_sha256":"'
            + b"b" * 64
            + b'","operation_index":0,"ownership_token_sha256":"8408c6d2a7b286b16d526315e5e8216cf36a7148cdbbd6e064762cd75ec5ae66","role":"backup","transaction_id":"'
            + b"a" * 64
            + b'"}],"schema_version":1,"target":{"device":1,"digest":"9a085b29788a7164b212a458bb4f97c779b1cefad3d86f17179e6d7bc2450a86","inode":2,"root":"2f73616d706c65"},"transaction_id":"'
            + b"a" * 64
            + b'"}'
        )
        self.assertEqual(encode_journal(_sample_envelope()), expected)

    @given(_journal_envelopes())
    def test_journal_round_trips_arbitrary_envelopes(
        self, pair: tuple[JournalEnvelope, str]
    ) -> None:
        envelope, _ = pair
        self.assertEqual(_ok(decode_journal(encode_journal(envelope))), envelope)

    def test_decode_rejects_invalid_json(self) -> None:
        for payload in (b"", b"{", b"not json", b"\xff\xfe"):
            error = _err(decode_journal(payload))
            self.assertIsInstance(error, InvalidJournal)

    def test_decode_rejects_duplicate_keys(self) -> None:
        payload = b'{"schema_version":1,"schema_version":2}'
        self.assertIsInstance(_err(decode_journal(payload)), InvalidJournal)

    def test_decode_rejects_unknown_schema_version(self) -> None:
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        data["schema_version"] = 2
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_unknown_phase(self) -> None:
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        data["phase"] = "EXPLODING"
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_tampered_target_digest(self) -> None:
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        target = cast(dict[str, object], data["target"])
        target["digest"] = "f" * 64
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_foreign_preparation_transaction(self) -> None:
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        preparations = cast(list[dict[str, object]], data["preparations"])
        preparations[0]["transaction_id"] = "c" * 64
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_directory_with_raw_hash(self) -> None:
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        preparations = cast(list[dict[str, object]], data["preparations"])
        preparations[0]["expected_kind"] = "directory"
        preparations[0]["expected_raw_sha256"] = "b" * 64
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_non_object_and_non_list_shapes(self) -> None:
        self.assertIsInstance(_err(decode_journal(b"[1, 2]")), InvalidJournal)
        envelope = _sample_envelope()
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        data["preparations"] = {}
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )
        data = cast(dict[str, object], json.loads(encode_journal(envelope)))
        data["preparations"] = [5]
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_field_type_violations(self) -> None:
        envelope = _sample_envelope()
        for field, value in (
            ("operation", 5),
            ("operation", ""),
            ("transaction_id", None),
            ("transaction_id", "A" * 64),
            ("phase", 5),
        ):
            data = cast(dict[str, object], json.loads(encode_journal(envelope)))
            data[field] = value
            self.assertIsInstance(
                _err(decode_journal(json.dumps(data).encode())),
                InvalidJournal,
                f"{field}={value!r} decoded",
            )
        for field, value in (
            ("target", 5),
            ("root", ""),
            ("root", "zz"),
            ("device", -1),
            ("device", True),
            ("digest", "zz" * 32),
        ):
            data = cast(dict[str, object], json.loads(encode_journal(envelope)))
            data["target"] = 5 if field == "target" else data["target"]
            if field != "target":
                target = cast(dict[str, object], data["target"])
                target[field] = value
            self.assertIsInstance(
                _err(decode_journal(json.dumps(data).encode())),
                InvalidJournal,
                f"target.{field}={value!r} decoded",
            )
        for field, value in (
            ("role", 5),
            ("role", "BACKUP"),
            ("expected_kind", "weird"),
            ("expected_mode", "x"),
            ("expected_mode", 0o10000),
            ("operation_index", -1),
            ("ownership_token_sha256", "zz" * 32),
            ("expected_raw_sha256", "zz" * 32),
        ):
            data = cast(dict[str, object], json.loads(encode_journal(envelope)))
            preparations = cast(list[dict[str, object]], data["preparations"])
            preparations[0][field] = value
            self.assertIsInstance(
                _err(decode_journal(json.dumps(data).encode())),
                InvalidJournal,
                f"preparation.{field}={value!r} decoded",
            )

    def test_construction_rejects_invalid_values(self) -> None:
        identity = target_identity(b"/sample", device=1, inode=2)
        base = _sample_envelope()
        with self.assertRaises(TypeError):
            _ = JournalTarget(root_hex="", device=1, inode=2, digest=identity.digest)
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2F73616D706C65", device=1, inode=2, digest=identity.digest
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f 73 61", device=1, inode=2, digest=identity.digest
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f73616d706c65",
                device=cast(int, "x"),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                inode=2,
                digest=identity.digest,
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f73616d706c65", device=-1, inode=2, digest=identity.digest
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f73616d706c65", device=2**53, inode=2, digest=identity.digest
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f73616d706c65", device=1, inode=2, digest="zz" * 32
            )
        with self.assertRaises(TypeError):
            _ = JournalTarget(
                root_hex="2f73616d706c65", device=1, inode=2, digest="f" * 64
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="z" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=-1,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=cast(PreparationRole, "backup"),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                ownership_token_sha256="a" * 64,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="zz" * 32,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind=cast(Literal["file", "directory"], "weird"),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind="file",
                expected_raw_sha256=None,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind="directory",
                expected_raw_sha256="b" * 64,
                expected_mode=PosixMode(0o644),
            )
        with self.assertRaises(TypeError):
            _ = PreparationIdentity(
                transaction_id="a" * 64,
                operation_index=0,
                role=PreparationRole.BACKUP,
                ownership_token_sha256="a" * 64,
                expected_kind="file",
                expected_raw_sha256="b" * 64,
                expected_mode=cast(PosixMode, 0o644),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
                schema_version=2,
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=cast(JournalTarget, object()),
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=cast(JournalPhase, "PLANNED"),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                transaction_id="a" * 64,
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="A" * 64,
            )
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
                preparations=cast(tuple[PreparationIdentity, ...], (5,)),
            )
        foreign = dataclasses.replace(base.preparations[0], transaction_id="c" * 64)
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
                preparations=(foreign,),
            )

    def test_construction_rejects_a_non_mapping_receipt(self) -> None:
        base = _sample_envelope()
        with self.assertRaises(TypeError):
            _ = JournalEnvelope(
                operation="apply",
                target=base.target,
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
                receipt=cast(dict[str, object], "not-a-mapping"),  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
            )

    def test_decode_rejects_a_non_mapping_receipt(self) -> None:
        data = cast(dict[str, object], json.loads(encode_journal(_sample_envelope())))
        data["receipt"] = "x"
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_decode_rejects_an_invalid_receipt_shape(self) -> None:
        data = cast(dict[str, object], json.loads(encode_journal(_sample_envelope())))
        data["receipt"] = {"plan_schema": 1}
        self.assertIsInstance(
            _err(decode_journal(json.dumps(data).encode())), InvalidJournal
        )

    def test_persist_writes_journal_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            envelope = _sample_envelope()
            self.assertEqual(_ok(persist_journal(state, envelope)), None)
            self.assertEqual(
                sorted(os.listdir(os.path.join(tmp, "state-root"))),
                ["journal.json"],
            )
            persisted = _read(os.path.join(tmp, "state-root", "journal.json"))
            self.assertEqual(_ok(decode_journal(persisted)), envelope)

    def test_persist_refuses_leftover_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "state-root", "journal.pending"), b"partial")
            envelope = _sample_envelope()
            error = _err(persist_journal(state, envelope))
            self.assertEqual(error.kind, TransactionErrorKind.INVALID_STATE_ROOT)
            self.assertEqual(
                _read(os.path.join(tmp, "state-root", "journal.pending")), b"partial"
            )

    def test_persist_refuses_symlinked_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "elsewhere"), b"x")
            os.symlink(
                os.path.join(tmp, "elsewhere"),
                os.path.join(tmp, "state-root", "journal.pending"),
            )
            error = _err(persist_journal(state, _sample_envelope()))
            self.assertEqual(error.kind, TransactionErrorKind.INVALID_STATE_ROOT)

    def test_persist_on_closed_state_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.close(state)
            error = _err(persist_journal(state, _sample_envelope()))
            self.assertEqual(error.kind, TransactionErrorKind.PRIMITIVE_FAILED)
            self.assertEqual(error.primitive, TransactionPrimitive.WRITE_FILE)

    def test_persist_over_a_directory_fails_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.mkdir(os.path.join(tmp, "state-root", "journal.json"))
            error = _err(persist_journal(state, _sample_envelope()))
            self.assertEqual(error.kind, TransactionErrorKind.ATOMIC_REPLACE_FAILED)
            self.assertEqual(
                os.path.isdir(os.path.join(tmp, "state-root", "journal.json")), True
            )

    def test_observe_empty_state_root_is_no_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertEqual(snapshot.entries, ())
            self.assertEqual(classify_state_root(snapshot), NoJournal())

    def test_observe_leftover_pending_is_stale_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            pending = b"partial write"
            _write(os.path.join(tmp, "state-root", "journal.pending"), pending)
            snapshot = _ok(capture_state_root(state, self._target()))
            result = classify_state_root(snapshot)
            self.assertEqual(
                result,
                StaleJournalWrite(
                    PendingIdentity(digest=hashlib.sha256(pending).hexdigest())
                ),
            )
            self.assertEqual(
                _read(os.path.join(tmp, "state-root", "journal.pending")), pending
            )

    def test_observe_valid_journal_matching_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()
            envelope = JournalEnvelope(
                operation="apply",
                target=JournalTarget.from_identity(target),
                phase=JournalPhase.MUTATING,
                transaction_id="a" * 64,
            )
            _ok(persist_journal(state, envelope))
            snapshot = _ok(capture_state_root(state, target))
            result = classify_state_root(snapshot)
            self.assertEqual(
                result,
                ValidatedJournal(
                    operation="apply",
                    target=target,
                    phase=JournalPhase.MUTATING,
                ),
            )

    def test_observe_journal_at_different_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            journal_target = self._target()
            envelope = JournalEnvelope(
                operation="apply",
                target=JournalTarget.from_identity(journal_target),
                phase=JournalPhase.PLANNED,
                transaction_id="a" * 64,
            )
            _ok(persist_journal(state, envelope))
            current = target_identity(b"/elsewhere", device=1, inode=2)
            snapshot = _ok(capture_state_root(state, current))
            result = classify_state_root(snapshot)
            self.assertEqual(
                result,
                JournalTargetMismatch(
                    journal=ValidatedJournal(
                        operation="apply",
                        target=journal_target,
                        phase=JournalPhase.PLANNED,
                    ),
                    target=current,
                ),
            )

    def test_observe_corrupt_journal_preserves_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            corrupt = b'{"broken": '
            _write(os.path.join(tmp, "state-root", "journal.json"), corrupt)
            snapshot = _ok(capture_state_root(state, self._target()))
            result = classify_state_root(snapshot)
            self.assertIsInstance(result, InvalidJournal)
            self.assertEqual(
                _read(os.path.join(tmp, "state-root", "journal.json")), corrupt
            )

    def test_observe_journal_symlink_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "elsewhere"), b"{}")
            os.symlink(
                os.path.join(tmp, "elsewhere"),
                os.path.join(tmp, "state-root", "journal.json"),
            )
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), InvalidJournal)

    def test_observe_journal_directory_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.mkdir(os.path.join(tmp, "state-root", "journal.json"))
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), InvalidJournal)

    def test_observe_hardlinked_journal_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "state-root", "journal.json"), b"{}")
            os.link(
                os.path.join(tmp, "state-root", "journal.json"),
                os.path.join(tmp, "other-name"),
            )
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), InvalidJournal)

    def test_observe_hardlinked_pending_is_orphan_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "state-root", "journal.pending"), b"x")
            os.link(
                os.path.join(tmp, "state-root", "journal.pending"),
                os.path.join(tmp, "other-name"),
            )
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), OrphanTransactionState)

    def test_capture_on_closed_state_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.close(state)
            self.assertIsInstance(
                _err(capture_state_root(state, self._target())), InternalFailure
            )

    def test_capture_rejects_unsearchable_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.chmod(os.path.join(tmp, "state-root"), 0o400)
            error = cast(
                ObservationError, _err(capture_state_root(state, self._target()))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_capture_rejects_unreadable_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            journal = os.path.join(tmp, "state-root", "journal.json")
            _write(journal, b"{}")
            os.chmod(journal, 0o000)
            error = cast(
                ObservationError, _err(capture_state_root(state, self._target()))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_capture_rejects_unreadable_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            pending = os.path.join(tmp, "state-root", "journal.pending")
            _write(pending, b"x")
            os.chmod(pending, 0o000)
            error = cast(
                ObservationError, _err(capture_state_root(state, self._target()))
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_observe_transactions_without_journal_is_orphan_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            os.mkdir(os.path.join(tmp, "state-root", "transactions"))
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), OrphanTransactionState)

    def test_observe_unexpected_entry_is_orphan_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "state-root", "mystery"), b"x")
            snapshot = _ok(capture_state_root(state, self._target()))
            self.assertIsInstance(classify_state_root(snapshot), OrphanTransactionState)

    def test_observe_unexpected_entry_with_journal_is_orphan_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()
            _ok(
                persist_journal(
                    state,
                    JournalEnvelope(
                        operation="apply",
                        target=JournalTarget.from_identity(target),
                        phase=JournalPhase.SEALED,
                        transaction_id="a" * 64,
                    ),
                )
            )
            _write(os.path.join(tmp, "state-root", "mystery"), b"x")
            snapshot = _ok(capture_state_root(state, target))
            self.assertIsInstance(classify_state_root(snapshot), OrphanTransactionState)

    def test_observe_oversized_journal_is_limit_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            _write(os.path.join(tmp, "state-root", "journal.json"), b"x" * 64)
            limits = ResourceLimits(max_file_bytes=32)
            error = cast(
                ObservationError,
                _err(capture_state_root(state, self._target(), limits=limits)),
            )
            self.assertEqual(
                error.kind, ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED
            )

    def test_collect_returns_stable_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()
            snapshot = _ok(capture_state_root(state, target))
            collected = _ok(collect_state_root_observation(state, target))
            self.assertEqual(collected, snapshot)

    def test_collect_reports_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()
            calls = {"count": 0}

            def alternating(
                state_fd: int, current: TargetIdentity
            ) -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
                del state_fd, current
                calls["count"] += 1
                return Ok(
                    StateRootSnapshot(
                        target=target,
                        entries=(b"journal.json",),
                        journal=b"a" if calls["count"] % 2 else b"b",
                        journal_irregular=False,
                        pending=None,
                        pending_irregular=False,
                    )
                )

            error = cast(
                ObservationError,
                _err(
                    collect_state_root_observation(state, target, capture=alternating)
                ),
            )
            self.assertEqual(error.kind, ObservationErrorKind.CONCURRENT_TARGET_CHANGE)

    def test_collect_propagates_capture_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()

            def failing(
                state_fd: int, current: TargetIdentity
            ) -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
                del state_fd, current
                return Err(
                    ObservationError(
                        ObservationErrorKind.PERMISSION_DENIED, "state-root"
                    )
                )

            error = cast(
                ObservationError,
                _err(collect_state_root_observation(state, target, capture=failing)),
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_collect_propagates_second_pass_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            target = self._target()
            calls = {"count": 0}
            snapshot = StateRootSnapshot(
                target=target,
                entries=(),
                journal=None,
                journal_irregular=False,
                pending=None,
                pending_irregular=False,
            )

            def failing_second(
                state_fd: int, current: TargetIdentity
            ) -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
                del state_fd, current
                calls["count"] += 1
                if calls["count"] == 1:
                    return Ok(snapshot)
                return Err(
                    ObservationError(
                        ObservationErrorKind.PERMISSION_DENIED, "state-root"
                    )
                )

            error = cast(
                ObservationError,
                _err(
                    collect_state_root_observation(
                        state, target, capture=failing_second
                    )
                ),
            )
            self.assertEqual(error.kind, ObservationErrorKind.PERMISSION_DENIED)

    def test_collect_rejects_non_positive_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state_root(tmp)
            with self.assertRaises(ValueError):
                _ = collect_state_root_observation(
                    state, self._target(), max_attempts=0
                )


if __name__ == "__main__":
    _ = unittest.main()
