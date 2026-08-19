"""Tests for the add transition, old-render oracle, and expanded selection compilation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.contributions import render_generation
from scripts.bootstrap.identity import (
    PosixMode,
    file_state_identity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    LicensingRecord,
    MaintenanceRecord,
    ManagedInventory,
    ManifestAdditions,
    ManifestAnswers,
    ProfileSelection,
    ProjectFacts,
    SlotContent,
    decode_manifest,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    ADD_OPERATION_KIND,
    SLOT_PLACEHOLDER_RULES,
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
    LicensingInfo,
    MaintenanceInfo,
    ManagedFile,
    ProfileInfo,
    ProjectInfo,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.source_baseline import (
    GitHubSourceBaseline,
    LifecycleSourceEntry,
)
from scripts.bootstrap.values import DEFAULT_LIMITS

TARGET = target_identity(b"/work/example", device=1, inode=2)
PROJECT = ProjectInfo(name="example", default_branch="main")
LICENSING = LicensingInfo(mode="retain-apache-2.0", content_sha256=None)
PROFILE = ProfileInfo(id="portable", frozen=())
MAINTENANCE_INFO = MaintenanceInfo(status="clean", retained_paths=())
SLOTS: Mapping[str, SlotContent] = MappingProxyType({})
SOURCE_ENTRIES = (
    LifecycleSourceEntry(
        path=RepoPath("scripts/bootstrap/__init__.py"),
        kind="file",
        mode=PosixMode.FILE,
        sha256=sha256_hex(b"present\n"),
    ),
    LifecycleSourceEntry(
        path=RepoPath("scripts/bootstrap/render.py"),
        kind="file",
        mode=PosixMode.FILE,
        sha256=sha256_hex(b"present\n"),
    ),
)

SLOT_CONTENTS: dict[str, bytes] = {
    "readme": b"# Example\n\nReal project description.\n",
    "prd": b"<!-- agentic-template:placeholder:prd -->\n# Product\n",
    "security_policy": b"<!-- agentic-template:placeholder:security -->\n",
    "contributing": b"<!-- agentic-template:placeholder:contributing -->\n",
    "validation_hook": (
        b"#!/usr/bin/env python3\nagentic-template:unconfigured:validate-project\n"
    ),
}
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
    blobs = VerifiedBlobStore.empty()
    managed = render_generation(
        generation_path=GenerationPath.GITHUB,
        core=core_definition(),
        definitions=capability_definitions(),
        effective=effective,
        settings=settings or MappingProxyType({}),
        project=PROJECT,
        licensing=LICENSING,
        profile=PROFILE,
        maintenance=MAINTENANCE_INFO,
        slots=SLOTS,
        blobs=blobs,
    )
    match managed:
        case Ok(rendered):
            return rendered, blobs
        case Err(error):
            raise AssertionError(f"render failed: {error}")


def _fixture_answers() -> ManifestAnswers:
    slots: dict[str, SlotContent] = {}
    for rule in SLOT_PLACEHOLDER_RULES:
        if rule.slot == "prd":
            slots[rule.slot] = SlotContent(mode="scaffold", content_sha256=None)
        else:
            slots[rule.slot] = SlotContent(
                mode="file", content_sha256=sha256_hex(SLOT_CONTENTS[rule.slot])
            )
    return ManifestAnswers(
        project=ProjectFacts(name="example", default_branch="main"),
        profile=ProfileSelection(id="portable", requested=()),
        settings=MappingProxyType({}),
        licensing=LicensingRecord(mode="retain-apache-2.0", content_sha256=None),
        slots=MappingProxyType(slots),
    )


def _source_baseline() -> GitHubSourceBaseline:
    return GitHubSourceBaseline(
        kind="github",
        fingerprint=sha256_hex(b"source-baseline"),
        entries=SOURCE_ENTRIES,
        snapshot_commit="0" * 40,
    )


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
        managed_new, blobs_new = _render_for(())
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
            blobs=blobs_new,
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
        managed_new, blobs_new = _render_for(("semantic-release",))
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
            blobs=blobs_new,
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
        managed_new, blobs_new = _render_for(("semantic-release",))
        existing_inventory = derive_managed_inventory(managed_old)

        snapshot_files = []
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
            blobs=blobs_new,
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
        managed_new, blobs_new = _render_for(("semantic-release",))
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
            blobs=blobs_new,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Err)
        assert result.error.kind == CompileErrorKind.RENDER_CONTRACT_VIOLATION

    def test_add_preserves_existing_additions(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, blobs_new = _render_for(("semantic-release",))
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
            blobs=blobs_new,
            source_baseline=_source_baseline(),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=TargetSnapshot(files=(), directories=()),
            limits=DEFAULT_LIMITS,
        )
        assert isinstance(result, Ok)

    def test_conflicting_settings_rejected(self) -> None:
        managed_old, _blobs_old = _render_for(())
        managed_new, blobs_new = _render_for(())
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
            blobs=blobs_new,
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
        managed_new, blobs_new = _render_for(("semantic-release",))
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
            blobs=blobs_new,
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
        managed_new, blobs_new = _render_for(())
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
            blobs=blobs_new,
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
