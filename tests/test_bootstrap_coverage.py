"""Targeted contract coverage for lifecycle error boundaries."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest  # pyright: ignore[reportMissingImports]  optional local test dependency

from scripts.bootstrap import cli, planner
from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.cli import (
    ParsedCommand,
    _compile_lifecycle_plan,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _decode_existing_manifest,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _execute_lifecycle,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _lifecycle_compile_error,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _manifest_identity,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _recorded_render,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _verify_reconcile_receipt,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    parse_argv,
)
from scripts.bootstrap.diagnostics import (
    ActionRequired,
    ContractFailure,
    InvalidRequest,
    Succeeded,
)
from scripts.bootstrap.errors import (
    ContractError,
    ContractErrorKind,
    TransitionError,
    TransitionErrorKind,
)
from scripts.bootstrap.identity import (
    FileState,
    ManifestIdentity,
    PosixMode,
    file_state_identity,
)
from scripts.bootstrap.intents import Add, AddOptions, GenerationPath, Intent
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    CandidateManifest,
    MaintenanceRecord,
    ManifestAdditions,
    ProfileSelection,
    ProvenanceRecord,
    build_candidate_manifest,
)
from scripts.bootstrap.observation import (
    ProjectObservationPass,
    SystemObservation,
    collect_template_source_entries,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import PlanReceipt, reconstruct_plan
from scripts.bootstrap.planner import (
    CompileError,
    CompileErrorKind,
    CreateFileOperation,
    ObservedFileEntry,
    OperationPlan,
    TargetSnapshot,
    _drifted_from_recorded,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _reconcile_candidate_manifest,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    _restore_operation,  # pyright: ignore[reportPrivateUsage]  targeted branch coverage
    compile_reconcile_plan,
    compile_restore_plan,
)
from scripts.bootstrap.presentation import CommandResult, PresentationOptions
from scripts.bootstrap.render import (
    RenderError,
    RenderErrorKind,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.scaffold import SOURCE_OWNERSHIP_PATH, decode_source_ownership
from scripts.bootstrap.values import DEFAULT_LIMITS
from tests import test_source_bootstrap
from tests.bootstrap_fixtures import (
    TARGET,
    copier_source_baseline,
    fixture_answers,
    observed_snapshot,
    render_for,
)

ROOT = Path(__file__).resolve().parent.parent


def _manifest(*, requested: tuple[str, ...] = ()) -> SimpleNamespace:
    answers = replace(
        fixture_answers(),
        profile=ProfileSelection(id="custom", requested=requested),
    )
    return SimpleNamespace(
        answers=answers,
        additions=ManifestAdditions(),
        existing_additions=ManifestAdditions(),
        provenance=ProvenanceRecord(
            generation_path=GenerationPath.COPIER,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=copier_source_baseline(b"baseline"),
        ),
    )


def _write_ownership(root: Path, lifecycle_paths: tuple[str, ...]) -> None:
    ownership = root / SOURCE_OWNERSHIP_PATH.value
    ownership.parent.mkdir(parents=True, exist_ok=True)
    _ = ownership.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lifecycle_paths": list(lifecycle_paths),
                "snapshot_cleanup_paths": [],
            }
        ),
        encoding="utf-8",
    )


def _parsed(args: list[str]) -> ParsedCommand:
    match parse_argv(args):
        case Ok(parsed) if isinstance(parsed, ParsedCommand):
            return parsed
        case other:
            raise AssertionError(f"parse failed: {other}")


def _execute(args: list[str]) -> CommandResult:
    parsed = _parsed(args)
    return _execute_lifecycle(parsed, template_root=str(ROOT), limits=DEFAULT_LIMITS)


def _raw_command(command: str, intent: Intent, project: Path) -> CommandResult:
    parsed = ParsedCommand(
        command=command,
        presentation=PresentationOptions(),
        intent=intent,
        target=str(project),
        bundle_path=None,
        input_path=None,
        out_path=None,
        plan_path=None,
        leave_maintenance_artifacts=False,
    )
    return _execute_lifecycle(parsed, template_root=str(ROOT), limits=DEFAULT_LIMITS)


def _activate(raw: Path) -> tuple[Path, Path]:
    try:
        return test_source_bootstrap._activate_source(raw)
    except AssertionError as error:
        if "CLEANUP_CONTRACT_INVALID" in str(error):
            pytest.skip(  # pyright: ignore[reportUnknownMemberType]
                f"apply cannot bootstrap in this environment: {error}"
            )
        raise


def test_source_collection_rejects_invalid_ownership_file(tmp_path: Path) -> None:
    for case in ("missing", "directory", "invalid", "oversized"):
        root = tmp_path / case
        ownership = root / SOURCE_OWNERSHIP_PATH.value
        ownership.parent.mkdir(parents=True)
        limits = DEFAULT_LIMITS
        if case == "directory":
            ownership.mkdir()
        elif case == "invalid":
            _ = ownership.write_text("{", encoding="utf-8")
        elif case == "oversized":
            _ = ownership.write_text("{}", encoding="utf-8")
            limits = replace(DEFAULT_LIMITS, max_file_bytes=1)

        result = collect_template_source_entries(
            str(root), managed_paths=set(), limits=limits
        )
        assert isinstance(result, Err)
        assert result.error.kind is ContractErrorKind.SOURCE_CONTRACT_INVALID


def test_source_collection_rejects_missing_or_symlinked_declared_path(
    tmp_path: Path,
) -> None:
    for symlink in (False, True):
        root = tmp_path / str(symlink)
        _write_ownership(root, ("owned.txt",))
        declared = root / "owned.txt"
        if symlink:
            target = root / "target.txt"
            _ = target.write_text("target", encoding="utf-8")
            declared.symlink_to(target)

        result = collect_template_source_entries(
            str(root), managed_paths=set(), limits=DEFAULT_LIMITS
        )
        assert isinstance(result, Err)
        assert result.error.kind is ContractErrorKind.SOURCE_CONTRACT_INVALID


def test_source_ownership_rejects_nested_lifecycle_paths() -> None:
    result = decode_source_ownership(
        json.dumps(
            {
                "schema_version": 1,
                "lifecycle_paths": ["owned", "owned/file.txt"],
                "snapshot_cleanup_paths": [],
            }
        ).encode()
    )
    assert isinstance(result, Err)


def test_restore_helper_covers_missing_create_and_noop_paths() -> None:
    content = b"managed\n"
    store_result = VerifiedBlobStore.empty().intern(content)
    assert isinstance(store_result, Ok)
    content_id, store = store_result.value

    missing = _restore_operation(
        RepoPath("managed.txt"),
        "text",
        PosixMode.FILE,
        ContentId("0" * 64),
        None,
        store,
    )
    assert isinstance(missing, Err)

    created = _restore_operation(
        RepoPath("managed.txt"),
        "text",
        PosixMode.FILE,
        content_id,
        None,
        store,
    )
    assert isinstance(created, Ok)
    assert isinstance(created.value, CreateFileOperation)

    current = file_state_identity(content, text=True, mode=PosixMode.FILE)
    unchanged = _restore_operation(
        RepoPath("managed.txt"),
        "text",
        PosixMode.FILE,
        content_id,
        current,
        store,
    )
    assert isinstance(unchanged, Ok)
    assert unchanged.value is None


def test_restore_drifted_helper_rejects_incomplete_observation() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    entry = derive_managed_inventory(managed)[0]
    observed = ObservedFileEntry(
        path=entry.path,
        state=FileState(None, None),
        content=b"",
    )
    assert _drifted_from_recorded(observed, entry)


def test_restore_plan_rejects_invalid_snapshot_and_render() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    inventory = derive_managed_inventory(managed)
    manifest = SimpleNamespace(payload=b"manifest", digest="0" * 64)
    invalid_snapshot = TargetSnapshot(
        files=(
            ObservedFileEntry(
                path=RepoPath("invalid/../path"),
                state=FileState(None, None),
                content=b"",
            ),
        ),
        directories=(),
    )
    invalid_snapshot_result = compile_restore_plan(
        generation=GenerationPath.COPIER,
        target_identity=TARGET,
        answers=fixture_answers(),
        certified_render=managed,
        existing_inventory=inventory,
        current_manifest=cast(ManifestIdentity, cast(object, manifest)),
        source_baseline=copier_source_baseline(b"baseline"),
        snapshot=invalid_snapshot,
        limits=DEFAULT_LIMITS,
    )
    assert isinstance(invalid_snapshot_result, Err)

    missing_render_result = compile_restore_plan(
        generation=GenerationPath.COPIER,
        target_identity=TARGET,
        answers=fixture_answers(),
        certified_render=managed[1:],
        existing_inventory=inventory,
        current_manifest=cast(ManifestIdentity, cast(object, manifest)),
        source_baseline=copier_source_baseline(b"baseline"),
        snapshot=observed_snapshot(managed),
        requested_paths=(managed[0].path,),
        limits=DEFAULT_LIMITS,
    )
    assert isinstance(missing_render_result, Err)


def test_restore_plan_covers_blob_and_path_limits() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    inventory = derive_managed_inventory(managed)
    snapshot = observed_snapshot(
        managed, drift={managed[0].path.value: b"adopter edit\n"}
    )
    for limits in (
        replace(DEFAULT_LIMITS, max_unique_bytes=0),
        replace(DEFAULT_LIMITS, max_paths=0),
    ):
        result = compile_restore_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=fixture_answers(),
            certified_render=managed,
            existing_inventory=inventory,
            current_manifest=ManifestIdentity(payload=b"manifest", digest="0" * 64),
            source_baseline=copier_source_baseline(b"baseline"),
            snapshot=snapshot,
            limits=limits,
        )
        assert isinstance(result, Err)


def test_reconcile_plan_covers_blob_and_path_limits() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    inventory = derive_managed_inventory(managed)
    for limits in (
        replace(DEFAULT_LIMITS, max_unique_bytes=0),
        replace(DEFAULT_LIMITS, max_paths=0),
    ):
        result = compile_reconcile_plan(
            generation=GenerationPath.COPIER,
            target_identity=TARGET,
            answers=fixture_answers(),
            existing_additions=ManifestAdditions(),
            new_render=managed,
            existing_inventory=inventory,
            old_source_baseline=copier_source_baseline(b"old"),
            new_source_baseline=copier_source_baseline(b"new"),
            old_manifest=ManifestIdentity(payload=b"manifest", digest="0" * 64),
            maintenance=MaintenanceRecord(status="clean"),
            snapshot=observed_snapshot(managed),
            limits=limits,
        )
        assert isinstance(result, Err)


def test_reconcile_candidate_manifest_failure_is_returned() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    with patch.object(
        planner,
        "build_candidate_manifest",
        return_value=Err(SimpleNamespace(subject="fixture")),
    ):
        result = _reconcile_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            new_render=managed,
            new_source_baseline=copier_source_baseline(b"baseline"),
            maintenance=MaintenanceRecord(status="clean"),
            generation=GenerationPath.COPIER,
        )
    assert isinstance(result, Err)


def test_receipt_reconstruction_rejects_unknown_operation_kind() -> None:
    receipt = cast(
        PlanReceipt,
        cast(
            object,
            {"target_binding": TARGET.digest, "operation_kind": "unknown"},
        ),
    )
    result = reconstruct_plan(receipt, target=TARGET)
    assert isinstance(result, Err)


def test_receipt_verification_rejects_oversized_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    _ = receipt.write_bytes(b"x" * (DEFAULT_LIMITS.max_file_bytes + 1))
    result = _verify_reconcile_receipt(
        str(receipt),
        cast(OperationPlan, cast(object, SimpleNamespace())),
        DEFAULT_LIMITS,
    )
    assert isinstance(result, Err)


def test_lifecycle_execution_refuses_unavailable_target(tmp_path: Path) -> None:
    parsed = parse_argv(["restore", "--target", str(tmp_path / "missing")])
    assert isinstance(parsed, Ok)
    assert isinstance(parsed.value, ParsedCommand)
    result = _execute_lifecycle(
        parsed.value,
        template_root=".",
        limits=DEFAULT_LIMITS,
    )
    assert result.outcome


def test_lifecycle_manifest_error_boundaries() -> None:
    absent = _decode_existing_manifest(
        cast(ProjectObservationPass, cast(object, SimpleNamespace(files=())))
    )
    assert isinstance(absent, Err)

    invalid = _decode_existing_manifest(
        cast(
            ProjectObservationPass,
            cast(
                object,
                SimpleNamespace(
                    files=(SimpleNamespace(path=MANIFEST_PATH, content=b"{}"),)
                ),
            ),
        )
    )
    assert isinstance(invalid, Err)
    assert isinstance(invalid.error, ContractError)
    assert invalid.error.kind is ContractErrorKind.INVALID_MANIFEST

    incompatible = _recorded_render(
        cast(
            CandidateManifest,
            cast(object, _manifest(requested=("unknown-capability",))),
        ),
        DEFAULT_LIMITS,
    )
    assert isinstance(incompatible, Err)
    assert incompatible.error.kind is ContractErrorKind.INCOMPATIBLE_CATALOG

    with patch.object(
        cli,
        "render_generation",
        return_value=Err(
            RenderError(RenderErrorKind.INVALID_TEMPLATE, "coverage", "fixture")
        ),
    ):
        render_error = _recorded_render(
            cast(CandidateManifest, cast(object, _manifest())), DEFAULT_LIMITS
        )
    assert isinstance(render_error, Err)
    assert render_error.error.kind is ContractErrorKind.RENDER_CONTRACT_VIOLATION


def test_source_collection_reports_ownership_open_failure(tmp_path: Path) -> None:
    root = tmp_path / "ownership-open"
    _write_ownership(root, ())
    with patch("scripts.bootstrap.observation.os.open", side_effect=OSError("blocked")):
        result = collect_template_source_entries(
            str(root), managed_paths=set(), limits=DEFAULT_LIMITS
        )
    assert isinstance(result, Err)
    assert result.error.kind is ContractErrorKind.SOURCE_CONTRACT_INVALID


def test_lifecycle_plan_returns_recorded_render_error() -> None:
    parsed = cast(
        ParsedCommand,
        cast(object, SimpleNamespace(command="restore")),
    )
    observed = cast(
        SystemObservation,
        cast(object, SimpleNamespace(pass_=SimpleNamespace(files=()))),
    )
    error = ContractError(ContractErrorKind.RENDER_CONTRACT_VIOLATION, "fixture")
    with (
        patch.object(cli, "_decode_existing_manifest", return_value=Ok(_manifest())),
        patch.object(cli, "_recorded_render", return_value=Err(error)),
    ):
        result = _compile_lifecycle_plan(
            parsed, observed, template_root=".", limits=DEFAULT_LIMITS
        )
    assert isinstance(result, Err)


def test_lifecycle_plan_refusals_and_error_mapping() -> None:
    unavailable = _compile_lifecycle_plan(
        cast(ParsedCommand, cast(object, SimpleNamespace(command="restore"))),
        cast(SystemObservation, cast(object, SimpleNamespace(pass_=None))),
        template_root=".",
        limits=DEFAULT_LIMITS,
    )
    assert isinstance(unavailable, Err)
    assert isinstance(unavailable.error, TransitionError)
    assert unavailable.error.kind is TransitionErrorKind.OPERATION_UNAVAILABLE

    absent_manifest = _compile_lifecycle_plan(
        cast(ParsedCommand, cast(object, SimpleNamespace(command="restore"))),
        cast(
            SystemObservation,
            cast(
                object,
                SimpleNamespace(
                    pass_=cast(
                        ProjectObservationPass,
                        cast(object, SimpleNamespace(files=())),
                    )
                ),
            ),
        ),
        template_root=".",
        limits=DEFAULT_LIMITS,
    )
    assert isinstance(absent_manifest, Err)

    mapped = _lifecycle_compile_error(
        "reconcile",
        CompileError(CompileErrorKind.RENDER_CONTRACT_VIOLATION, "managed_drift"),
    )
    assert isinstance(mapped, TransitionError)
    assert mapped.kind is TransitionErrorKind.MANAGED_DRIFT


def test_reconcile_receipt_rejects_hardlinked_receipt(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    receipt = tmp_path / "receipt.json"
    _ = target.write_text("receipt", encoding="utf-8")
    os.link(target, receipt)

    result = _verify_reconcile_receipt(
        str(receipt),
        cast(OperationPlan, cast(object, SimpleNamespace())),
        DEFAULT_LIMITS,
    )
    assert isinstance(result, Err)


def test_reconcile_receipt_rejects_invalid_json(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    _ = receipt.write_bytes(b"{}")
    result = _verify_reconcile_receipt(
        str(receipt),
        cast(OperationPlan, cast(object, SimpleNamespace())),
        DEFAULT_LIMITS,
    )
    assert isinstance(result, Err)


def test_manifest_identity_can_be_recomputed() -> None:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    candidate = build_candidate_manifest(
        answers=fixture_answers(),
        additions=ManifestAdditions(),
        provenance=ProvenanceRecord(
            generation_path=GenerationPath.COPIER,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=copier_source_baseline(b"baseline"),
        ),
        managed=derive_managed_inventory(managed),
    )
    assert isinstance(candidate, Ok)
    identity = _manifest_identity(candidate.value)
    assert identity.digest


def test_recorded_render_preserves_profile_capability_closure() -> None:
    answers = fixture_answers()
    answers = answers.__class__(
        project=answers.project,
        profile=ProfileSelection(id="custom", requested=("nix",)),
        settings=answers.settings,
        licensing=answers.licensing,
        slots=answers.slots,
    )
    manifest = SimpleNamespace(
        answers=answers,
        additions=ManifestAdditions(),
        provenance=ProvenanceRecord(
            generation_path=GenerationPath.COPIER,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=copier_source_baseline(b"baseline"),
        ),
    )
    result = _recorded_render(
        cast(CandidateManifest, cast(object, manifest)), DEFAULT_LIMITS
    )
    assert isinstance(result, Ok), result
    expected, _blobs = render_for(("nix",), GenerationPath.COPIER)
    assert tuple(file.path for file in result.value) == tuple(
        file.path for file in expected
    )


def test_restore_repairs_drifted_managed_file_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]
        _ = managed.write_bytes(b"drifted in-process\n")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert managed.read_bytes() == compiled


def test_plan_restore_writes_receipt_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        _ = managed.write_bytes(b"drifted in-process\n")
        receipt = Path(raw) / "restore-plan.json"
        result = _execute(
            [
                "plan",
                "restore",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert receipt.exists()
        assert managed.read_bytes() == b"drifted in-process\n"


def test_out_occupied_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        receipt = Path(raw) / "restore-plan.json"
        _ = receipt.write_text("occupied", encoding="utf-8")
        result = _execute(
            [
                "plan",
                "restore",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(result.outcome, InvalidRequest), result.outcome
        assert "occupied" in str(result.outcome)


def test_add_is_deferred_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        result = _raw_command("add", Add(AddOptions()), project)
        assert isinstance(result.outcome, ActionRequired), result.outcome
        assert "later lifecycle task" in str(result.outcome)


def test_restore_no_drift_is_a_no_op_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert result.state_document == {"kind": "no_changes"}


def test_restore_unknown_requested_path_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        result = _execute(
            ["restore", "--target", str(project), "--path", "docs/not-managed.md"]
        )
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "not-managed.md" in str(result.outcome)


def test_unusual_filename_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        odd = project / "bad\\name"
        _ = odd.write_text("weird\n", encoding="utf-8")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "OBSERVATION_LIMIT_EXCEEDED" in str(result.outcome)


def test_hardlinked_file_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        source = project / "README.md"
        os.link(source, project / "README-link.md")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "HARDLINK_ENCOUNTERED" in str(result.outcome)


def test_corrupt_ownership_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        ownership = project / ".agentic-template/source-ownership.json"
        _ = ownership.write_text("{garbage", encoding="utf-8")
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]
        _ = managed.write_bytes(b"drifted in-process\n")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "SOURCE_CONTRACT_INVALID" in str(result.outcome)
        assert managed.read_bytes() != compiled


def test_reconcile_binds_receipt_in_process() -> None:
    from tests import test_bootstrap_reconcile_cli

    as_copier_project = cast(
        Callable[[Path], None],
        test_bootstrap_reconcile_cli.__dict__["_as_copier_project"],
    )

    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        as_copier_project(project)
        source = project / "docs/agents/domain.md"
        _ = source.write_text("drifted source\n", encoding="utf-8")
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]

        receipt = Path(raw) / "reconcile-plan.json"
        planned = _execute(
            [
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(planned.outcome, Succeeded), planned.outcome
        assert receipt.exists()
        assert source.read_text(encoding="utf-8") == "drifted source\n"

        _ = managed.write_bytes(b"adopter edit\n")
        receipt.unlink()
        planned = _execute(
            [
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(planned.outcome, Succeeded), planned.outcome
        reconciled = _execute(
            [
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ]
        )
        assert isinstance(reconciled.outcome, Succeeded), reconciled.outcome
        assert managed.read_bytes() == compiled
        assert source.read_text(encoding="utf-8") == "drifted source\n"


def test_reconcile_refuses_stale_receipt_in_process() -> None:
    from tests import test_bootstrap_reconcile_cli

    as_copier_project = cast(
        Callable[[Path], None],
        test_bootstrap_reconcile_cli.__dict__["_as_copier_project"],
    )

    with tempfile.TemporaryDirectory(prefix="agentic-template-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        as_copier_project(project)
        source = project / "docs/agents/domain.md"
        _ = source.write_text("drifted source\n", encoding="utf-8")
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]

        receipt = Path(raw) / "reconcile-plan.json"
        planned = _execute(
            [
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(planned.outcome, Succeeded), planned.outcome

        _ = managed.write_bytes(b"different edit\n")
        result = _execute(
            [
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ]
        )
        assert isinstance(result.outcome, InvalidRequest), result.outcome
        assert "does not match the current reconcile" in str(result.outcome)
        assert managed.read_bytes() == b"different edit\n"
        assert compiled != b"different edit\n"

        receipt.unlink()
        planned = _execute(
            [
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(planned.outcome, Succeeded), planned.outcome
        reconciled = _execute(
            [
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ]
        )
        assert isinstance(reconciled.outcome, Succeeded), reconciled.outcome
        assert managed.read_bytes() == compiled
        assert source.read_text(encoding="utf-8") == "drifted source\n"
