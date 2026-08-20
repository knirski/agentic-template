"""Tests for the add transition, old-render oracle, and expanded selection compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.identity import (
    PosixMode,
    file_state_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    MaintenanceRecord,
    ManagedInventory,
    ManifestAdditions,
    ManifestAnswers,
    decode_manifest,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    ADD_OPERATION_KIND,
    CompileErrorKind,
    CreateFileOperation,
    ObservedFileEntry,
    ReadinessRule,
    ReplaceFileOperation,
    TargetSnapshot,
    compile_add_plan,
    verify_old_render_oracle,
)
from scripts.bootstrap.render import (
    ManagedFile,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.source_baseline import (
    GitHubSourceBaseline,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits
from tests.bootstrap_fixtures import (
    TARGET,
    fixture_answers,
    github_source_baseline,
    render_for,
)

APACHE_TEXT = b"Apache License\nVersion 2.0, January 2004\n"
LEGAL_CONTENTS: dict[str, dict[str, bytes]] = {
    "retain-apache-2.0": {
        "LICENSE": APACHE_TEXT,
        "NOTICE.md": b"# Notices\n\nBundled skills are covered by their upstream licences.\n",
    },
}


def _render_for(
    effective: tuple[str, ...],
    settings: Mapping[str, Mapping[str, str | bool]] | None = None,
) -> tuple[tuple[ManagedFile, ...], VerifiedBlobStore]:
    return render_for(effective, GenerationPath.GITHUB, settings)


def _fixture_answers() -> ManifestAnswers:
    return fixture_answers()


def _source_baseline() -> GitHubSourceBaseline:
    return github_source_baseline()


class TestVerifyOldRenderOracle:
    def test_matching_render_succeeds(self) -> None:
        managed, _blobs = _render_for(())
        inventory = derive_managed_inventory(managed)
        result = verify_old_render_oracle(managed, inventory)
        assert isinstance(result, Ok)

    def test_mismatched_entry_count_fails(self) -> None:
        managed, _blobs = _render_for(())
        empty_inventory: ManagedInventory = ()
        result = verify_old_render_oracle(managed, empty_inventory)
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION
        assert "entry_count_mismatch" in result.error.subject

    def test_mismatched_hash_fails(self) -> None:
        managed, _blobs = _render_for(())
        wrong_inventory = tuple(
            replace(entry, sha256="wrong_hash")
            for entry in derive_managed_inventory(managed)
        )
        result = verify_old_render_oracle(managed, wrong_inventory)
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION
        assert "hash_mismatch" in result.error.subject


class TestCompileAddPlan:
    def test_add_empty_to_empty(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(())
        existing_inventory = derive_managed_inventory(managed_old)

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=(),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        assert plan.operation_kind == ADD_OPERATION_KIND
        assert plan.gate_specification.operation == "add"
        assert plan.gate_specification.readiness_rule == ReadinessRule.NO_WORSE_BLOCKING

    def test_add_capability_produces_new_files(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        managed_paths = {
            op.path.value
            for op in plan.ordered_operations
            if isinstance(op, (CreateFileOperation, ReplaceFileOperation))
            and op.path.value != MANIFEST_PATH.value
        }
        assert ".releaserc" in managed_paths

    def test_add_replaces_existing_managed_files(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)

        snapshot_files: list[ObservedFileEntry] = []
        for file in managed_old:
            snapshot_files.append(
                ObservedFileEntry(
                    path=file.path,
                    state=file_state_identity(
                        file.content, text=file.kind == "text", mode=file.mode
                    ),
                    content=file.content,
                )
            )
        snapshot = TargetSnapshot(
            files=tuple(
                sorted(snapshot_files, key=lambda e: e.path.value.encode("utf-8"))
            ),
            directories=(),
        )

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        replace_ops = [
            op for op in plan.ordered_operations if isinstance(op, ReplaceFileOperation)
        ]
        assert len(replace_ops) > 0
        replace_paths = {op.path.value for op in replace_ops}
        assert "pyproject.toml" in replace_paths

    def test_old_render_mismatch_fails(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        wrong_inventory: ManagedInventory = ()

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=wrong_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION

    def test_add_preserves_existing_additions(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)
        existing_additions = ManifestAdditions(
            requested=("existing-cap",),
            settings=MappingProxyType({"existing-cap": {"key": "value"}}),
        )

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=existing_additions,
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)

    def test_conflicting_settings_rejected(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(())
        existing_inventory = derive_managed_inventory(managed_old)
        existing_additions = ManifestAdditions(
            requested=("existing-cap",),
            settings=MappingProxyType({"existing-cap": {"key": "old_value"}}),
        )

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=existing_additions,
            new_addition_ids=("existing-cap",),
            new_settings=MappingProxyType({"existing-cap": {"key": "new_value"}}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.INVALID_MANIFEST
        assert "settings_conflict" in result.error.subject

    def test_add_updates_manifest_additions(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        plan = result.value
        manifest_op = plan.ordered_operations[-1]
        assert isinstance(manifest_op, (CreateFileOperation, ReplaceFileOperation))
        manifest_bytes = plan.blob_store.get(manifest_op.planned_new.content_id)
        assert manifest_bytes is not None
        match decode_manifest(manifest_bytes):
            case Ok(decoded):
                assert "semantic-release" in decoded.additions.requested
            case Err(error):
                raise AssertionError(f"manifest decode failed: {error}")

    def test_gate_specification_for_add(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(())
        existing_inventory = derive_managed_inventory(managed_old)

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=(),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
        gate = result.value.gate_specification
        assert gate.operation == "add"
        assert gate.artifact_verification is True
        assert gate.template_contract is True
        assert gate.readiness_rule == ReadinessRule.NO_WORSE_BLOCKING
        assert gate.expected_placeholder == ()

    def test_snapshot_validation_rejects_duplicate_paths(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(())
        existing_inventory = derive_managed_inventory(managed_old)

        dup_file = ObservedFileEntry(
            path=RepoPath("README.md"),
            state=file_state_identity(b"content", text=True, mode=PosixMode.FILE),
            content=b"content",
        )
        snapshot = TargetSnapshot(
            files=(dup_file, dup_file),
            directories=(),
        )

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=(),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=snapshot,
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.INVALID_TARGET

    def test_path_limit_exceeded(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)

        tiny_limits = ResourceLimits(
            max_file_bytes=1024 * 1024,
            max_unique_bytes=1024 * 1024 * 10,
            max_paths=1,
            max_operations=1000,
        )

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=tiny_limits,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.PLAN_LIMIT_EXCEEDED

    def test_oracle_rejects_path_mismatch(self) -> None:
        from scripts.bootstrap.manifest import ManagedInventoryEntry

        managed_old, _blobs_old = _render_for(())
        wrong_inventory = tuple(
            ManagedInventoryEntry(
                path=RepoPath("nonexistent.txt"),
                kind="text",
                mode=PosixMode.FILE,
                sha256="wrong",
            )
            for _ in derive_managed_inventory(managed_old)
        )
        result = verify_old_render_oracle(managed_old, wrong_inventory)
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION
        assert "entry_mismatch" in result.error.subject

    def test_new_capability_settings_recorded(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, _blobs_new = _render_for(())
        existing_inventory = derive_managed_inventory(managed_old)

        result = compile_add_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=_fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_addition_ids=("semantic-release",),
            new_settings=MappingProxyType({"semantic-release": {"channel": "main"}}),
            old_render=managed_old,
            new_managed=managed_new,
            existing_inventory=existing_inventory,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)
