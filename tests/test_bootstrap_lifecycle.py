"""In-process lifecycle-executor tests: restore and reconcile run inside the test process.

The CLI e2e suites exercise the executor through subprocesses, which pytest-cov
cannot see; these tests call ``_execute_lifecycle`` directly so the lifecycle
happy paths, receipt binding, and refusal branches count toward source coverage.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from scripts.bootstrap.cli import (
    ParsedCommand,
    _execute_lifecycle,  # pyright: ignore[reportPrivateUsage]  intentional lifecycle coverage
    _recorded_render,  # pyright: ignore[reportPrivateUsage]  intentional lifecycle coverage
    parse_argv,
)
from scripts.bootstrap.diagnostics import (
    ContractFailure,
    InvalidRequest,
    Succeeded,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    CandidateManifest,
    MaintenanceRecord,
    ManifestAdditions,
    ProfileSelection,
    ProvenanceRecord,
    decode_manifest,
)
from scripts.bootstrap.presentation import CommandResult
from scripts.bootstrap.result import Ok
from scripts.bootstrap.values import DEFAULT_LIMITS
from tests import test_source_bootstrap
from tests.bootstrap_fixtures import copier_source_baseline, fixture_answers, render_for

ROOT = Path(__file__).resolve().parent.parent


def _parsed(args: list[str]) -> ParsedCommand:
    match parse_argv(args):
        case Ok(parsed) if isinstance(parsed, ParsedCommand):
            return parsed
        case other:
            raise AssertionError(f"parse failed: {other}")


def _execute(args: list[str]) -> CommandResult:
    parsed = _parsed(args)
    return _execute_lifecycle(parsed, template_root=str(ROOT), limits=DEFAULT_LIMITS)


def _activate(raw: Path) -> tuple[Path, Path]:
    return test_source_bootstrap._activate_source(raw)


def test_recorded_render_preserves_profile_capability_closure() -> None:
    answers = replace(
        fixture_answers(),
        profile=ProfileSelection(id="custom", requested=("nix",)),
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
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]
        document = project / "docs/capabilities.md"
        compiled_document = test_source_bootstrap.render_for(())["docs/capabilities.md"]
        _ = managed.write_bytes(b"drifted in-process\n")
        _ = document.write_bytes(b"drifted documentation\n")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert managed.read_bytes() == compiled
        assert document.read_bytes() == compiled_document


def test_plan_restore_writes_receipt_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
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
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
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
        assert receipt.read_text(encoding="utf-8") == "occupied"


def test_add_installs_an_append_only_capability_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        parent = Path(raw)
        project, _record = _activate(parent)
        additions = parent / "additions.json"
        _ = additions.write_text(
            '{"schema_version": 1, "add_capabilities": ["semantic-release"]}',
            encoding="utf-8",
        )
        result = _execute(
            [
                "add",
                "--target",
                str(project),
                "--input",
                str(additions),
            ]
        )
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert (project / ".releaserc").is_file()
        decoded = decode_manifest((project / ".rygor/project.json").read_bytes())
        assert isinstance(decoded, Ok)
        assert decoded.value.additions.requested == ("semantic-release",)


def test_add_persists_complete_normalized_dependency_settings_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        parent = Path(raw)
        project, _record = _activate(parent)
        additions = parent / "additions.json"
        _ = additions.write_text(
            (
                '{"schema_version": 1, "add_capabilities": ["cachix-publish"], '
                '"capability_settings": {"cachix-publish": {"cache_name": " example "}}}'
            ),
            encoding="utf-8",
        )
        result = _execute(["add", "--target", str(project), "--input", str(additions)])
        assert isinstance(result.outcome, Succeeded), result.outcome
        decoded = decode_manifest((project / ".rygor/project.json").read_bytes())
        assert isinstance(decoded, Ok)
        assert decoded.value.additions.settings == {
            "cachix-publish": {"cache_name": "example"},
            "nix": {},
        }


def test_plan_add_writes_an_append_only_receipt_without_mutating_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        parent = Path(raw)
        project, _record = _activate(parent)
        additions = parent / "additions.json"
        _ = additions.write_text(
            '{"schema_version": 1, "add_capabilities": ["semantic-release"]}',
            encoding="utf-8",
        )
        receipt = parent / "add-plan.json"
        result = _execute(
            [
                "plan",
                "add",
                "--target",
                str(project),
                "--input",
                str(additions),
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert receipt.is_file()
        assert not (project / ".releaserc").exists()
        decoded = decode_manifest((project / ".rygor/project.json").read_bytes())
        assert isinstance(decoded, Ok)
        assert decoded.value.additions.requested == ()


def test_restore_no_drift_is_a_no_op_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, Succeeded), result.outcome
        assert result.state_document == {"kind": "no_changes"}


def test_restore_unknown_requested_path_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        result = _execute(
            ["restore", "--target", str(project), "--path", "docs/not-managed.md"]
        )
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "not-managed.md" in str(result.outcome)


def test_unusual_filename_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        odd = project / "bad\\name"
        _ = odd.write_text("weird\n", encoding="utf-8")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "OBSERVATION_LIMIT_EXCEEDED" in str(result.outcome)


def test_hardlinked_file_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        source = project / "README.md"
        os.link(source, project / "README-link.md")
        result = _execute(["restore", "--target", str(project)])
        assert isinstance(result.outcome, ContractFailure), result.outcome
        assert "HARDLINK_ENCOUNTERED" in str(result.outcome)


def test_corrupt_ownership_is_refused_in_process() -> None:
    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        ownership = project / ".rygor/source-ownership.json"
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

    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
        project, _record = _activate(Path(raw))
        as_copier_project(project)
        # An unselected capability artifact can remain in a Copier source tree;
        # both lifecycle inventories must exclude it as declaratively managed.
        unselected_artifact = project / ".releaserc"
        _ = unselected_artifact.write_bytes((ROOT / ".releaserc").read_bytes())
        adopter_validation = project / ".github/workflows/project-validation.yml"
        _ = adopter_validation.write_text(
            adopter_validation.read_text(encoding="utf-8")
            + "\n# adopter customization\n",
            encoding="utf-8",
        )
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
        assert unselected_artifact.read_bytes() == (ROOT / ".releaserc").read_bytes()
        assert "# adopter customization" in adopter_validation.read_text(
            encoding="utf-8"
        )

        # The matching preview binds execution and repairs the managed drift.
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
        assert unselected_artifact.read_bytes() == (ROOT / ".releaserc").read_bytes()


def test_reconcile_refuses_stale_receipt_in_process() -> None:
    from tests import test_bootstrap_reconcile_cli

    as_copier_project = cast(
        Callable[[Path], None],
        test_bootstrap_reconcile_cli.__dict__["_as_copier_project"],
    )

    with tempfile.TemporaryDirectory(prefix="rygor-lifecycle.") as raw:
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
                "--overwrite-drift",
                "--out",
                str(receipt),
            ]
        )
        assert isinstance(planned.outcome, Succeeded), planned.outcome

        # A different drift changes the plan, so the preview receipt no longer
        # binds.
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

        # The matching preview binds execution and repairs the managed drift.
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
