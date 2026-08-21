"""Tests for the restore transition plan compilation and restore decisions."""

from __future__ import annotations

from dataclasses import replace

from scripts.bootstrap.decisions import (
    RefuseMutation,
    RestoreManaged,
    decide_project,
)
from scripts.bootstrap.errors import TransitionError, TransitionErrorKind
from scripts.bootstrap.identity import (
    ManifestIdentity,
    target_identity,
)
from scripts.bootstrap.intents import (
    GenerationPath,
    RestoreOptions,
)
from scripts.bootstrap.intents import (
    Restore as RestoreIntent,
)
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import (
    build_receipt,
    decode_receipt,
    encode_receipt,
    reconstruct_plan,
)
from scripts.bootstrap.planner import (
    RESTORE_OPERATION_KIND,
    CompileErrorKind,
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    ReadinessRule,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    TargetSnapshot,
    compile_restore_plan,
)
from scripts.bootstrap.render import (
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.state import (
    CopierCondition,
    CopierExistingProject,
    CopierSourceSame,
    ExistingProject,
    ManagedDrift,
    ManagedVerified,
    OrdinaryProject,
    PathDelta,
    ProjectAvailable,
    RecordedProjectState,
    SnapshotCondition,
    SnapshotExistingProject,
    SnapshotRepair,
    SnapshotSourceChanged,
    SnapshotSourceSame,
    SnapshotSourceUnrecoverable,
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
    fixture_answers,
    github_source_baseline,
    observed_snapshot,
    render_for,
)


def _current_manifest() -> ManifestIdentity:
    return ManifestIdentity(payload=b"manifest", digest="0" * 64)


class TestCompileRestorePlan:
    def test_restore_selects_only_drifted_paths(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"drifted bytes\n"}
        snapshot = observed_snapshot(managed, drift=drifted)

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        assert plan.operation_kind == RESTORE_OPERATION_KIND
        restored = {
            op.path.value
            for op in plan.ordered_operations
            if isinstance(op, (CreateFileOperation, ReplaceFileOperation))
        }
        assert restored == {managed[0].path.value}
        assert all(
            op.path != MANIFEST_PATH
            for op in plan.ordered_operations
            if isinstance(
                op,
                (
                    CreateFileOperation,
                    ReplaceFileOperation,
                    DeleteFileOperation,
                    RemoveEmptyDirectoryOperation,
                ),
            )
        )
        assert plan.manifest_before == plan.manifest_after
        assert plan.gate_specification.readiness_rule == ReadinessRule.NO_WORSE_BLOCKING

    def test_restore_leaves_unrelated_drift(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"a\n", managed[1].path.value: b"b\n"}
        snapshot = observed_snapshot(managed, drift=drifted)

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            requested_paths=(managed[0].path,),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        restored = {
            op.path.value
            for op in result.value.ordered_operations
            if isinstance(op, (CreateFileOperation, ReplaceFileOperation))
        }
        assert restored == {managed[0].path.value}

    def test_restore_normalizes_requested_paths(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        first, second = managed[:2]
        inventory = derive_managed_inventory(managed)
        snapshot = observed_snapshot(
            managed,
            drift={first.path.value: b"a\n", second.path.value: b"b\n"},
        )

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            requested_paths=(second.path, first.path, first.path),
            limits=DEFAULT_LIMITS,
        )

        assert isinstance(result, Ok)
        restored = [
            operation.path.value
            for operation in result.value.ordered_operations
            if isinstance(operation, (CreateFileOperation, ReplaceFileOperation))
        ]
        assert restored == sorted(
            {first.path.value, second.path.value},
            key=lambda value: value.encode("utf-8"),
        )

    def test_restore_refuses_unmanaged_path(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        snapshot = observed_snapshot(managed)

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            requested_paths=(RepoPath("not/managed.txt"),),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.INVALID_TARGET

    def test_restore_refuses_render_contract_violation(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        snapshot = observed_snapshot(managed)
        tampered = tuple(
            replace(entry, sha256="wrong" * 10) if i == 0 else entry
            for i, entry in enumerate(inventory)
        )

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=tampered,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            requested_paths=(managed[0].path,),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION

    def test_restore_refuses_diverged_auto_drift(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"drifted bytes\n"}
        snapshot = observed_snapshot(managed, drift=drifted)
        diverged = tuple(
            replace(file, content=b"template changed\n")
            if file.path == managed[0].path
            else file
            for file in managed
        )

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=diverged,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION
        assert "render_mismatch" in result.error.subject

    def test_restore_repairs_deleted_parent_hierarchy(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        snapshot = observed_snapshot(managed)
        files = tuple(
            entry for entry in snapshot.files if entry.path != managed[0].path
        )
        directories = tuple(
            entry
            for entry in snapshot.directories
            if not managed[0].path.value.startswith(entry.path.value + "/")
        )
        deleted = TargetSnapshot(files=files, directories=directories)

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=deleted,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        assert any(
            isinstance(operation, CreateTreeOperation)
            and managed[0].path.value
            in {entry.path.value for entry in operation.planned_new.entries}
            for operation in plan.ordered_operations
        )

    def test_restore_receipt_round_trips(self) -> None:
        managed, _blobs = render_for((), GenerationPath.GITHUB)
        inventory = derive_managed_inventory(managed)
        drifted = {managed[0].path.value: b"drifted bytes\n"}
        snapshot = observed_snapshot(managed, drift=drifted)

        result = compile_restore_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=_current_manifest(),
            source_baseline=github_source_baseline(),
            snapshot=snapshot,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Err(error):
                raise AssertionError(f"restore receipt decode failed: {error}")
            case Ok(decoded):
                assert decoded["operation_kind"] == "restore"
        match reconstruct_plan(receipt, target=plan.target_identity):
            case Err(error):
                raise AssertionError(f"restore receipt reconstruction failed: {error}")
            case Ok(reconstructed):
                assert reconstructed.operation_kind == RESTORE_OPERATION_KIND
                assert reconstructed.ordered_operations == plan.ordered_operations
                assert reconstructed.manifest_after.digest == plan.manifest_after.digest


def _worktree() -> SupportedWorktree:
    return SupportedWorktree(
        WorktreeContext(
            target=target_identity(b"/tmp/project", device=1, inode=2),
            state_root=RepoPath(".agentic-template"),
            protection=OrdinaryProject(),
        )
    )


def _system_with(condition: SnapshotCondition | CopierCondition) -> ProjectAvailable:
    recorded = RecordedProjectState(GenerationPath.GITHUB)
    if isinstance(
        condition,
        (SnapshotSourceSame, SnapshotSourceChanged, SnapshotSourceUnrecoverable),
    ):
        project = SnapshotExistingProject(recorded, condition, StateTargetSnapshot(()))
    else:
        project = CopierExistingProject(recorded, condition, StateTargetSnapshot(()))
    return ProjectAvailable(_worktree(), ExistingProject(project))


class TestRestoreDecisions:
    def test_restore_accepts_same_source_copier(self) -> None:
        decision = decide_project(
            RestoreIntent(RestoreOptions()),
            _system_with(CopierSourceSame(ManagedVerified())),
        )
        assert isinstance(decision, RestoreManaged)

    def test_restore_accepts_managed_drift_as_its_purpose(self) -> None:
        decision = decide_project(
            RestoreIntent(RestoreOptions()),
            _system_with(
                CopierSourceSame(ManagedDrift(PathDelta((RepoPath("managed.txt"),))))
            ),
        )
        assert isinstance(decision, RestoreManaged)

    def test_restore_refuses_changed_snapshot_source(self) -> None:
        decision = decide_project(
            RestoreIntent(RestoreOptions()),
            _system_with(
                SnapshotSourceChanged(
                    SourceDelta((RepoPath("source.txt"),)),
                    SnapshotRepair("0" * 40, (RepoPath("source.txt"),)),
                    ManagedVerified(),
                )
            ),
        )
        assert isinstance(decision, RefuseMutation)
        assert isinstance(decision.error, TransitionError)
        assert decision.error.kind == TransitionErrorKind.TEMPLATE_CHANGED
        assert "repair snapshot baseline" in decision.error.subject
        assert "source.txt" in decision.error.subject

    def test_restore_preserves_snapshot_regeneration_guidance(self) -> None:
        decision = decide_project(
            RestoreIntent(RestoreOptions()),
            _system_with(
                SnapshotSourceUnrecoverable(
                    SourceDelta((RepoPath("source.txt"),)),
                    "recorded content differs at commit",
                    ManagedVerified(),
                )
            ),
        )
        assert isinstance(decision, RefuseMutation)
        assert isinstance(decision.error, TransitionError)
        assert decision.error.kind == TransitionErrorKind.TEMPLATE_CHANGED
        assert "regenerate from the current template" in decision.error.subject
        assert "recorded content differs at commit" in decision.error.subject

    def test_snapshot_source_delta_names_exact_paths(self) -> None:
        condition = SnapshotSourceChanged(
            SourceDelta((RepoPath("a.txt"), RepoPath("b.txt"))),
            SnapshotRepair("0" * 40, (RepoPath("a.txt"), RepoPath("b.txt"))),
            ManagedVerified(),
        )
        assert condition.delta.paths == (RepoPath("a.txt"), RepoPath("b.txt"))
