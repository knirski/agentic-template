"""Rollback reducers, recovery decisions, and crash-resumable cleanup.

Covers T11b validation: exact raw bytes/modes and directory topology restored,
idempotent rollback, directory create/remove recovery, crash during gating and
cleanup, RESTORED and SEALED recovery, third-state preservation, git-clean
survival, Hypothesis crash sequences, and evidence remaining available after
failure.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
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
    old_file_parts,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.journal import (
    PreparationIdentity,
    PreparationRole,
    PreparationSpec,
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
from scripts.bootstrap.recovery import (
    CandidateIntact,
    CleanupMissing,
    CleanupThirdState,
    CleanupVerified,
    DiscardStalePending,
    FinishRestoredCleanup,
    FinishSealedCleanup,
    NothingToRecover,
    ObservedArtifact,
    PlannedCleanup,
    PreStateIntact,
    RefuseRecovery,
    RollbackInterrupted,
    ThirdStateFound,
    cleanup_step,
    preparation_matches_identity,
    recovery_action,
    restored_verification,
    sealed_verification,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.rollback import (
    AlreadyCandidate,
    AlreadyRestored,
    RemoveCreatedTreeAtomically,
    RestoreEmptyDirectoryAtomically,
    RestoreOldFile,
    RollbackStep,
    RollbackThirdState,
    SealedThirdState,
    derive_rollback_preparations,
    derive_rollback_specs,
    rollback_directory_step,
    rollback_file_step,
    rollback_steps,
    sealed_directory_step,
    sealed_file_step,
    sealed_steps,
)
from scripts.bootstrap.source_baseline import GitHubSourceBaseline
from scripts.bootstrap.state import (
    InvalidJournal,
    JournalObservation,
    JournalTargetMismatch,
    NoJournal,
    OrphanTransactionState,
    PendingIdentity,
    RecoveryEvidenceInvalid,
    StaleJournalWrite,
    ValidatedJournal,
)
from scripts.bootstrap.transaction import (
    CompiledTransaction,
    LockedTransaction,
    MutatingTransaction,
    PlannedTransaction,
    ValidatedLockedTransaction,
    VerifiedRestoredTransaction,
    derive_cleanup,
    derive_preparation_specs,
    restored_envelope,
)
from scripts.bootstrap.values import JournalPhase
from tests.factory import seed_repo

TARGET = target_identity(b"/work/example", device=1, inode=2)
NEW = b"fresh content\n"
NEW2 = b"replacement content\n"
OLD = b"old content\n"
STALE = b"stale content\n"
TREE_FILE = b"tree content\n"
TRANSACTION_ID = "cd" * 32

ABSENT_FILE = FileState(None, None)


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


def _fixture_plan() -> tuple[OperationPlan, VerifiedBlobStore, dict[bytes, ContentId]]:
    store, ids = _blob_store(NEW, NEW2, OLD, STALE, TREE_FILE)
    operations = (
        CreateFileOperation(
            path=RepoPath("app.py"),
            expected_old=ABSENT_FILE,
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
                identity=content_identity(NEW2, text=False),
                mode=PosixMode.EXECUTABLE,
                content_id=ids[NEW2],
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


@dataclass(slots=True)
class FakeFs:
    """In-memory mirror of the target tree used by the fake shell."""

    files: dict[str, tuple[bytes, int]]  # relative path -> (bytes, mode)
    directories: set[str]
    backups: dict[str, tuple[bytes, int]]  # relative path -> backup (bytes, mode)

    @classmethod
    def pre_state(cls) -> FakeFs:
        return cls(
            files={
                "README.md": (OLD, 0o644),
                "stale.txt": (STALE, 0o644),
            },
            directories={"empty"},
            backups={
                "README.md": (OLD, 0o644),
                "stale.txt": (STALE, 0o644),
            },
        )

    def apply(self, plan: OperationPlan) -> None:
        for operation in plan.ordered_operations:
            match operation:
                case CreateFileOperation(path=path, planned_new=planned):
                    content = _ok(self._content(plan, planned.content_id))
                    self.files[path.value] = (content, planned.mode.value)
                case ReplaceFileOperation(path=path, planned_new=planned):
                    content = _ok(self._content(plan, planned.content_id))
                    self.files[path.value] = (content, planned.mode.value)
                case DeleteFileOperation(path=path):
                    _ = self.files.pop(path.value, None)
                case CreateTreeOperation(root=root, planned_new=tree):
                    self.directories.add(root.value)
                    for entry in tree.entries:
                        match entry:
                            case PlannedDirectoryEntry(path=path):
                                self.directories.add(path.value)
                            case PlannedFileEntry(path=path, content_id=content_id):
                                content = _ok(self._content(plan, content_id))
                                self.files[path.value] = (content, PosixMode.FILE.value)
                case RemoveEmptyDirectoryOperation(path=path):
                    self.directories.discard(path.value)

    @staticmethod
    def _content(plan: OperationPlan, content_id: ContentId) -> Result[bytes, str]:
        content = plan.blob_store.get(content_id)
        if content is None:
            return Err("missing blob")
        return Ok(content)

    def execute_rollback(self, steps: tuple[RollbackStep, ...]) -> RollbackStep | None:
        """Execute decisions in reverse plan order; stop at the first third state."""
        for step in reversed(steps):
            decision = step.decision
            match decision:
                case AlreadyRestored():
                    continue
                case RestoreOldFile():
                    self._restore_old_file(step)
                case RemoveCreatedTreeAtomically():
                    self._remove_tree(step)
                case RestoreEmptyDirectoryAtomically():
                    self._restore_empty_directory(step)
                case RollbackThirdState():
                    return step
        return None

    def _restore_old_file(self, step: RollbackStep) -> None:
        backup = self.backups.get(step.path.value)
        if backup is not None:
            self.files[step.path.value] = backup
        else:
            _ = self.files.pop(step.path.value, None)

    def _remove_tree(self, step: RollbackStep) -> None:
        prefix = step.path.value + "/"
        self.files = {
            path: value
            for path, value in self.files.items()
            if path != step.path.value and not path.startswith(prefix)
        }
        self.directories = {
            path
            for path in self.directories
            if path != step.path.value and not path.startswith(prefix)
        }

    def _restore_empty_directory(self, step: RollbackStep) -> None:
        self.directories.add(step.path.value)

    def snapshot(self) -> TargetSnapshot:
        files = tuple(
            ObservedFileEntry(
                RepoPath(path),
                file_state_identity(content, text=False, mode=PosixMode(mode)),
                content,
            )
            for path, (content, mode) in sorted(self.files.items())
            if not path.startswith("pkg/")
        )
        directories: list[ObservedDirectoryEntry] = []
        for path in sorted(self.directories):
            if path == "pkg":
                entries: list[FileEntry | DirectoryEntry] = []
                for child, (content, mode) in sorted(self.files.items()):
                    if child.startswith("pkg/"):
                        entries.append(
                            FileEntry(RepoPath(child), content, PosixMode(mode))
                        )
                for child in sorted(self.directories):
                    if child.startswith("pkg/") and child != "pkg":
                        entries.append(
                            DirectoryEntry(RepoPath(child), PosixMode.DIRECTORY)
                        )
                directories.append(
                    ObservedDirectoryEntry(
                        RepoPath(path),
                        DirectoryState(PosixMode.DIRECTORY, tuple(entries)),
                    )
                )
            else:
                directories.append(
                    ObservedDirectoryEntry(
                        RepoPath(path), DirectoryState(PosixMode.DIRECTORY, ())
                    )
                )
        return TargetSnapshot(files=files, directories=tuple(directories))

    def assert_pre_state(self) -> None:
        assert self.files == {
            "README.md": (OLD, 0o644),
            "stale.txt": (STALE, 0o644),
        }
        assert self.directories == {"empty"}

    def assert_candidate_state(self) -> None:
        assert self.files["app.py"] == (NEW, 0o644)
        assert self.files["README.md"] == (NEW2, 0o755)
        assert "stale.txt" not in self.files
        assert self.files["pkg/__init__.py"] == (TREE_FILE, 0o644)
        assert "pkg" in self.directories and "pkg/sub" in self.directories
        assert "empty" not in self.directories


class TestRollbackFileStep:
    def test_absent_expected_absent_current_is_already_restored(self) -> None:
        assert (
            rollback_file_step(ABSENT_FILE, FileAbsent(), ABSENT_FILE)
            == AlreadyRestored()
        )

    def test_present_expected_present_current_is_already_restored(self) -> None:
        expected = file_state_identity(OLD, text=False, mode=PosixMode.FILE)
        assert rollback_file_step(expected, FileAbsent(), expected) == AlreadyRestored()

    def test_candidate_current_requests_restore(self) -> None:
        expected = file_state_identity(OLD, text=False, mode=PosixMode.FILE)
        planned = PlannedFilePresent(
            identity=content_identity(NEW, text=False),
            mode=PosixMode.FILE,
            content_id=ContentId.from_bytes(NEW),
        )
        current = file_state_identity(NEW, text=False, mode=PosixMode.FILE)
        assert rollback_file_step(expected, planned, current) == RestoreOldFile()

    def test_absent_original_requests_restore_when_candidate_present(self) -> None:
        planned = PlannedFilePresent(
            identity=content_identity(NEW, text=False),
            mode=PosixMode.FILE,
            content_id=ContentId.from_bytes(NEW),
        )
        current = file_state_identity(NEW, text=False, mode=PosixMode.FILE)
        assert rollback_file_step(ABSENT_FILE, planned, current) == RestoreOldFile()

    def test_delete_candidate_requests_restore(self) -> None:
        expected = file_state_identity(OLD, text=False, mode=PosixMode.FILE)
        assert (
            rollback_file_step(expected, FileAbsent(), ABSENT_FILE) == RestoreOldFile()
        )

    def test_foreign_current_is_third_state(self) -> None:
        expected = file_state_identity(OLD, text=False, mode=PosixMode.FILE)
        planned = PlannedFilePresent(
            identity=content_identity(NEW, text=False),
            mode=PosixMode.FILE,
            content_id=ContentId.from_bytes(NEW),
        )
        current = file_state_identity(b"foreign\n", text=False, mode=PosixMode.FILE)
        decision = rollback_file_step(expected, planned, current)
        assert isinstance(decision, RollbackThirdState)
        assert decision.observed == current

    def test_explicit_absent_entry_is_treated_as_absence(self) -> None:
        assert (
            rollback_file_step(ABSENT_FILE, FileAbsent(), FileState(None, None))
            == AlreadyRestored()
        )


class TestRollbackDirectoryStep:
    def _create_tree_operation(self, plan: OperationPlan) -> CreateTreeOperation:
        operation = plan.ordered_operations[3]
        assert isinstance(operation, CreateTreeOperation)
        return operation

    def _remove_empty_operation(
        self, plan: OperationPlan
    ) -> RemoveEmptyDirectoryOperation:
        operation = plan.ordered_operations[4]
        assert isinstance(operation, RemoveEmptyDirectoryOperation)
        return operation

    def test_create_tree_absent_is_already_restored(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._create_tree_operation(plan)
        assert rollback_directory_step(operation, None) == AlreadyRestored()

    def test_create_tree_candidate_requests_atomic_removal(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._create_tree_operation(plan)
        current = DirectoryState(
            PosixMode.DIRECTORY,
            (
                FileEntry(RepoPath("pkg/__init__.py"), TREE_FILE, PosixMode.FILE),
                DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),
            ),
        )
        decision = rollback_directory_step(operation, current)
        assert isinstance(decision, RemoveCreatedTreeAtomically)

    def test_create_tree_foreign_entry_is_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._create_tree_operation(plan)
        current = DirectoryState(
            PosixMode.DIRECTORY,
            (FileEntry(RepoPath("pkg/extra.txt"), b"foreign\n", PosixMode.FILE),),
        )
        decision = rollback_directory_step(operation, current)
        assert isinstance(decision, RollbackThirdState)

    def test_remove_empty_present_is_already_restored(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._remove_empty_operation(plan)
        current = DirectoryState(PosixMode.DIRECTORY, ())
        assert rollback_directory_step(operation, current) == AlreadyRestored()

    def test_remove_empty_absent_requests_atomic_restore(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._remove_empty_operation(plan)
        assert (
            rollback_directory_step(operation, None)
            == RestoreEmptyDirectoryAtomically()
        )

    def test_remove_empty_foreign_entry_is_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = self._remove_empty_operation(plan)
        current = DirectoryState(
            PosixMode.DIRECTORY,
            (FileEntry(RepoPath("empty/x"), b"foreign\n", PosixMode.FILE),),
        )
        decision = rollback_directory_step(operation, current)
        assert isinstance(decision, RollbackThirdState)


class TestSealedSteps:
    def test_file_candidate_is_already_candidate(self) -> None:
        planned = PlannedFilePresent(
            identity=content_identity(NEW, text=False),
            mode=PosixMode.FILE,
            content_id=ContentId.from_bytes(NEW),
        )
        current = file_state_identity(NEW, text=False, mode=PosixMode.FILE)
        assert sealed_file_step(planned, current) == AlreadyCandidate()

    def test_file_foreign_is_third_state(self) -> None:
        planned = PlannedFilePresent(
            identity=content_identity(NEW, text=False),
            mode=PosixMode.FILE,
            content_id=ContentId.from_bytes(NEW),
        )
        current = file_state_identity(b"foreign\n", text=False, mode=PosixMode.FILE)
        decision = sealed_file_step(planned, current)
        assert isinstance(decision, SealedThirdState)

    def test_delete_absent_is_already_candidate(self) -> None:
        assert sealed_file_step(FileAbsent(), ABSENT_FILE) == AlreadyCandidate()

    def test_directory_candidate_is_already_candidate(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = plan.ordered_operations[3]
        assert isinstance(operation, CreateTreeOperation)
        current = DirectoryState(
            PosixMode.DIRECTORY,
            (
                FileEntry(RepoPath("pkg/__init__.py"), TREE_FILE, PosixMode.FILE),
                DirectoryEntry(RepoPath("pkg/sub"), PosixMode.DIRECTORY),
            ),
        )
        assert sealed_directory_step(operation, current) == AlreadyCandidate()

    def test_directory_foreign_is_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = plan.ordered_operations[3]
        assert isinstance(operation, CreateTreeOperation)
        current = DirectoryState(PosixMode.DIRECTORY, ())
        decision = sealed_directory_step(operation, current)
        assert isinstance(decision, SealedThirdState)

    def test_remove_empty_absent_is_already_candidate(self) -> None:
        plan, _, _ = _fixture_plan()
        operation = plan.ordered_operations[4]
        assert isinstance(operation, RemoveEmptyDirectoryOperation)
        assert sealed_directory_step(operation, None) == AlreadyCandidate()


class TestPlanRollbackSteps:
    def test_candidate_snapshot_requests_restore_for_every_operation(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        steps = rollback_steps(plan, fs.snapshot())
        assert [type(step.decision).__name__ for step in steps] == [
            "RestoreOldFile",
            "RestoreOldFile",
            "RestoreOldFile",
            "RemoveCreatedTreeAtomically",
            "RestoreEmptyDirectoryAtomically",
        ]
        assert [step.path.value for step in steps] == [
            "app.py",
            "README.md",
            "stale.txt",
            "pkg",
            "empty",
        ]

    def test_pre_state_snapshot_is_already_restored(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        steps = rollback_steps(plan, fs.snapshot())
        assert all(isinstance(step.decision, AlreadyRestored) for step in steps)

    def test_third_state_path_is_reported(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        fs.files["app.py"] = (b"foreign\n", 0o644)
        steps = rollback_steps(plan, fs.snapshot())
        decision = steps[0].decision
        assert isinstance(decision, RollbackThirdState)


class TestSealedPlanSteps:
    def test_candidate_snapshot_is_already_candidate(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        steps = sealed_steps(plan, fs.snapshot())
        assert all(isinstance(step.decision, AlreadyCandidate) for step in steps)

    def test_pre_state_snapshot_is_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        steps = sealed_steps(plan, fs.snapshot())
        assert all(isinstance(step.decision, SealedThirdState) for step in steps)


class TestRollbackPreparations:
    def test_old_file_parts_absent_state_returns_none(self) -> None:
        assert old_file_parts(ABSENT_FILE) is None

    def test_rollback_specs_cover_every_restoring_operation(self) -> None:
        plan, _, _ = _fixture_plan()
        assert derive_rollback_specs(plan) == (
            PreparationSpec(
                1, PreparationRole.ROLLBACK, "file", sha256_hex(OLD), PosixMode.FILE
            ),
            PreparationSpec(
                2, PreparationRole.ROLLBACK, "file", sha256_hex(STALE), PosixMode.FILE
            ),
            PreparationSpec(
                3, PreparationRole.ROLLBACK, "directory", None, PosixMode.DIRECTORY
            ),
            PreparationSpec(
                4, PreparationRole.ROLLBACK, "directory", None, PosixMode.DIRECTORY
            ),
        )

    def test_derive_rollback_preparations_carries_identities(self) -> None:
        plan, _, _ = _fixture_plan()
        specs = derive_rollback_specs(plan)
        tokens = tuple(os.urandom(32) for _ in range(len(specs)))
        preparations = derive_rollback_preparations(plan, TRANSACTION_ID, tokens)
        for preparation, spec, token in zip(preparations, specs, tokens, strict=True):
            assert preparation.transaction_id == TRANSACTION_ID
            assert preparation.operation_index == spec.operation_index
            assert preparation.role is PreparationRole.ROLLBACK
            assert preparation.ownership_token_sha256 == sha256_hex(token)
            assert preparation.expected_kind == spec.expected_kind
            assert preparation.expected_raw_sha256 == spec.expected_raw_sha256
            assert preparation.expected_mode == spec.expected_mode

    def test_requires_one_token_per_rollback_preparation(self) -> None:
        plan, _, _ = _fixture_plan()
        with pytest.raises(ValueError, match="ownership token"):
            _ = derive_rollback_preparations(plan, TRANSACTION_ID, (os.urandom(32),))

    def test_restored_cleanup_includes_rollback_containers(self) -> None:
        plan, _, _ = _fixture_plan()
        cleanup = derive_cleanup(plan, JournalPhase.RESTORED)
        kinds = [item.kind.value for item in cleanup]
        assert kinds == [
            "stage",
            "stage",
            "backup",
            "backup",
            "stage",
            "rollback",
            "rollback",
            "rollback",
            "rollback",
            "transaction_directory",
            "journal",
        ]

    def test_restored_envelope_records_rollback_preparations(self) -> None:
        plan, _, _ = _fixture_plan()
        compiled = CompiledTransaction.compile(
            plan,
            ExpectedGatePass(readiness=evaluate_readiness()),
            transaction_id=TRANSACTION_ID,
            ownership_tokens=tuple(
                os.urandom(32) for _ in range(len(derive_preparation_specs(plan)))
            ),
        )
        locked = LockedTransaction(compiled)
        validated = ValidatedLockedTransaction(locked, TargetSnapshot((), ()))
        planned = PlannedTransaction(validated)
        verified = VerifiedRestoredTransaction(MutatingTransaction(planned))
        rollback_preparations = derive_rollback_preparations(
            plan,
            TRANSACTION_ID,
            tuple(os.urandom(32) for _ in range(len(derive_rollback_specs(plan)))),
        )
        envelope = restored_envelope(verified, rollback_preparations)
        assert envelope.phase is JournalPhase.RESTORED
        assert envelope.preparations == (
            *compiled.preparations,
            *rollback_preparations,
        )
        assert decode_journal(encode_journal(envelope)) == Ok(envelope)


class TestRecoveryAction:
    def test_no_journal_is_nothing_to_recover(self) -> None:
        assert recovery_action(NoJournal(), TARGET) == NothingToRecover()

    def test_stale_pending_is_discardable_only_by_recover(self) -> None:
        observation = StaleJournalWrite(PendingIdentity("ab" * 32))
        action = recovery_action(observation, TARGET)
        assert isinstance(action, DiscardStalePending)
        assert action.pending == PendingIdentity("ab" * 32)

    @pytest.mark.parametrize(
        "phase, expected",
        [
            (JournalPhase.PLANNED, PlannedCleanup),
            (JournalPhase.MUTATING, RollbackInterrupted),
            (JournalPhase.RESTORED, FinishRestoredCleanup),
            (JournalPhase.SEALED, FinishSealedCleanup),
        ],
    )
    def test_phase_maps_to_the_only_legal_recovery_action(
        self, phase: JournalPhase, expected: type[object]
    ) -> None:
        journal = ValidatedJournal(operation="initial", target=TARGET, phase=phase)
        action = recovery_action(journal, TARGET)
        assert isinstance(action, expected)
        narrowed = cast(
            PlannedCleanup
            | RollbackInterrupted
            | FinishRestoredCleanup
            | FinishSealedCleanup,
            action,
        )
        assert narrowed.journal == journal

    def test_restored_never_reinstalls_a_candidate(self) -> None:
        journal = ValidatedJournal(
            operation="initial", target=TARGET, phase=JournalPhase.RESTORED
        )
        assert isinstance(recovery_action(journal, TARGET), FinishRestoredCleanup)
        assert not isinstance(recovery_action(journal, TARGET), RollbackInterrupted)

    def test_sealed_never_rolls_back_a_verified_candidate(self) -> None:
        journal = ValidatedJournal(
            operation="initial", target=TARGET, phase=JournalPhase.SEALED
        )
        assert isinstance(recovery_action(journal, TARGET), FinishSealedCleanup)
        assert not isinstance(recovery_action(journal, TARGET), RollbackInterrupted)

    def test_target_mismatch_refuses_recovery(self) -> None:
        journal = ValidatedJournal(
            operation="initial",
            target=target_identity(b"/other", device=1, inode=2),
            phase=JournalPhase.MUTATING,
        )
        action = recovery_action(journal, TARGET)
        assert isinstance(action, RefuseRecovery)
        assert isinstance(action.reason, JournalTargetMismatch)

    @pytest.mark.parametrize(
        "observation",
        [
            InvalidJournal("corrupt"),
            RecoveryEvidenceInvalid(
                ValidatedJournal(
                    operation="initial", target=TARGET, phase=JournalPhase.MUTATING
                ),
                "evidence mismatch",
            ),
            OrphanTransactionState("unexpected shape"),
            JournalTargetMismatch(
                ValidatedJournal(
                    operation="initial", target=TARGET, phase=JournalPhase.SEALED
                ),
                target_identity(b"/other", device=1, inode=2),
            ),
        ],
    )
    def test_invalid_observations_refuse_recovery(
        self, observation: JournalObservation
    ) -> None:
        action = recovery_action(observation, TARGET)
        assert isinstance(action, RefuseRecovery)


class TestRecoveryVerification:
    def test_restored_verification_accepts_exact_pre_state(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        assert restored_verification(plan, fs.snapshot()) == PreStateIntact()

    def test_restored_verification_never_reapplies_a_candidate(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        result = restored_verification(plan, fs.snapshot())
        assert isinstance(result, ThirdStateFound)
        assert result.path == RepoPath("app.py")

    def test_sealed_verification_accepts_exact_candidate(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        assert sealed_verification(plan, fs.snapshot()) == CandidateIntact()

    def test_sealed_verification_reports_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        result = sealed_verification(plan, fs.snapshot())
        assert isinstance(result, ThirdStateFound)


class TestPreparationOwnership:
    def test_matching_artifact_is_verified(self) -> None:
        identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=1,
            role=PreparationRole.BACKUP,
            ownership_token_sha256="ab" * 32,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(OLD),
            expected_mode=PosixMode.FILE,
        )
        assert (
            preparation_matches_identity(
                identity,
                observed_kind="file",
                observed_raw_sha256=sha256_hex(OLD),
                observed_mode=PosixMode.FILE,
            )
            is True
        )

    @pytest.mark.parametrize(
        "kind, digest, mode",
        [
            ("directory", sha256_hex(OLD), PosixMode.FILE),
            ("file", sha256_hex(NEW), PosixMode.FILE),
            ("file", sha256_hex(OLD), PosixMode.EXECUTABLE),
        ],
    )
    def test_any_mismatch_is_not_verified(
        self, kind: Literal["file", "directory"], digest: str, mode: PosixMode
    ) -> None:
        identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=1,
            role=PreparationRole.BACKUP,
            ownership_token_sha256="ab" * 32,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(OLD),
            expected_mode=PosixMode.FILE,
        )
        assert (
            preparation_matches_identity(
                identity,
                observed_kind=kind,
                observed_raw_sha256=digest,
                observed_mode=mode,
            )
            is False
        )

    def test_missing_artifact_is_already_clean(self) -> None:
        identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=1,
            role=PreparationRole.BACKUP,
            ownership_token_sha256="ab" * 32,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(OLD),
            expected_mode=PosixMode.FILE,
        )
        assert cleanup_step(identity, None) == CleanupMissing()

    def test_matching_artifact_is_verified_clean(self) -> None:
        identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=1,
            role=PreparationRole.BACKUP,
            ownership_token_sha256="ab" * 32,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(OLD),
            expected_mode=PosixMode.FILE,
        )
        observed = ObservedArtifact(
            kind="file", raw_sha256=sha256_hex(OLD), mode=PosixMode.FILE
        )
        assert cleanup_step(identity, observed) == CleanupVerified()

    def test_mismatched_artifact_is_third_state(self) -> None:
        identity = PreparationIdentity(
            transaction_id=TRANSACTION_ID,
            operation_index=1,
            role=PreparationRole.BACKUP,
            ownership_token_sha256="ab" * 32,
            expected_kind="file",
            expected_raw_sha256=sha256_hex(OLD),
            expected_mode=PosixMode.FILE,
        )
        observed = ObservedArtifact(
            kind="file", raw_sha256=sha256_hex(b"foreign\n"), mode=PosixMode.FILE
        )
        assert isinstance(cleanup_step(identity, observed), CleanupThirdState)


class TestFakeShellRollback(unittest.TestCase):
    def test_rollback_restores_exact_bytes_modes_and_topology(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        fs.assert_candidate_state()
        steps = rollback_steps(plan, fs.snapshot())
        stopped = fs.execute_rollback(steps)
        assert stopped is None
        fs.assert_pre_state()

    def test_rollback_is_idempotent(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        steps = rollback_steps(plan, fs.snapshot())
        assert fs.execute_rollback(steps) is None
        fs.assert_pre_state()
        second_steps = rollback_steps(plan, fs.snapshot())
        assert all(isinstance(step.decision, AlreadyRestored) for step in second_steps)
        assert fs.execute_rollback(second_steps) is None
        fs.assert_pre_state()

    def test_third_state_is_preserved_and_stops_rollback(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        foreign = b"foreign content\n"
        fs.files["app.py"] = (foreign, 0o644)
        steps = rollback_steps(plan, fs.snapshot())
        stopped = fs.execute_rollback(steps)
        assert stopped is not None
        assert stopped.path == RepoPath("app.py")
        assert isinstance(stopped.decision, RollbackThirdState)
        assert fs.files["app.py"] == (foreign, 0o644)
        assert "README.md" in fs.files
        assert "pkg" not in fs.directories

    def test_directory_third_state_is_preserved(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        fs.files["pkg/extra.txt"] = (b"foreign\n", 0o644)
        steps = rollback_steps(plan, fs.snapshot())
        stopped = fs.execute_rollback(steps)
        assert stopped is not None
        assert stopped.path == RepoPath("pkg")
        assert isinstance(stopped.decision, RollbackThirdState)
        assert fs.files["pkg/extra.txt"] == (b"foreign\n", 0o644)

    def test_evidence_survives_third_state(self) -> None:
        plan, _, _ = _fixture_plan()
        fs = FakeFs.pre_state()
        fs.apply(plan)
        fs.files["app.py"] = (b"foreign\n", 0o644)
        steps = rollback_steps(plan, fs.snapshot())
        stopped = fs.execute_rollback(steps)
        assert stopped is not None
        assert fs.backups == {
            "README.md": (OLD, 0o644),
            "stale.txt": (STALE, 0o644),
        }

    def test_git_clean_survives_administrative_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = seed_repo(Path(tmp), {"tracked.txt": "tracked"})
            state_root = repo / ".git" / "rygor"
            backup = state_root / "transactions" / TRANSACTION_ID / "backups" / "1"
            backup.parent.mkdir(parents=True)
            _ = backup.write_bytes(b"backup-bytes")
            _ = (repo / "scratch.txt").write_text("untracked", encoding="utf-8")
            _ = subprocess.run(
                ["git", "clean", "-fdx"], cwd=repo, check=True, capture_output=True
            )
            self.assertEqual(backup.read_bytes(), b"backup-bytes")
            self.assertFalse((repo / "scratch.txt").exists())


@settings(max_examples=30, deadline=None)
@given(
    st.lists(
        st.sampled_from(("apply", "crash")),
        min_size=1,
        max_size=12,
    )
)
def test_crash_sequences_resume_to_exact_pre_state(script: list[str]) -> None:
    plan, _, _ = _fixture_plan()
    fs = FakeFs.pre_state()
    operations = plan.ordered_operations
    applied = 0
    for step in script:
        if step == "apply" and applied < len(operations):
            fs.apply(_plan(operations[applied : applied + 1], plan.blob_store))
            applied += 1
        # "crash" leaves the current partial state in place
    steps = rollback_steps(plan, fs.snapshot())
    assert fs.execute_rollback(steps) is None
    fs.assert_pre_state()


class RollbackCrashStateMachine(RuleBasedStateMachine):
    plan: OperationPlan
    fs: FakeFs
    applied: int
    rolling_back: bool
    cursor: int
    foreign: str | None

    def __init__(self) -> None:
        super().__init__()
        self.plan, _, _ = _fixture_plan()
        self.fs = FakeFs.pre_state()
        self.applied = 0
        self.rolling_back = False
        self.cursor = len(self.plan.ordered_operations) - 1
        self.foreign = None

    def _apply_one(self) -> None:
        operations = self.plan.ordered_operations[self.applied : self.applied + 1]
        self.fs.apply(_plan(operations, self.plan.blob_store))
        self.applied += 1

    def _rollback_one(self) -> bool:
        """Execute one rollback step in reverse; returns True when stopped."""
        steps = rollback_steps(self.plan, self.fs.snapshot())
        step = steps[self.cursor]
        if isinstance(step.decision, RollbackThirdState):
            return True
        assert self.fs.execute_rollback((step,)) is None
        self.cursor -= 1
        return False

    @rule()
    def apply_next(self) -> None:
        if self.rolling_back or self.foreign is not None:
            return
        if self.applied >= len(self.plan.ordered_operations):
            return
        self._apply_one()

    @rule()
    def rollback_next(self) -> None:
        if self.applied == 0 or self.cursor < 0:
            return
        self.rolling_back = True
        if self._rollback_one():
            return

    @rule(data=st.data())
    def inject_foreign_file(self, data: st.DataObject) -> None:
        if self.rolling_back or self.applied == 0 or self.foreign is not None:
            return
        path = data.draw(st.sampled_from(["app.py", "README.md"]))
        if path not in self.fs.files:
            return
        self.fs.files[path] = (b"foreign-injected\n", 0o600)
        self.foreign = path

    @rule()
    def crash(self) -> None:
        return

    @invariant()
    def rollback_never_overwrites_foreign_state(self) -> None:
        if self.foreign is not None:
            assert self.fs.files[self.foreign] == (b"foreign-injected\n", 0o600)

    @invariant()
    def applied_paths_match_expected(self) -> None:
        if self.rolling_back:
            return
        fs = self.fs
        expected_files = dict(fs.backups)
        expected_dirs = {"empty"}
        if self.applied >= 1:
            expected_files["app.py"] = (NEW, 0o644)
        if self.applied >= 2:
            expected_files["README.md"] = (NEW2, 0o755)
        if self.applied >= 3:
            expected_files = {
                path: value
                for path, value in expected_files.items()
                if path != "stale.txt"
            }
        if self.applied >= 4:
            expected_dirs.update({"pkg", "pkg/sub"})
            expected_files["pkg/__init__.py"] = (TREE_FILE, 0o644)
        if self.applied >= 5:
            expected_dirs.discard("empty")
        if self.foreign is None:
            assert fs.files == expected_files
            assert fs.directories == expected_dirs


TestRollbackCrashStateMachine = cast(
    type[unittest.TestCase], RollbackCrashStateMachine.TestCase
)
