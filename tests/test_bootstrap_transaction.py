"""Typed transaction machine: preparation, mutation, verification, and phases.

Covers T11 validation: the complete Mealy transition table through ``PLANNED``,
``MUTATING``, ``RESTORED``, and ``SEALED``; typed request/observation matching
with ``InternalFailure`` on mismatch; injected failures before and after every
journal/preparation/phase/effect boundary; gate failure entering rollback rather
than sealed cleanup; closed ``EffectError`` mapping; and a Hypothesis stateful
model that drives every machine constructor.
"""

from __future__ import annotations

import os
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, cast

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.errors import (
    ErrnoClass,
    InternalCode,
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
)
from scripts.bootstrap.identity import (
    DirectoryEntry,
    DirectoryState,
    FileEntry,
    FileState,
    ManifestIdentity,
    PosixMode,
    content_identity,
    directory_tree_hash,
    file_state_identity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.journal import (
    PreparationIdentity,
    PreparationRole,
    decode_journal,
    encode_journal,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    DirectoryAbsent,
    DirectoryOperation,
    ExpectedGatePass,
    ExpectedGateRefusal,
    ExpectedValidation,
    FileAbsent,
    FileOperation,
    GateSpecification,
    MaterializedTree,
    ObservedDirectoryEntry,
    ObservedFileEntry,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    PlannedFilePresent,
    ReadinessRule,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    TargetSnapshot,
)
from scripts.bootstrap.readiness import evaluate_readiness
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.source_baseline import GitHubSourceBaseline
from scripts.bootstrap.transaction import (
    CleaningForward,
    CleaningRollback,
    CleanupCompleted,
    CleanupCursor,
    CleanupItem,
    CleanupKind,
    CompiledTransaction,
    Completed,
    EffectError,
    EffectFailed,
    EffectRequestKind,
    GatedCandidateTransaction,
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
    NeedRevalidation,
    NeedSealedJournal,
    ObservedEffect,
    ObservedFileAbsent,
    OperationApplied,
    OperationCursor,
    PersistJournal,
    PlannedTransaction,
    PostStateObserved,
    PreparationCompleted,
    PreparationCursor,
    PreparationSpec,
    Preparing,
    Releasing,
    Reobserved,
    RestoredTransaction,
    RollbackAlreadyRestored,
    RollbackCursor,
    RollbackRestoredNow,
    RollbackStepCompleted,
    RollingBack,
    SealedTransaction,
    Start,
    Stopped,
    TransactionEvent,
    TransactionInstruction,
    TransactionMachineState,
    TransactionOutcome,
    TransactionTerminal,
    ValidatedLockedTransaction,
    VerifiedRestoredTransaction,
    Verifying,
    _old_file_state,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    derive_cleanup,
    derive_preparation_specs,
    derive_preparations,
    mutating_envelope,
    planned_envelope,
    request_kind,
    restored_envelope,
    sealed_envelope,
    snapshot_matches_candidate,
    snapshot_matches_preconditions,
    step_transaction,
)
from scripts.bootstrap.values import JournalPhase

TARGET = target_identity(b"/work/example", device=1, inode=2)
NEW = b"fresh content\n"
OLD = b"old content\n"
STALE = b"stale content\n"
TREE_FILE = b"tree content\n"
TREE_SUB_FILE = b"sub content\n"
TRANSACTION_ID = "ab" * 32

_EFFECT_ERRORS: tuple[EffectError, ...] = (
    ObservationError(ObservationErrorKind.PATH_MISSING, "app.py"),
    ObservationError(ObservationErrorKind.GIT_COMMAND_FAILED, "git"),
    ObservationError(ObservationErrorKind.CONCURRENT_TARGET_CHANGE),
    TransactionError(TransactionErrorKind.INVALID_JOURNAL, subject="journal.json"),
    TransactionError(TransactionErrorKind.PRECONDITION_CHANGED, subject="README.md"),
    TransactionError.primitive_failed(
        TransactionPrimitive.WRITE_FILE, ErrnoClass.NO_SPACE, "app.py"
    ),
    TransactionError(
        TransactionErrorKind.ATOMIC_REPLACE_FAILED,
        errno_class=ErrnoClass.CROSS_DEVICE,
        subject="app.py",
    ),
    InternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION),
    InternalFailure(InternalCode.IMPOSSIBLE_STATE),
)


def _ok[ValueT, ErrorT](result: Result[ValueT, ErrorT]) -> ValueT:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise AssertionError(f"expected Ok, got Err({error!r})")


def _blob_store(
    *contents: bytes,
) -> tuple[VerifiedBlobStore, dict[bytes, ContentId]]:
    store = VerifiedBlobStore.empty()
    ids: dict[bytes, ContentId] = {}
    for content in contents:
        content_id, store = _ok(store.intern(content))
        ids[content] = content_id
    return store, ids


def _plan(
    operations: tuple[FileOperation | DirectoryOperation, ...],
    store: VerifiedBlobStore,
) -> OperationPlan:
    return OperationPlan(
        plan_schema=1,
        operation_kind="initial",
        target_identity=TARGET,
        generation_path=GenerationPath.GITHUB,
        source_before=None,
        source_after=GitHubSourceBaseline(
            kind="github", fingerprint="0" * 64, entries=(), snapshot_commit="0" * 40
        ),
        manifest_before=None,
        manifest_after=ManifestIdentity(payload=b"{}", digest=sha256_hex(b"{}")),
        ordered_operations=operations,
        blob_store=store,
        gate_specification=GateSpecification(
            operation="initial",
            artifact_verification=True,
            template_contract=True,
            readiness_rule=ReadinessRule.NO_WORSE_BLOCKING,
            expected_placeholder=(),
        ),
    )


def _tree(ids: dict[bytes, ContentId]) -> MaterializedTree:
    entries = (
        PlannedFileEntry(
            path=RepoPath("pkg/__init__.py"),
            identity=content_identity(TREE_FILE, text=False),
            mode=PosixMode.FILE,
            content_id=ids[TREE_FILE],
        ),
        PlannedDirectoryEntry(path=RepoPath("pkg/sub"), mode=PosixMode.DIRECTORY),
    )
    byte_entries = (
        FileEntry(RepoPath("pkg/__init__.py"), TREE_FILE, PosixMode.FILE),
        DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),
    )
    return MaterializedTree(
        root=RepoPath("pkg"),
        root_mode=PosixMode.DIRECTORY,
        entries=entries,
        raw_tree_sha256=directory_tree_hash(
            b"plan/tree", DirectoryState(PosixMode.DIRECTORY, byte_entries)
        ),
    )


def _full_plan() -> tuple[OperationPlan, VerifiedBlobStore, dict[bytes, ContentId]]:
    store, ids = _blob_store(NEW, OLD, STALE, TREE_FILE, TREE_SUB_FILE)
    operations = (
        CreateFileOperation(
            path=RepoPath("app.py"),
            expected_old=file_state_identity(None, text=False),
            planned_new=PlannedFilePresent(
                identity=content_identity(NEW, text=False),
                mode=PosixMode.FILE,
                content_id=ids[NEW],
            ),
        ),
        ReplaceFileOperation(
            path=RepoPath("README.md"),
            expected_old=file_state_identity(OLD, text=False, mode=PosixMode.FILE),
            planned_new=PlannedFilePresent(
                identity=content_identity(NEW, text=False),
                mode=PosixMode.EXECUTABLE,
                content_id=ids[NEW],
            ),
        ),
        DeleteFileOperation(
            path=RepoPath("stale.txt"),
            expected_old=file_state_identity(STALE, text=False, mode=PosixMode.FILE),
            planned_new=FileAbsent(),
        ),
        CreateTreeOperation(
            root=RepoPath("pkg"), expected_old=None, planned_new=_tree(ids)
        ),
        RemoveEmptyDirectoryOperation(
            path=RepoPath("empty"),
            expected_old=DirectoryState(PosixMode.DIRECTORY, ()),
            planned_new=DirectoryAbsent(),
        ),
    )
    return _plan(operations, store), store, ids


def _precondition_snapshot() -> TargetSnapshot:
    return TargetSnapshot(
        files=(
            ObservedFileEntry(
                path=RepoPath("README.md"),
                state=file_state_identity(OLD, text=False, mode=PosixMode.FILE),
                content=OLD,
            ),
            ObservedFileEntry(
                path=RepoPath("stale.txt"),
                state=file_state_identity(STALE, text=False, mode=PosixMode.FILE),
                content=STALE,
            ),
        ),
        directories=(
            ObservedDirectoryEntry(
                path=RepoPath("empty"), state=DirectoryState(PosixMode.DIRECTORY, ())
            ),
        ),
    )


