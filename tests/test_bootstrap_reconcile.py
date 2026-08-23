"""Tests for the reconcile transition plan compilation and reconcile decisions."""

from __future__ import annotations

from collections.abc import Mapping

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.decisions import (
    CompileCandidate,
    ReconcileTemplate,
    RefuseMutation,
    decide_project,
)
from scripts.bootstrap.errors import TransitionError, TransitionErrorKind
from scripts.bootstrap.identity import (
    ManifestIdentity,
    PosixMode,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import (
    GenerationPath,
    PlanReconcile,
    ReconcileOptions,
)
from scripts.bootstrap.intents import (
    Reconcile as ReconcileIntent,
)
from scripts.bootstrap.manifest import (
    MaintenanceRecord,
    ManifestAdditions,
    ManifestAnswers,
    decode_manifest,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import (
    build_receipt,
    decode_receipt,
    encode_receipt,
    reconstruct_plan,
)
from scripts.bootstrap.planner import (
    RECONCILE_OPERATION_KIND,
    CompileErrorKind,
    CreateTreeOperation,
    DeleteFileOperation,
    OperationPlan,
    ReadinessRule,
    RemoveEmptyDirectoryOperation,
    TargetSnapshot,
    compile_reconcile_plan,
)
from scripts.bootstrap.render import (
    ManagedFile,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    template_source_fingerprint,
)
from scripts.bootstrap.state import (
    CopierCondition,
    CopierExistingProject,
    CopierSourceChanged,
    ExistingProject,
    ManagedVerified,
    OrdinaryProject,
    ProjectAvailable,
    RecordedProjectState,
    SnapshotExistingProject,
    SnapshotSourceSame,
    SourceDelta,
    SupportedWorktree,
    WorktreeContext,
)
from scripts.bootstrap.state import (
    TargetSnapshot as StateTargetSnapshot,
)
from scripts.bootstrap.values import DEFAULT_LIMITS
from tests.bootstrap_fixtures import (
    TARGET,
    copier_source_baseline,
    fixture_answers,
    observed_snapshot,
    render_for,
)


def _render_for(
    effective: tuple[str, ...],
    settings: Mapping[str, Mapping[str, str | bool]] | None = None,
) -> tuple[tuple[ManagedFile, ...], VerifiedBlobStore]:
    return render_for(effective, GenerationPath.COPIER, settings)


def _fixture_answers() -> ManifestAnswers:
    return fixture_answers()


def _source_baseline(seed: bytes) -> CopierSourceBaseline:
    return copier_source_baseline(seed)


def _observed(
    managed: tuple[ManagedFile, ...], *, drift: Mapping[str, bytes] | None = None
) -> TargetSnapshot:
    return observed_snapshot(managed, drift=drift)


def _manifest(seed: bytes) -> ManifestIdentity:
    value = sha256_hex(seed)
    return ManifestIdentity(payload=value.encode(), digest=value)


class TestCompileReconcilePlan:
    @staticmethod
    def _transition_render(path: str, content: bytes) -> tuple[ManagedFile, ...]:
        return (ManagedFile(RepoPath(path), "text", PosixMode.FILE, content),)

    def _compile_transition(
        self,
        old_render: tuple[ManagedFile, ...],
        new_render: tuple[ManagedFile, ...],
    ) -> OperationPlan:
        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=new_render,
            existing_inventory=derive_managed_inventory(old_render),
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=_observed(old_render),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok), result
        return result.value

    def test_reconcile_retires_file_before_creating_tree(self) -> None:
        plan = self._compile_transition(
            self._transition_render("foo", b"old"),
            self._transition_render("foo/bar", b"new"),
        )
        assert isinstance(plan.ordered_operations[0], DeleteFileOperation)
        assert plan.ordered_operations[0].path == RepoPath("foo")
        assert any(
            isinstance(operation, CreateTreeOperation)
            for operation in plan.ordered_operations
        )

    def test_reconcile_removes_empty_tree_before_creating_file(self) -> None:
        plan = self._compile_transition(
            self._transition_render("foo/bar", b"old"),
            self._transition_render("foo", b"new"),
        )
        assert isinstance(plan.ordered_operations[0], DeleteFileOperation)
        assert plan.ordered_operations[0].path == RepoPath("foo/bar")
        assert any(
            operation.path == RepoPath("foo")
            for operation in plan.ordered_operations
            if isinstance(operation, RemoveEmptyDirectoryOperation)
        )

    def test_reconcile_deletes_retired_managed_output(self) -> None:
        old_render, _blobs = _render_for(())
        new_render = old_render[:-1]
        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=new_render,
            existing_inventory=derive_managed_inventory(old_render),
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=_observed(old_render),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok), result
        deleted = {
            operation.path
            for operation in result.value.ordered_operations
            if isinstance(operation, DeleteFileOperation)
        }
        assert deleted == {old_render[-1].path}

    def test_reconcile_advances_source_baseline(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        snapshot = _observed(managed)

        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            overwrite_drift=False,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        assert plan.operation_kind == RECONCILE_OPERATION_KIND
        # The source baseline is advanced by a reconcile.
        assert plan.source_before is not None
        assert plan.source_before.fingerprint == template_source_fingerprint(
            plan.source_before.entries
        )
        assert plan.source_after.fingerprint == template_source_fingerprint(
            plan.source_after.entries
        )
        # The manifest is rewritten to carry the new source baseline.
        assert plan.manifest_before is not None
        assert plan.manifest_before.digest == sha256_hex(b"old")
        assert plan.manifest_after.digest != plan.manifest_before.digest
        match decode_manifest(plan.manifest_after.payload):
            case Ok(decoded):
                assert decoded.provenance.source_baseline.fingerprint == (
                    template_source_fingerprint(
                        decoded.provenance.source_baseline.entries
                    )
                )
            case Err(error):
                raise AssertionError(f"manifest decode failed: {error}")
        assert plan.gate_specification.readiness_rule == ReadinessRule.NO_WORSE_BLOCKING

    def test_reconcile_refuses_drift_without_overwrite(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"adopter edit\n"}
        snapshot = _observed(managed, drift=drifted)

        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            overwrite_drift=False,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION
        assert "managed_drift" in result.error.subject

    def test_reconcile_allows_drift_with_overwrite(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"adopter edit\n"}
        snapshot = _observed(managed, drift=drifted)

        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            overwrite_drift=True,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        assert result.value.source_before is not None
        assert result.value.source_before.fingerprint == template_source_fingerprint(
            result.value.source_before.entries
        )
        assert result.value.source_after.fingerprint == template_source_fingerprint(
            result.value.source_after.entries
        )

    def test_reconcile_rebuilds_deleted_parent_hierarchy(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        snapshot = _observed(managed)
        directories = tuple(
            entry
            for entry in snapshot.directories
            if not managed[0].path.value.startswith(entry.path.value + "/")
        )
        deleted = TargetSnapshot(files=snapshot.files, directories=directories)

        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=deleted,
            overwrite_drift=True,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        assert any(
            isinstance(operation, CreateTreeOperation)
            and managed[0].path.value
            in {entry.path.value for entry in operation.planned_new.entries}
            for operation in result.value.ordered_operations
        )

    def test_reconcile_receipt_round_trips(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        snapshot = _observed(managed)

        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=_source_baseline(b"old"),
            new_source_baseline=_source_baseline(b"new"),
            old_manifest=_manifest(b"old"),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            overwrite_drift=False,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Err(error):
                raise AssertionError(f"reconcile receipt decode failed: {error}")
            case Ok(decoded):
                assert decoded["operation_kind"] == "reconcile"
        match reconstruct_plan(receipt, target=plan.target_identity):
            case Err(error):
                raise AssertionError(
                    f"reconcile receipt reconstruction failed: {error}"
                )
            case Ok(reconstructed):
                assert reconstructed.operation_kind == RECONCILE_OPERATION_KIND
                assert reconstructed.ordered_operations == plan.ordered_operations
                assert reconstructed.source_after == plan.source_after
                assert reconstructed.manifest_after.digest == plan.manifest_after.digest


def _worktree() -> SupportedWorktree:
    return SupportedWorktree(
        WorktreeContext(
            target=target_identity(b"/tmp/project", device=1, inode=2),
            state_root=RepoPath(".agentic-template"),
            protection=OrdinaryProject(),
        )
    )


def _system_with(condition: SnapshotSourceSame | CopierCondition) -> ProjectAvailable:
    recorded = RecordedProjectState(GenerationPath.COPIER)
    if isinstance(condition, SnapshotSourceSame):
        project = SnapshotExistingProject(recorded, condition, StateTargetSnapshot(()))
    else:
        project = CopierExistingProject(recorded, condition, StateTargetSnapshot(()))
    return ProjectAvailable(_worktree(), ExistingProject(project))


class TestReconcileDecisions:
    def test_reconcile_accepts_changed_copier_source(self) -> None:
        decision = decide_project(
            ReconcileIntent(ReconcileOptions()),
            _system_with(
                CopierSourceChanged(
                    SourceDelta((RepoPath("source.txt"),)), ManagedVerified()
                )
            ),
        )
        assert isinstance(decision, ReconcileTemplate)

    def test_plan_reconcile_accepts_changed_copier_source(self) -> None:
        decision = decide_project(
            PlanReconcile(ReconcileOptions()),
            _system_with(
                CopierSourceChanged(
                    SourceDelta((RepoPath("source.txt"),)), ManagedVerified()
                )
            ),
        )
        assert isinstance(decision, CompileCandidate)

    def test_snapshots_refuse_reconcile(self) -> None:
        decision = decide_project(
            ReconcileIntent(ReconcileOptions()),
            _system_with(SnapshotSourceSame(ManagedVerified())),
        )
        assert isinstance(decision, RefuseMutation)
        assert isinstance(decision.error, TransitionError)
        assert decision.error.kind == TransitionErrorKind.OPERATION_UNAVAILABLE

    def test_copier_source_delta_names_exact_paths(self) -> None:
        condition = CopierSourceChanged(
            SourceDelta((RepoPath("a.txt"), RepoPath("b.txt"))), ManagedVerified()
        )
        assert condition.delta.paths == (RepoPath("a.txt"), RepoPath("b.txt"))