def _candidate_snapshot() -> TargetSnapshot:
    return TargetSnapshot(
        files=(
            ObservedFileEntry(
                path=RepoPath("app.py"),
                state=file_state_identity(NEW, text=False, mode=PosixMode.FILE),
                content=NEW,
            ),
            ObservedFileEntry(
                path=RepoPath("README.md"),
                state=file_state_identity(NEW, text=False, mode=PosixMode.EXECUTABLE),
                content=NEW,
            ),
        ),
        directories=(
            ObservedDirectoryEntry(
                path=RepoPath("pkg"),
                state=DirectoryState(
                    PosixMode.DIRECTORY,
                    (
                        FileEntry(
                            RepoPath("pkg/__init__.py"), TREE_FILE, PosixMode.FILE
                        ),
                        DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),
                    ),
                ),
            ),
        ),
    )


def _compiled(
    plan: OperationPlan,
    expected: ExpectedValidation | None = None,
    *,
    tokens: tuple[bytes, ...] | None = None,
) -> CompiledTransaction:
    if expected is None:
        expected = ExpectedGatePass(readiness=evaluate_readiness())
    if tokens is None:
        tokens = tuple(
            os.urandom(32) for _ in range(len(derive_preparation_specs(plan)))
        )
    return CompiledTransaction.compile(
        plan, expected, transaction_id=TRANSACTION_ID, ownership_tokens=tokens
    )


def _chain(
    compiled: CompiledTransaction,
) -> tuple[
    LockedTransaction,
    ValidatedLockedTransaction,
    PlannedTransaction,
    MutatingTransaction,
    VerifiedRestoredTransaction,
    GatedCandidateTransaction,
    SealedTransaction,
    RestoredTransaction,
]:
    locked = LockedTransaction(compiled)
    validated = ValidatedLockedTransaction(locked, _precondition_snapshot())
    planned = PlannedTransaction(validated)
    mutating = MutatingTransaction(planned)
    verified = VerifiedRestoredTransaction(mutating)
    gated = GatedCandidateTransaction(mutating, _candidate_snapshot())
    sealed = SealedTransaction(gated)
    restored = RestoredTransaction(verified)
    return locked, validated, planned, mutating, verified, gated, sealed, restored


def _state_tag(state: TransactionMachineState) -> str:
    match state:
        case NeedLock():
            return "NeedLock"
        case NeedRevalidation():
            return "NeedRevalidation"
        case NeedPlannedJournal():
            return "NeedPlannedJournal"
        case Preparing():
            return "Preparing"
        case NeedMutatingJournal():
            return "NeedMutatingJournal"
        case Installing():
            return "Installing"
        case Verifying():
            return "Verifying"
        case RollingBack():
            return "RollingBack"
        case NeedRestoredJournal():
            return "NeedRestoredJournal"
        case NeedSealedJournal():
            return "NeedSealedJournal"
        case CleaningForward():
            return "CleaningForward"
        case CleaningRollback():
            return "CleaningRollback"
        case Releasing():
            return "Releasing"
    return assert_never(
        state
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _drive(
    initial: TransactionMachineState, events: tuple[TransactionEvent, ...]
) -> tuple[TransactionMachineState, TransactionOutcome | None]:
    state = initial
    for event in events:
        match step_transaction(state, event):
            case TransactionInstruction(request=_, next_state=next_state):
                state = next_state
            case TransactionTerminal(outcome=outcome):
                return state, outcome
    return state, None


def _run(
    initial: TransactionMachineState, events: tuple[TransactionEvent, ...]
) -> tuple[tuple[str, ...], tuple[EffectRequestKind, ...], TransactionOutcome | None]:
    state = initial
    tags: list[str] = []
    kinds: list[EffectRequestKind] = []
    outcome: TransactionOutcome | None = None
    for event in events:
        match step_transaction(state, event):
            case TransactionInstruction(request=request, next_state=next_state):
                state = next_state
                tags.append(_state_tag(state))
                kinds.append(request_kind(request))
            case TransactionTerminal(outcome=terminal):
                outcome = terminal
                break
    return tuple(tags), tuple(kinds), outcome


def _terminal(
    state: TransactionMachineState, event: TransactionEvent
) -> TransactionOutcome:
    step = step_transaction(state, event)
    match step:
        case TransactionTerminal(outcome=outcome):
            return outcome
        case TransactionInstruction(request=_, next_state=_):
            raise AssertionError("expected a terminal step")
    return assert_never(
        step
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _instruction(
    state: TransactionMachineState, event: TransactionEvent
) -> TransactionInstruction:
    step = step_transaction(state, event)
    match step:
        case TransactionInstruction(request=request, next_state=next_state):
            return TransactionInstruction(request, next_state)
        case TransactionTerminal(outcome=outcome):
            raise AssertionError(f"expected an instruction, got {outcome!r}")
    return assert_never(
        step
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


def _sealed_cleanup(plan: OperationPlan) -> tuple[CleanupItem, ...]:
    return derive_cleanup(plan, JournalPhase.SEALED)


def _restored_cleanup(plan: OperationPlan) -> tuple[CleanupItem, ...]:
    return derive_cleanup(plan, JournalPhase.RESTORED)


class TestPreparationDerivation:
    def test_specs_cover_every_operation_shape(self) -> None:
        plan, _, _ = _full_plan()
        assert derive_preparation_specs(plan) == (
            PreparationSpec(
                0, PreparationRole.STAGE, "file", sha256_hex(NEW), PosixMode.FILE
            ),
            PreparationSpec(
                1, PreparationRole.STAGE, "file", sha256_hex(NEW), PosixMode.EXECUTABLE
            ),
            PreparationSpec(
                1, PreparationRole.BACKUP, "file", sha256_hex(OLD), PosixMode.FILE
            ),
            PreparationSpec(
                2, PreparationRole.BACKUP, "file", sha256_hex(STALE), PosixMode.FILE
            ),
            PreparationSpec(
                3, PreparationRole.STAGE, "directory", None, PosixMode.DIRECTORY
            ),
        )

    def test_derive_preparations_carries_exact_identities(self) -> None:
        plan, _, _ = _full_plan()
        specs = derive_preparation_specs(plan)
        tokens = tuple(os.urandom(32) for _ in range(len(specs)))
        preparations = derive_preparations(plan, TRANSACTION_ID, tokens)
        assert len(preparations) == len(specs)
        for preparation, spec, token in zip(preparations, specs, tokens, strict=True):
            assert preparation.transaction_id == TRANSACTION_ID
            assert preparation.operation_index == spec.operation_index
            assert preparation.role is spec.role
            assert preparation.ownership_token_sha256 == sha256_hex(token)
            assert preparation.expected_kind == spec.expected_kind
            assert preparation.expected_raw_sha256 == spec.expected_raw_sha256
            assert preparation.expected_mode == spec.expected_mode

    def test_derive_preparations_requires_one_token_per_preparation(self) -> None:
        plan, _, _ = _full_plan()
        with pytest.raises(ValueError, match="ownership token"):
            _ = derive_preparations(plan, TRANSACTION_ID, (os.urandom(32),))

    def test_compiled_transaction_rejects_bad_transaction_id(self) -> None:
        plan, _, _ = _full_plan()
        with pytest.raises(TypeError, match="transaction id"):
            _ = CompiledTransaction.compile(
                plan,
                ExpectedGatePass(readiness=evaluate_readiness()),
                transaction_id="zz" * 32,
                ownership_tokens=tuple(os.urandom(32) for _ in range(5)),
            )

    def test_compiled_transaction_rejects_mismatched_preparations(self) -> None:
        plan, _, _ = _full_plan()
        tokens = tuple(os.urandom(32) for _ in range(5))
        good = derive_preparations(plan, TRANSACTION_ID, tokens)
        bad = good[:4]
        with pytest.raises(TypeError, match="preparation"):
            _ = CompiledTransaction(
                plan,
                ExpectedGatePass(readiness=evaluate_readiness()),
                TRANSACTION_ID,
                bad,
            )


class TestCleanupDerivation:
    def test_sealed_cleanup_order(self) -> None:
        plan, _, _ = _full_plan()
        assert _sealed_cleanup(plan) == (
            CleanupItem(CleanupKind.STAGE, 0),
            CleanupItem(CleanupKind.STAGE, 1),
            CleanupItem(CleanupKind.BACKUP, 1),
            CleanupItem(CleanupKind.BACKUP, 2),
            CleanupItem(CleanupKind.STAGE, 3),
            CleanupItem(CleanupKind.TRANSACTION_DIRECTORY),
            CleanupItem(CleanupKind.JOURNAL),
        )

    def test_restored_cleanup_order_matches_sealed_base(self) -> None:
        plan, _, _ = _full_plan()
        assert _restored_cleanup(plan) == _sealed_cleanup(plan)

    def test_cleanup_rejects_other_phases(self) -> None:
        plan, _, _ = _full_plan()
        with pytest.raises(ValueError, match="RESTORED and SEALED"):
            _ = derive_cleanup(plan, JournalPhase.PLANNED)


class TestEnvelopes:
    def test_envelopes_round_trip_through_journal_codec(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        _, _, planned, _, verified, gated, _, _ = _chain(compiled)
        envelopes = (
            planned_envelope(planned),
            mutating_envelope(planned),
            restored_envelope(verified),
            sealed_envelope(gated),
        )
        for envelope in envelopes:
            assert decode_journal(encode_journal(envelope)) == Ok(envelope)

    def test_envelopes_carry_phase_and_preparations(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        _, _, planned, _, verified, gated, _, _ = _chain(compiled)
        assert planned_envelope(planned).phase is JournalPhase.PLANNED
        assert mutating_envelope(planned).phase is JournalPhase.MUTATING
        assert restored_envelope(verified).phase is JournalPhase.RESTORED
        assert sealed_envelope(gated).phase is JournalPhase.SEALED
        for envelope in (
            planned_envelope(planned),
            mutating_envelope(planned),
            restored_envelope(verified),
            sealed_envelope(gated),
        ):
            assert envelope.transaction_id == TRANSACTION_ID
            assert envelope.target.root_hex == TARGET.root_os_bytes.hex()
            assert envelope.preparations == compiled.preparations


def _snapshot_with_file(
    path: RepoPath,
    state: FileState,
    content: bytes,
    *,
    base: TargetSnapshot | None = None,
) -> TargetSnapshot:
    base = base if base is not None else _precondition_snapshot()
    files = (
        *(entry for entry in base.files if entry.path != path),
        ObservedFileEntry(path, state, content),
    )
    return TargetSnapshot(files=files, directories=base.directories)


def _snapshot_without_file(path: RepoPath) -> TargetSnapshot:
    base = _precondition_snapshot()
    files = tuple(entry for entry in base.files if entry.path != path)
    return TargetSnapshot(files=files, directories=base.directories)


def _snapshot_with_directory(path: RepoPath, state: DirectoryState) -> TargetSnapshot:
    base = _precondition_snapshot()
    directories = (
        *(entry for entry in base.directories if entry.path != path),
        ObservedDirectoryEntry(path, state),
    )
    return TargetSnapshot(files=base.files, directories=directories)


def _snapshot_without_directory(path: RepoPath) -> TargetSnapshot:
    base = _precondition_snapshot()
    directories = tuple(entry for entry in base.directories if entry.path != path)
    return TargetSnapshot(files=base.files, directories=directories)


class TestSnapshotVerification:
    def test_preconditions_match_full_snapshot(self) -> None:
        plan, _, _ = _full_plan()
        assert snapshot_matches_preconditions(plan, _precondition_snapshot()) is True

    def test_preconditions_accept_explicit_absent_entries(self) -> None:
        plan, _, _ = _full_plan()
        snapshot = _snapshot_with_file(
            RepoPath("app.py"), file_state_identity(None, text=False), b""
        )
        assert snapshot_matches_preconditions(plan, snapshot) is True

    def test_candidate_accepts_explicit_absent_deleted_entry(self) -> None:
        plan, _, _ = _full_plan()
        snapshot = _snapshot_with_file(
            RepoPath("stale.txt"),
            file_state_identity(None, text=False),
            b"",
            base=_candidate_snapshot(),
        )
        assert snapshot_matches_candidate(plan, snapshot) is True

    @pytest.mark.parametrize(
        "label, snapshot",
        [
            (
                "changed-file",
                _snapshot_with_file(
                    RepoPath("README.md"),
                    file_state_identity(b"other\n", text=False, mode=PosixMode.FILE),
                    b"other\n",
                ),
            ),
            ("missing-file", _snapshot_without_file(RepoPath("README.md"))),
            ("missing-file2", _snapshot_without_file(RepoPath("stale.txt"))),
            (
                "extra-file",
                _snapshot_with_file(
                    RepoPath("app.py"),
                    file_state_identity(NEW, text=False, mode=PosixMode.FILE),
                    NEW,
                ),
            ),
            (
                "wrong-mode",
                _snapshot_with_file(
                    RepoPath("README.md"),
                    file_state_identity(OLD, text=False, mode=PosixMode.EXECUTABLE),
                    OLD,
                ),
            ),
            ("missing-directory", _snapshot_without_directory(RepoPath("empty"))),
            (
                "changed-directory",
                _snapshot_with_directory(
                    RepoPath("empty"),
                    DirectoryState(
                        PosixMode.DIRECTORY,
                        (FileEntry(RepoPath("empty/x"), b"x", PosixMode.FILE),),
                    ),
                ),
            ),
            (
                "extra-directory",
                _snapshot_with_directory(
                    RepoPath("pkg"), DirectoryState(PosixMode.DIRECTORY, ())
                ),
            ),
        ],
    )
    def test_preconditions_reject_each_perturbation(
        self, label: str, snapshot: TargetSnapshot
    ) -> None:
        del label
        plan, _, _ = _full_plan()
        assert snapshot_matches_preconditions(plan, snapshot) is False

    def test_candidate_matches_full_snapshot(self) -> None:
        plan, _, _ = _full_plan()
        assert snapshot_matches_candidate(plan, _candidate_snapshot()) is True

    @pytest.mark.parametrize(
        "label, snapshot",
        [
            ("missing-app", _snapshot_without_file(RepoPath("app.py"))),
            (
                "changed-app",
                _snapshot_with_file(
                    RepoPath("app.py"),
                    file_state_identity(b"other\n", text=False, mode=PosixMode.FILE),
                    b"other\n",
                ),
            ),
            (
                "wrong-app-mode",
                _snapshot_with_file(
                    RepoPath("app.py"),
                    file_state_identity(NEW, text=False, mode=PosixMode.EXECUTABLE),
                    NEW,
                ),
            ),
            (
                "wrong-readme-mode",
                _snapshot_with_file(
                    RepoPath("README.md"),
                    file_state_identity(NEW, text=False, mode=PosixMode.FILE),
                    NEW,
                ),
            ),
            (
                "stale-remains",
                _snapshot_with_file(
                    RepoPath("stale.txt"),
                    file_state_identity(STALE, text=False, mode=PosixMode.FILE),
                    STALE,
                ),
            ),
            ("missing-pkg", _snapshot_without_directory(RepoPath("pkg"))),
            (
                "missing-tree-file",
                _snapshot_with_directory(
                    RepoPath("pkg"),
                    DirectoryState(
                        PosixMode.DIRECTORY,
                        (DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),),
                    ),
                ),
            ),
            (
                "changed-tree-file",
                _snapshot_with_directory(
                    RepoPath("pkg"),
                    DirectoryState(
                        PosixMode.DIRECTORY,
                        (
                            FileEntry(
                                RepoPath("pkg/__init__.py"), b"other\n", PosixMode.FILE
                            ),
                            DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),
                        ),
                    ),
                ),
            ),
            (
                "missing-subdirectory",
                _snapshot_with_directory(
                    RepoPath("pkg"),
                    DirectoryState(
                        PosixMode.DIRECTORY,
                        (
                            FileEntry(
                                RepoPath("pkg/__init__.py"), TREE_FILE, PosixMode.FILE
                            ),
                        ),
                    ),
                ),
            ),
            (
                "empty-remains",
                _snapshot_with_directory(
                    RepoPath("empty"), DirectoryState(PosixMode.DIRECTORY, ())
                ),
            ),
        ],
    )
    def test_candidate_rejects_each_perturbation(
        self, label: str, snapshot: TargetSnapshot
    ) -> None:
        del label
        plan, _, _ = _full_plan()
        assert snapshot_matches_candidate(plan, snapshot) is False


def _prefix_events(
    compiled: CompiledTransaction,
) -> dict[str, tuple[TransactionEvent, ...]]:
    preparations = compiled.preparations
    n_ops = len(compiled.plan.ordered_operations)
    planned = (
        Start(),
        ObservedEffect(LockAcquired()),
        ObservedEffect(Reobserved(_precondition_snapshot())),
        ObservedEffect(JournalPersisted(JournalPhase.PLANNED)),
    )
    prepared = (
        *planned,
        *(
            ObservedEffect(PreparationCompleted(preparations[index]))
            for index in range(len(preparations))
        ),
    )
    installing = (*prepared, ObservedEffect(JournalPersisted(JournalPhase.MUTATING)))
    applied = (
        *installing,
        *(
            ObservedEffect(OperationApplied(index, ObservedFileAbsent()))
            for index in range(n_ops)
        ),
    )
    sealed_journal = (
        *applied,
        ObservedEffect(PostStateObserved(_candidate_snapshot())),
    )
    sealed = (*sealed_journal, ObservedEffect(JournalPersisted(JournalPhase.SEALED)))
    cleaned = (
        *sealed,
        *(
            ObservedEffect(CleanupCompleted(index))
            for index in range(len(_sealed_cleanup(compiled.plan)))
        ),
    )
    rolling = (*applied, ObservedEffect(PostStateObserved(_candidate_snapshot())))
    rolled_back = (
        *rolling,
        *(
            ObservedEffect(RollbackStepCompleted(index, RollbackAlreadyRestored()))
            for index in reversed(range(n_ops))
        ),
    )
    restored_journal = (
        *rolled_back,
        ObservedEffect(JournalPersisted(JournalPhase.RESTORED)),
    )
    return {
        "acquire-lock": (Start(),),
        "observe-again": (Start(), ObservedEffect(LockAcquired())),
        "planned-journal": (
            Start(),
            ObservedEffect(LockAcquired()),
            ObservedEffect(Reobserved(_precondition_snapshot())),
        ),
        "prepare-one": planned,
        "mutating-journal": prepared,
        "apply-one": installing,
        "observe-post-state": applied,
        "sealed-journal": sealed_journal,
        "clean-one-forward": sealed,
        "release-lock": cleaned,
        "attempt-rollback-one": rolling,
        "restored-journal": rolled_back,
        "clean-one-rollback": restored_journal,
    }


class TestMachineHappyPath:
    def test_full_run_reaches_completed_with_exact_transition_table(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        prepared_count = len(compiled.preparations)
        n_ops = len(plan.ordered_operations)
        cleanup_count = len(_sealed_cleanup(plan))
        events = (
            Start(),
            ObservedEffect(LockAcquired()),
            ObservedEffect(Reobserved(_precondition_snapshot())),
            ObservedEffect(JournalPersisted(JournalPhase.PLANNED)),
            *(
                ObservedEffect(PreparationCompleted(compiled.preparations[index]))
                for index in range(prepared_count)
            ),
            ObservedEffect(JournalPersisted(JournalPhase.MUTATING)),
            *(
                ObservedEffect(OperationApplied(index, ObservedFileAbsent()))
                for index in range(n_ops)
            ),
            ObservedEffect(PostStateObserved(_candidate_snapshot())),
            ObservedEffect(JournalPersisted(JournalPhase.SEALED)),
            *(
                ObservedEffect(CleanupCompleted(index))
                for index in range(cleanup_count)
            ),
            ObservedEffect(LockReleased()),
        )
        tags, kinds, outcome = _run(NeedLock(compiled), events)
        assert outcome is not None
        match outcome:
            case Completed(trace=trace):
                assert trace == kinds
            case Stopped():
                raise AssertionError(f"expected Completed, got {outcome!r}")
        assert tags == (
            "NeedRevalidation",
            "NeedRevalidation",
            "NeedPlannedJournal",
            *("Preparing",) * prepared_count,
            "NeedMutatingJournal",
            *("Installing",) * n_ops,
            "Verifying",
            "NeedSealedJournal",
            *("CleaningForward",) * cleanup_count,
            "Releasing",
        )
        assert kinds == (
            EffectRequestKind.ACQUIRE_LOCK,
            EffectRequestKind.OBSERVE_AGAIN,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.PREPARE_ONE,) * prepared_count,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.APPLY_ONE,) * n_ops,
            EffectRequestKind.OBSERVE_POST_STATE,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.CLEAN_ONE,) * cleanup_count,
            EffectRequestKind.RELEASE_LOCK,
        )

    def test_gate_refusal_enters_rollback_and_reaches_completed(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan, ExpectedGateRefusal(failures=()))
        prepared_count = len(compiled.preparations)
        n_ops = len(plan.ordered_operations)
        cleanup_count = len(_restored_cleanup(plan))
        events = (
            Start(),
            ObservedEffect(LockAcquired()),
            ObservedEffect(Reobserved(_precondition_snapshot())),
            ObservedEffect(JournalPersisted(JournalPhase.PLANNED)),
            *(
                ObservedEffect(PreparationCompleted(compiled.preparations[index]))
                for index in range(prepared_count)
            ),
            ObservedEffect(JournalPersisted(JournalPhase.MUTATING)),
            *(
                ObservedEffect(OperationApplied(index, ObservedFileAbsent()))
                for index in range(n_ops)
            ),
            ObservedEffect(PostStateObserved(_candidate_snapshot())),
            *(
                ObservedEffect(RollbackStepCompleted(index, RollbackRestoredNow()))
                for index in reversed(range(n_ops))
            ),
            ObservedEffect(JournalPersisted(JournalPhase.RESTORED)),
            *(
                ObservedEffect(CleanupCompleted(index))
                for index in range(cleanup_count)
            ),
            ObservedEffect(LockReleased()),
        )
        tags, kinds, outcome = _run(NeedLock(compiled), events)
        assert outcome is not None
        match outcome:
            case Completed(trace=trace):
                assert trace == kinds
            case Stopped():
                raise AssertionError(f"expected Completed, got {outcome!r}")
        assert tags == (
            "NeedRevalidation",
            "NeedRevalidation",
            "NeedPlannedJournal",
            *("Preparing",) * prepared_count,
            "NeedMutatingJournal",
            *("Installing",) * n_ops,
            "Verifying",
            *("RollingBack",) * n_ops,
            "NeedRestoredJournal",
            *("CleaningRollback",) * cleanup_count,
            "Releasing",
        )
        assert kinds == (
            EffectRequestKind.ACQUIRE_LOCK,
            EffectRequestKind.OBSERVE_AGAIN,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.PREPARE_ONE,) * prepared_count,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.APPLY_ONE,) * n_ops,
            EffectRequestKind.OBSERVE_POST_STATE,
            *(EffectRequestKind.ATTEMPT_ROLLBACK_ONE,) * n_ops,
            EffectRequestKind.PERSIST_JOURNAL,
            *(EffectRequestKind.CLEAN_ONE,) * cleanup_count,
            EffectRequestKind.RELEASE_LOCK,
        )

    def test_post_state_mismatch_also_enters_rollback(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        prefix = _prefix_events(compiled)["observe-post-state"]
        state, _ = _drive(NeedLock(compiled), prefix)
        assert isinstance(state, Verifying)
        instruction = _instruction(
            state, ObservedEffect(PostStateObserved(_precondition_snapshot()))
        )
        assert (
            request_kind(instruction.request) == EffectRequestKind.ATTEMPT_ROLLBACK_ONE
        )
        assert isinstance(instruction.next_state, RollingBack)


class TestMachineRevalidation:
    def test_reobserved_precondition_mismatch_stops_with_input_changed(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        prefix = _prefix_events(compiled)["observe-again"]
        state, _ = _drive(NeedLock(compiled), prefix)
        assert isinstance(state, NeedRevalidation)
        outcome = _terminal(state, ObservedEffect(Reobserved(_candidate_snapshot())))
        match outcome:
            case Stopped(
                trace=trace, error=TransitionError(kind=kind, subject=subject)
            ):
                assert kind is TransitionErrorKind.INPUT_CHANGED
                assert (
                    subject
                    == "re-observed target differs from the planned preconditions"
                )
                assert trace == (
                    EffectRequestKind.ACQUIRE_LOCK,
                    EffectRequestKind.OBSERVE_AGAIN,
                )
            case _:
                raise AssertionError(
                    f"expected Stopped(INPUT_CHANGED), got {outcome!r}"
                )

    def test_lock_refused_stops_with_lock_held(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        instruction = _instruction(NeedLock(compiled), Start())
        assert request_kind(instruction.request) == EffectRequestKind.ACQUIRE_LOCK
        outcome = _terminal(
            instruction.next_state,
            ObservedEffect(
                LockRefused(TransitionError(TransitionErrorKind.LOCK_HELD, "lock"))
            ),
        )
        match outcome:
            case Stopped(trace=trace, error=TransitionError(kind=kind)):
                assert kind is TransitionErrorKind.LOCK_HELD
                assert trace == (EffectRequestKind.ACQUIRE_LOCK,)
            case _:
                raise AssertionError(f"expected Stopped(LOCK_HELD), got {outcome!r}")

    def test_lock_refused_rejects_other_transition_kinds(self) -> None:
        with pytest.raises(TypeError, match="LOCK_HELD"):
            _ = LockRefused(TransitionError(TransitionErrorKind.INPUT_CHANGED, "x"))


class TestMachineMismatches:
    def test_mismatched_observations_are_internal_failures(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        _, _, planned, mutating, verified, gated, sealed, restored = _chain(compiled)
        preparations = compiled.preparations
        fake_identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=99,
            role=PreparationRole.STAGE,
            ownership_token_sha256="f" * 64,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(NEW),
            expected_mode=PosixMode.FILE,
        )
        error = _EFFECT_ERRORS[0]
        cases: tuple[tuple[str, TransactionMachineState, TransactionEvent], ...] = (
            (
                "start-only-at-need-lock",
                NeedLock(compiled),
                ObservedEffect(LockAcquired()),
            ),
            (
                "no-pending-effect-at-need-lock",
                NeedLock(compiled),
                ObservedEffect(EffectFailed(EffectRequestKind.ACQUIRE_LOCK, error)),
            ),
            (
                "reobserved-while-awaiting-lock",
                NeedRevalidation(
                    LockedTransaction(compiled), (EffectRequestKind.ACQUIRE_LOCK,)
                ),
                ObservedEffect(Reobserved(_precondition_snapshot())),
            ),
            (
                "lock-acquired-while-awaiting-reobservation",
                NeedRevalidation(
                    LockedTransaction(compiled),
                    (EffectRequestKind.ACQUIRE_LOCK, EffectRequestKind.OBSERVE_AGAIN),
                ),
                ObservedEffect(LockAcquired()),
            ),
            (
                "lock-refused-while-awaiting-reobservation",
                NeedRevalidation(
                    LockedTransaction(compiled),
                    (EffectRequestKind.ACQUIRE_LOCK, EffectRequestKind.OBSERVE_AGAIN),
                ),
                ObservedEffect(
                    LockRefused(TransitionError(TransitionErrorKind.LOCK_HELD, "lock"))
                ),
            ),
            (
                "start-after-lock",
                NeedRevalidation(
                    LockedTransaction(compiled), (EffectRequestKind.ACQUIRE_LOCK,)
                ),
                Start(),
            ),
            (
                "wrong-journal-phase-at-planned",
                NeedPlannedJournal(
                    ValidatedLockedTransaction(
                        LockedTransaction(compiled), _precondition_snapshot()
                    ),
                    (
                        EffectRequestKind.ACQUIRE_LOCK,
                        EffectRequestKind.OBSERVE_AGAIN,
                        EffectRequestKind.PERSIST_JOURNAL,
                    ),
                ),
                ObservedEffect(JournalPersisted(JournalPhase.MUTATING)),
            ),
            (
                "reobserved-at-planned-journal",
                NeedPlannedJournal(
                    ValidatedLockedTransaction(
                        LockedTransaction(compiled), _precondition_snapshot()
                    ),
                    (
                        EffectRequestKind.ACQUIRE_LOCK,
                        EffectRequestKind.OBSERVE_AGAIN,
                        EffectRequestKind.PERSIST_JOURNAL,
                    ),
                ),
                ObservedEffect(Reobserved(_precondition_snapshot())),
            ),
            (
                "wrong-preparation-index",
                Preparing(
                    planned,
                    PreparationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.PREPARE_ONE),
                ),
                ObservedEffect(PreparationCompleted(preparations[1])),
            ),
            (
                "wrong-preparation-identity",
                Preparing(
                    planned,
                    PreparationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.PREPARE_ONE),
                ),
                ObservedEffect(PreparationCompleted(fake_identity)),
            ),
            (
                "applied-while-preparing",
                Preparing(
                    planned,
                    PreparationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.PREPARE_ONE),
                ),
                ObservedEffect(OperationApplied(0, ObservedFileAbsent())),
            ),
            (
                "wrong-mutating-phase",
                NeedMutatingJournal(planned, (EffectRequestKind.PERSIST_JOURNAL,)),
                ObservedEffect(JournalPersisted(JournalPhase.SEALED)),
            ),
            (
                "wrong-operation-index",
                Installing(
                    mutating,
                    OperationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.APPLY_ONE),
                ),
                ObservedEffect(OperationApplied(1, ObservedFileAbsent())),
            ),
            (
                "prepared-while-installing",
                Installing(
                    mutating,
                    OperationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.APPLY_ONE),
                ),
                ObservedEffect(PreparationCompleted(preparations[0])),
            ),
            (
                "journaled-while-verifying",
                Verifying(
                    mutating,
                    (EffectRequestKind.APPLY_ONE, EffectRequestKind.OBSERVE_POST_STATE),
                ),
                ObservedEffect(JournalPersisted(JournalPhase.SEALED)),
            ),
            (
                "wrong-rollback-index",
                RollingBack(
                    mutating,
                    RollbackCursor(0),
                    (
                        EffectRequestKind.OBSERVE_POST_STATE,
                        EffectRequestKind.ATTEMPT_ROLLBACK_ONE,
                    ),
                ),
                ObservedEffect(RollbackStepCompleted(1, RollbackAlreadyRestored())),
            ),
            (
                "applied-while-rolling-back",
                RollingBack(
                    mutating,
                    RollbackCursor(0),
                    (
                        EffectRequestKind.OBSERVE_POST_STATE,
                        EffectRequestKind.ATTEMPT_ROLLBACK_ONE,
                    ),
                ),
                ObservedEffect(OperationApplied(0, ObservedFileAbsent())),
            ),
            (
                "wrong-restored-phase",
                NeedRestoredJournal(
                    verified,
                    (
                        EffectRequestKind.ATTEMPT_ROLLBACK_ONE,
                        EffectRequestKind.PERSIST_JOURNAL,
                    ),
                ),
                ObservedEffect(JournalPersisted(JournalPhase.PLANNED)),
            ),
            (
                "wrong-sealed-phase",
                NeedSealedJournal(
                    gated,
                    (
                        EffectRequestKind.OBSERVE_POST_STATE,
                        EffectRequestKind.PERSIST_JOURNAL,
                    ),
                ),
                ObservedEffect(JournalPersisted(JournalPhase.MUTATING)),
            ),
            (
                "wrong-cleanup-index-forward",
                CleaningForward(
                    sealed,
                    CleanupCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.CLEAN_ONE),
                ),
                ObservedEffect(CleanupCompleted(1)),
            ),
            (
                "wrong-cleanup-index-rollback",
                CleaningRollback(
                    restored,
                    CleanupCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.CLEAN_ONE),
                ),
                ObservedEffect(CleanupCompleted(1)),
            ),
            (
                "cleaned-while-releasing",
                Releasing(
                    sealed,
                    (EffectRequestKind.CLEAN_ONE, EffectRequestKind.RELEASE_LOCK),
                ),
                ObservedEffect(CleanupCompleted(0)),
            ),
            (
                "released-without-pending-request",
                Releasing(sealed, ()),
                ObservedEffect(LockReleased()),
            ),
            (
                "wrong-failure-kind",
                Preparing(
                    planned,
                    PreparationCursor(0),
                    (EffectRequestKind.PERSIST_JOURNAL, EffectRequestKind.PREPARE_ONE),
                ),
                ObservedEffect(EffectFailed(EffectRequestKind.APPLY_ONE, error)),
            ),
        )
        for label, state, event in cases:
            outcome = _terminal(state, event)
            match outcome:
                case Stopped(error=InternalFailure(code=code)):
                    assert code is InternalCode.IMPOSSIBLE_STATE, label
                case _:
                    raise AssertionError(
                        f"{label}: expected InternalFailure, got {outcome!r}"
                    )


class TestMachineEffectFailures:
    @pytest.mark.parametrize(
        "label, kind",
        [
            ("acquire-lock", EffectRequestKind.ACQUIRE_LOCK),
            ("observe-again", EffectRequestKind.OBSERVE_AGAIN),
            ("planned-journal", EffectRequestKind.PERSIST_JOURNAL),
            ("prepare-one", EffectRequestKind.PREPARE_ONE),
            ("mutating-journal", EffectRequestKind.PERSIST_JOURNAL),
            ("apply-one", EffectRequestKind.APPLY_ONE),
            ("observe-post-state", EffectRequestKind.OBSERVE_POST_STATE),
            ("sealed-journal", EffectRequestKind.PERSIST_JOURNAL),
            ("clean-one-forward", EffectRequestKind.CLEAN_ONE),
            ("release-lock", EffectRequestKind.RELEASE_LOCK),
            ("attempt-rollback-one", EffectRequestKind.ATTEMPT_ROLLBACK_ONE),
            ("restored-journal", EffectRequestKind.PERSIST_JOURNAL),
            ("clean-one-rollback", EffectRequestKind.CLEAN_ONE),
        ],
    )
    def test_effect_failure_at_every_boundary_stops_with_the_error(
        self, label: str, kind: EffectRequestKind
    ) -> None:
        plan, _, _ = _full_plan()
        rollback_rows = {
            "attempt-rollback-one",
            "restored-journal",
            "clean-one-rollback",
        }
        compiled = _compiled(
            plan,
            ExpectedGateRefusal(failures=()) if label in rollback_rows else None,
        )
        prefix = _prefix_events(compiled)[label]
        state, _ = _drive(NeedLock(compiled), prefix)
        error = TransactionError.primitive_failed(
            TransactionPrimitive.WRITE_FILE, ErrnoClass.NO_SPACE, "app.py"
        )
        outcome = _terminal(state, ObservedEffect(EffectFailed(kind, error)))
        match outcome:
            case Stopped(trace=trace, error=received):
                assert received == error
                assert trace == state.trace
                assert trace[-1] == kind
                assert len(trace) == len(prefix)
            case _:
                raise AssertionError(f"{label}: expected Stopped, got {outcome!r}")

    @pytest.mark.parametrize(
        "error",
        _EFFECT_ERRORS,
        ids=[
            f"{type(error).__name__}-{getattr(error, 'kind', getattr(error, 'code', ''))}"
            for error in _EFFECT_ERRORS
        ],
    )
    def test_every_effect_error_variant_maps_closed_to_stopped(
        self, error: EffectError
    ) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        state = NeedRevalidation(
            LockedTransaction(compiled), (EffectRequestKind.ACQUIRE_LOCK,)
        )
        outcome = _terminal(
            state, ObservedEffect(EffectFailed(EffectRequestKind.ACQUIRE_LOCK, error))
        )
        match outcome:
            case Stopped(trace=trace, error=received):
                assert received == error
                assert trace == (EffectRequestKind.ACQUIRE_LOCK,)
            case _:
                raise AssertionError(f"expected Stopped, got {outcome!r}")


class TestContractGuards:
    @pytest.mark.parametrize(
        "label, factory, match",
        [
            (
                "persist-journal-request-phase",
                lambda: PersistJournal("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed phase",
            ),
            (
                "reobserved-snapshot",
                lambda: Reobserved("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "target snapshot",
            ),
            (
                "journal-persisted-phase",
                lambda: JournalPersisted("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed phase",
            ),
            (
                "preparation-completed-identity",
                lambda: PreparationCompleted("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "identity",
            ),
            (
                "operation-applied-index",
                lambda: OperationApplied(-1, ObservedFileAbsent()),
                "non-negative",
            ),
            (
                "operation-applied-state",
                lambda: OperationApplied(0, "bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed path state",
            ),
            (
                "post-state-observed-snapshot",
                lambda: PostStateObserved("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "target snapshot",
            ),
            ("cleanup-completed-index", lambda: CleanupCompleted(-1), "non-negative"),
            (
                "rollback-step-index",
                lambda: RollbackStepCompleted(-1, RollbackAlreadyRestored()),
                "non-negative",
            ),
            (
                "rollback-step-result",
                lambda: RollbackStepCompleted(0, "bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed result",
            ),
            (
                "effect-failed-kind",
                lambda: EffectFailed("bad", _EFFECT_ERRORS[0]),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed request kind",
            ),
            (
                "effect-failed-error",
                lambda: EffectFailed(EffectRequestKind.ACQUIRE_LOCK, "bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed effect error",
            ),
            (
                "observed-effect-observation",
                lambda: ObservedEffect("bad"),  # pyright: ignore[reportArgumentType]  intentional invalid-value negative test
                "closed observation",
            ),
            ("preparation-cursor", lambda: PreparationCursor(-1), "non-negative"),
            ("operation-cursor", lambda: OperationCursor(-1), "non-negative"),
            ("rollback-cursor", lambda: RollbackCursor(-1), "non-negative"),
            ("cleanup-cursor", lambda: CleanupCursor(-1), "non-negative"),
        ],
    )
    def test_contract_guards_reject_invalid_payloads(
        self, label: str, factory: Callable[[], object], match: str
    ) -> None:
        del label
        with pytest.raises(TypeError, match=match):
            _ = factory()

    def test_old_file_state_returns_none_for_absent_state(self) -> None:
        assert _old_file_state(FileState(None, None)) is None

    def test_compiled_transaction_rejects_bad_id_directly(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        with pytest.raises(TypeError, match="transaction id"):
            _ = CompiledTransaction(
                plan,
                ExpectedGatePass(readiness=evaluate_readiness()),
                "zz" * 32,
                compiled.preparations,
            )

    def test_compiled_transaction_rejects_mismatched_identity_directly(self) -> None:
        plan, _, _ = _full_plan()
        compiled = _compiled(plan)
        original = compiled.preparations[0]
        mismatched = PreparationIdentity(
            transaction_id=original.transaction_id,
            operation_index=original.operation_index,
            role=original.role,
            ownership_token_sha256=original.ownership_token_sha256,
            expected_kind=original.expected_kind,
            expected_raw_sha256=original.expected_raw_sha256,
            expected_mode=PosixMode.EXECUTABLE,
        )
        preparations = (mismatched, *compiled.preparations[1:])
        with pytest.raises(TypeError, match="preparation identity"):
            _ = CompiledTransaction(
                plan,
                ExpectedGatePass(readiness=evaluate_readiness()),
                TRANSACTION_ID,
                preparations,
            )


class TestMachineDegenerate:
    def test_skips_preparation_when_none_reserved(self) -> None:
        store, _ = _blob_store()
        plan = _plan(
            (
                RemoveEmptyDirectoryOperation(
                    path=RepoPath("empty"),
                    expected_old=DirectoryState(PosixMode.DIRECTORY, ()),
                    planned_new=DirectoryAbsent(),
                ),
            ),
            store,
        )
        compiled = _compiled(plan, tokens=())
        prefix = _prefix_events(compiled)["planned-journal"]
        state, _ = _drive(NeedLock(compiled), prefix)
        assert isinstance(state, NeedPlannedJournal)
        instruction = _instruction(
            state, ObservedEffect(JournalPersisted(JournalPhase.PLANNED))
        )
        assert request_kind(instruction.request) == EffectRequestKind.PERSIST_JOURNAL
        assert isinstance(instruction.next_state, NeedMutatingJournal)

    def test_skips_apply_when_no_operations(self) -> None:
        store, _ = _blob_store()
        plan = _plan((), store)
        compiled = _compiled(plan, tokens=())
        prefix = _prefix_events(compiled)["mutating-journal"]
        state, _ = _drive(NeedLock(compiled), prefix)
        assert isinstance(state, NeedMutatingJournal)
        instruction = _instruction(
            state, ObservedEffect(JournalPersisted(JournalPhase.MUTATING))
        )
        assert request_kind(instruction.request) == EffectRequestKind.OBSERVE_POST_STATE
        assert isinstance(instruction.next_state, Verifying)

    def test_gate_refusal_with_no_operations_enters_restored_directly(self) -> None:
        store, _ = _blob_store()
        plan = _plan((), store)
        compiled = _compiled(plan, ExpectedGateRefusal(failures=()), tokens=())
        prefix = _prefix_events(compiled)["observe-post-state"]
        state, _ = _drive(NeedLock(compiled), prefix)
        assert isinstance(state, Verifying)
        instruction = _instruction(
            state, ObservedEffect(PostStateObserved(_candidate_snapshot()))
        )
        assert request_kind(instruction.request) == EffectRequestKind.PERSIST_JOURNAL
        assert isinstance(instruction.next_state, NeedRestoredJournal)


@dataclass(frozen=True, slots=True)
class _Prediction:
    name: str | None
    cursor: int | None
    trace: tuple[EffectRequestKind, ...]
    outcome: TransactionOutcome | None


def _same_outcome(a: TransactionOutcome, b: TransactionOutcome) -> bool:
    match (a, b):
        case (Completed(trace_a), Completed(trace_b)):
            return trace_a == trace_b
        case (Stopped(trace_a, error_a), Stopped(trace_b, error_b)):
            if trace_a != trace_b or type(error_a) is not type(error_b):
                return False
            return all(
                getattr(error_a, attr, None) == getattr(error_b, attr, None)
                for attr in ("kind", "code")
            )
        case _:
            return False


@settings(max_examples=40, deadline=None)
class TransactionMachineStateful(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.plan: OperationPlan = _full_plan()[0]
        store, ids = _blob_store(NEW, OLD, STALE, TREE_FILE, TREE_SUB_FILE)
        self._store: VerifiedBlobStore = store
        self._ids: dict[bytes, ContentId] = ids
        self._pass_gate: bool = os.urandom(1)[0] % 2 == 0
        expected: ExpectedValidation = (
            ExpectedGatePass(readiness=evaluate_readiness())
            if self._pass_gate
            else ExpectedGateRefusal(failures=())
        )
        tokens = tuple(
            os.urandom(32) for _ in range(len(derive_preparation_specs(self.plan)))
        )
        self.compiled: CompiledTransaction = CompiledTransaction.compile(
            self.plan, expected, transaction_id=TRANSACTION_ID, ownership_tokens=tokens
        )
        self.preparations: tuple[PreparationIdentity, ...] = self.compiled.preparations
        self.n_ops: int = len(self.plan.ordered_operations)
        self.sealed_cleanup: tuple[CleanupItem, ...] = _sealed_cleanup(self.plan)
        self.restored_cleanup: tuple[CleanupItem, ...] = _restored_cleanup(self.plan)
        self.state: TransactionMachineState = NeedLock(self.compiled)
        self.name: str = "NeedLock"
        self.cursor: int | None = None
        self.trace: tuple[EffectRequestKind, ...] = ()
        self.outcome: TransactionOutcome | None = None

    @staticmethod
    def _observe(
        state: TransactionMachineState,
    ) -> tuple[str, int | None, tuple[EffectRequestKind, ...]]:
        match state:
            case NeedLock(trace=trace):
                return "NeedLock", None, trace
            case NeedRevalidation(trace=trace):
                return "NeedRevalidation", None, trace
            case NeedPlannedJournal(trace=trace):
                return "NeedPlannedJournal", None, trace
            case Preparing(cursor=cursor, trace=trace):
                return "Preparing", cursor.index, trace
            case NeedMutatingJournal(trace=trace):
                return "NeedMutatingJournal", None, trace
            case Installing(cursor=cursor, trace=trace):
                return "Installing", cursor.index, trace
            case Verifying(trace=trace):
                return "Verifying", None, trace
            case RollingBack(cursor=cursor, trace=trace):
                return "RollingBack", cursor.index, trace
            case NeedRestoredJournal(trace=trace):
                return "NeedRestoredJournal", None, trace
            case NeedSealedJournal(trace=trace):
                return "NeedSealedJournal", None, trace
            case CleaningForward(cursor=cursor, trace=trace):
                return "CleaningForward", cursor.index, trace
            case CleaningRollback(cursor=cursor, trace=trace):
                return "CleaningRollback", cursor.index, trace
            case Releasing(trace=trace):
                return "Releasing", None, trace
        return assert_never(
            state
        )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard

    def _correct_event(self) -> TransactionEvent:
        pending = self.trace[-1]
        index = self.cursor if self.cursor is not None else -1
        match (self.name, pending):
            case ("NeedRevalidation", EffectRequestKind.ACQUIRE_LOCK):
                return ObservedEffect(LockAcquired())
            case ("NeedRevalidation", EffectRequestKind.OBSERVE_AGAIN):
                return ObservedEffect(Reobserved(_precondition_snapshot()))
            case ("NeedPlannedJournal", EffectRequestKind.PERSIST_JOURNAL):
                return ObservedEffect(JournalPersisted(JournalPhase.PLANNED))
            case ("Preparing", EffectRequestKind.PREPARE_ONE):
                assert index >= 0
                return ObservedEffect(PreparationCompleted(self.preparations[index]))
            case ("NeedMutatingJournal", EffectRequestKind.PERSIST_JOURNAL):
                return ObservedEffect(JournalPersisted(JournalPhase.MUTATING))
            case ("Installing", EffectRequestKind.APPLY_ONE):
                assert index >= 0
                return ObservedEffect(OperationApplied(index, ObservedFileAbsent()))
            case ("Verifying", EffectRequestKind.OBSERVE_POST_STATE):
                return ObservedEffect(PostStateObserved(_candidate_snapshot()))
            case ("RollingBack", EffectRequestKind.ATTEMPT_ROLLBACK_ONE):
                assert index >= 0
                return ObservedEffect(
                    RollbackStepCompleted(index, RollbackAlreadyRestored())
                )
            case ("NeedRestoredJournal", EffectRequestKind.PERSIST_JOURNAL):
                return ObservedEffect(JournalPersisted(JournalPhase.RESTORED))
            case ("NeedSealedJournal", EffectRequestKind.PERSIST_JOURNAL):
                return ObservedEffect(JournalPersisted(JournalPhase.SEALED))
            case ("CleaningForward" | "CleaningRollback", EffectRequestKind.CLEAN_ONE):
                assert index >= 0
                return ObservedEffect(CleanupCompleted(index))
            case ("Releasing", EffectRequestKind.RELEASE_LOCK):
                return ObservedEffect(LockReleased())
            case _:  # pyright: ignore[reportAny] — residual subject type after narrowed cases
                raise AssertionError(
                    f"no correct event for {self.name} awaiting {pending}"
                )

    def _rollback_prediction(self, trace: tuple[EffectRequestKind, ...]) -> _Prediction:
        if self.n_ops:
            return _Prediction(
                "RollingBack",
                self.n_ops - 1,
                (*trace, EffectRequestKind.ATTEMPT_ROLLBACK_ONE),
                None,
            )
        return _Prediction(
            "NeedRestoredJournal",
            None,
            (*trace, EffectRequestKind.PERSIST_JOURNAL),
            None,
        )

    def _model_predict(self, event: TransactionEvent) -> _Prediction:
        pending = self.trace[-1] if self.trace else None
        trace = self.trace
        if isinstance(event, ObservedEffect) and isinstance(
            event.observation, EffectFailed
        ):
            failed = event.observation
            if pending is None or failed.request_kind != pending:
                return _Prediction(
                    None,
                    None,
                    trace,
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                )
            return _Prediction(None, None, trace, Stopped(trace, failed.error))
        if isinstance(event, Start):
            if self.name != "NeedLock" or pending is not None:
                return _Prediction(
                    None,
                    None,
                    trace,
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                )
            return _Prediction(
                "NeedRevalidation",
                None,
                (*trace, EffectRequestKind.ACQUIRE_LOCK),
                None,
            )
        assert isinstance(event, ObservedEffect)
        observation = event.observation
        match (self.name, observation):
            case (
                "NeedRevalidation",
                LockAcquired(),
            ) if pending == EffectRequestKind.ACQUIRE_LOCK:
                return _Prediction(
                    "NeedRevalidation",
                    None,
                    (*trace, EffectRequestKind.OBSERVE_AGAIN),
                    None,
                )
            case (
                "NeedRevalidation",
                LockRefused(),
            ) if pending == EffectRequestKind.ACQUIRE_LOCK:
                return _Prediction(None, None, trace, Stopped(trace, observation.error))
            case (
                "NeedRevalidation",
                Reobserved(snapshot=snapshot),
            ) if pending == EffectRequestKind.OBSERVE_AGAIN:
                if snapshot_matches_preconditions(self.plan, snapshot):
                    return _Prediction(
                        "NeedPlannedJournal",
                        None,
                        (*trace, EffectRequestKind.PERSIST_JOURNAL),
                        None,
                    )
                return _Prediction(
                    None,
                    None,
                    trace,
                    Stopped(
                        trace,
                        TransitionError(
                            TransitionErrorKind.INPUT_CHANGED,
                            "re-observed target differs from the planned preconditions",
                        ),
                    ),
                )
            case ("NeedPlannedJournal", JournalPersisted(phase=JournalPhase.PLANNED)):
                if self.preparations:
                    return _Prediction(
                        "Preparing",
                        0,
                        (*trace, EffectRequestKind.PREPARE_ONE),
                        None,
                    )
                return _Prediction(
                    "NeedMutatingJournal",
                    None,
                    (*trace, EffectRequestKind.PERSIST_JOURNAL),
                    None,
                )
            case ("Preparing", PreparationCompleted(identity=identity)):
                index = self.cursor
                if (
                    index is None
                    or index >= len(self.preparations)
                    or identity != self.preparations[index]
                ):
                    return _Prediction(
                        None,
                        None,
                        trace,
                        Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                    )
                if index + 1 < len(self.preparations):
                    return _Prediction(
                        "Preparing",
                        index + 1,
                        (*trace, EffectRequestKind.PREPARE_ONE),
                        None,
                    )
                return _Prediction(
                    "NeedMutatingJournal",
                    None,
                    (*trace, EffectRequestKind.PERSIST_JOURNAL),
                    None,
                )
            case ("NeedMutatingJournal", JournalPersisted(phase=JournalPhase.MUTATING)):
                if self.n_ops:
                    return _Prediction(
                        "Installing",
                        0,
                        (*trace, EffectRequestKind.APPLY_ONE),
                        None,
                    )
                return _Prediction(
                    "Verifying",
                    None,
                    (*trace, EffectRequestKind.OBSERVE_POST_STATE),
                    None,
                )
            case ("Installing", OperationApplied(operation_index=index, state=_)):
                cursor = self.cursor
                if cursor is None or index != cursor or index >= self.n_ops:
                    return _Prediction(
                        None,
                        None,
                        trace,
                        Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                    )
                if cursor + 1 < self.n_ops:
                    return _Prediction(
                        "Installing",
                        cursor + 1,
                        (*trace, EffectRequestKind.APPLY_ONE),
                        None,
                    )
                return _Prediction(
                    "Verifying",
                    None,
                    (*trace, EffectRequestKind.OBSERVE_POST_STATE),
                    None,
                )
            case ("Verifying", PostStateObserved(snapshot=snapshot)):
                if snapshot_matches_candidate(self.plan, snapshot):
                    if self._pass_gate:
                        return _Prediction(
                            "NeedSealedJournal",
                            None,
                            (*trace, EffectRequestKind.PERSIST_JOURNAL),
                            None,
                        )
                    return self._rollback_prediction(trace)
                return self._rollback_prediction(trace)
            case (
                "RollingBack",
                RollbackStepCompleted(operation_index=index, result=_),
            ):
                cursor = self.cursor
                if cursor is None or index != cursor or cursor < 0:
                    return _Prediction(
                        None,
                        None,
                        trace,
                        Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                    )
                if cursor > 0:
                    return _Prediction(
                        "RollingBack",
                        cursor - 1,
                        (*trace, EffectRequestKind.ATTEMPT_ROLLBACK_ONE),
                        None,
                    )
                return _Prediction(
                    "NeedRestoredJournal",
                    None,
                    (*trace, EffectRequestKind.PERSIST_JOURNAL),
                    None,
                )
            case ("NeedRestoredJournal", JournalPersisted(phase=JournalPhase.RESTORED)):
                return _Prediction(
                    "CleaningRollback",
                    0,
                    (*trace, EffectRequestKind.CLEAN_ONE),
                    None,
                )
            case ("NeedSealedJournal", JournalPersisted(phase=JournalPhase.SEALED)):
                return _Prediction(
                    "CleaningForward",
                    0,
                    (*trace, EffectRequestKind.CLEAN_ONE),
                    None,
                )
            case ("CleaningForward", CleanupCompleted(cleanup_index=index)):
                return self._cleanup_prediction(
                    index, self.sealed_cleanup, "CleaningForward", trace
                )
            case ("CleaningRollback", CleanupCompleted(cleanup_index=index)):
                return self._cleanup_prediction(
                    index, self.restored_cleanup, "CleaningRollback", trace
                )
            case ("Releasing", LockReleased()) if (
                pending == EffectRequestKind.RELEASE_LOCK
            ):
                return _Prediction(None, None, trace, Completed(trace))
            case _:
                return _Prediction(
                    None,
                    None,
                    trace,
                    Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
                )

    def _cleanup_prediction(
        self,
        index: int,
        cleanup: tuple[CleanupItem, ...],
        name: str,
        trace: tuple[EffectRequestKind, ...],
    ) -> _Prediction:
        cursor = self.cursor
        if cursor is None or index != cursor or index >= len(cleanup):
            return _Prediction(
                None,
                None,
                trace,
                Stopped(trace, InternalFailure(InternalCode.IMPOSSIBLE_STATE)),
            )
        if cursor + 1 < len(cleanup):
            return _Prediction(
                name, cursor + 1, (*trace, EffectRequestKind.CLEAN_ONE), None
            )
        return _Prediction(
            "Releasing",
            None,
            (*trace, EffectRequestKind.RELEASE_LOCK),
            None,
        )

    def _legal_events(self) -> list[TransactionEvent]:
        if self.name == "NeedLock":
            return [Start()]
        pending = self.trace[-1]
        correct = self._correct_event()
        legal: list[TransactionEvent] = [
            correct,
            ObservedEffect(EffectFailed(pending, _EFFECT_ERRORS[0])),
        ]
        if (
            self.name == "NeedRevalidation"
            and pending == EffectRequestKind.ACQUIRE_LOCK
        ):
            legal.append(
                ObservedEffect(
                    LockRefused(TransitionError(TransitionErrorKind.LOCK_HELD, "lock"))
                )
            )
        if self.name == "RollingBack":
            index = self.cursor if self.cursor is not None else -1
            legal.append(
                ObservedEffect(RollbackStepCompleted(index, RollbackRestoredNow()))
            )
        return legal

    def _wrong_events(self) -> list[TransactionEvent]:
        legal = self._legal_events()
        pending = self.trace[-1] if self.trace else None
        events: list[TransactionEvent] = [
            ObservedEffect(LockAcquired()),
            ObservedEffect(JournalPersisted(JournalPhase.PLANNED)),
            ObservedEffect(JournalPersisted(JournalPhase.MUTATING)),
            ObservedEffect(JournalPersisted(JournalPhase.RESTORED)),
            ObservedEffect(JournalPersisted(JournalPhase.SEALED)),
            ObservedEffect(PreparationCompleted(self.preparations[0])),
            ObservedEffect(OperationApplied(999, ObservedFileAbsent())),
            ObservedEffect(PostStateObserved(_candidate_snapshot())),
            ObservedEffect(CleanupCompleted(999)),
            ObservedEffect(RollbackStepCompleted(999, RollbackAlreadyRestored())),
            ObservedEffect(LockReleased()),
            ObservedEffect(
                EffectFailed(EffectRequestKind.APPLY_ONE, _EFFECT_ERRORS[0])
            ),
            ObservedEffect(Reobserved(_candidate_snapshot())),
        ]
        if self.name == "NeedLock":
            events.append(
                ObservedEffect(
                    EffectFailed(EffectRequestKind.ACQUIRE_LOCK, _EFFECT_ERRORS[0])
                )
            )
        if pending == EffectRequestKind.PREPARE_ONE and len(self.preparations) > 1:
            index = ((self.cursor or 0) + 1) % len(self.preparations)
            events.append(
                ObservedEffect(PreparationCompleted(self.preparations[index]))
            )
        if pending == EffectRequestKind.APPLY_ONE and self.n_ops > 1:
            index = ((self.cursor or 0) + 1) % self.n_ops
            events.append(ObservedEffect(OperationApplied(index, ObservedFileAbsent())))
        if pending == EffectRequestKind.ATTEMPT_ROLLBACK_ONE and self.n_ops > 1:
            index = ((self.cursor or 0) + 1) % self.n_ops
            events.append(
                ObservedEffect(RollbackStepCompleted(index, RollbackRestoredNow()))
            )
        if pending == EffectRequestKind.CLEAN_ONE and len(self.sealed_cleanup) > 1:
            index = ((self.cursor or 0) + 1) % len(self.sealed_cleanup)
            events.append(ObservedEffect(CleanupCompleted(index)))
        if pending == EffectRequestKind.PERSIST_JOURNAL:
            wrong_phase = (
                JournalPhase.SEALED
                if self.name == "NeedPlannedJournal"
                else JournalPhase.PLANNED
            )
            events.append(ObservedEffect(JournalPersisted(wrong_phase)))
        return [event for event in events if event not in legal]

    def _feed(self, event: TransactionEvent) -> None:
        prediction = self._model_predict(event)
        step = step_transaction(self.state, event)
        match step:
            case TransactionInstruction(request=request, next_state=next_state):
                assert prediction.outcome is None, (event, prediction, step)
                assert request_kind(request) == prediction.trace[-1], (
                    event,
                    prediction,
                    step,
                )
                name, cursor, trace = self._observe(next_state)
                assert name == prediction.name, (event, prediction, step)
                assert cursor == prediction.cursor, (event, prediction, step)
                assert trace == prediction.trace, (event, prediction, step)
                self.state = next_state
                self.name, self.cursor, self.trace = name, cursor, trace
            case TransactionTerminal(outcome=outcome):
                assert prediction.outcome is not None, (event, prediction, step)
                assert _same_outcome(outcome, prediction.outcome), (
                    event,
                    prediction,
                    step,
                )
                self.outcome = outcome

    @rule()
    def start_machine(self) -> None:
        if self.outcome is not None or self.name != "NeedLock":
            return
        self._feed(Start())

    @rule()
    def feed_correct_observation(self) -> None:
        if self.outcome is not None or self.name == "NeedLock":
            return
        self._feed(self._correct_event())

    @rule(data=st.data())
    def fail_current_effect(self, data: st.DataObject) -> None:
        if self.outcome is not None or self.name == "NeedLock":
            return
        kind = self.trace[-1]
        error = data.draw(st.sampled_from(_EFFECT_ERRORS))
        self._feed(ObservedEffect(EffectFailed(kind, error)))

    @rule(data=st.data())
    def feed_wrong_observation(self, data: st.DataObject) -> None:
        if self.outcome is not None:
            return
        event = data.draw(st.sampled_from(self._wrong_events()))
        self._feed(event)

    @invariant()
    def machine_matches_model(self) -> None:
        if self.outcome is not None:
            return
        assert self._observe(self.state) == (self.name, self.cursor, self.trace)


TestTransactionMachineStateful = cast(
    type[unittest.TestCase], TransactionMachineStateful.TestCase
)
