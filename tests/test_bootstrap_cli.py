"""CLI adapters, scaffold classification, and end-to-end command families.

Covers T12 validation: golden command-family exit mappings, text/JSON parity,
status/planning/recovery never running the hook, refusal/rollback/recovery hook
counts, all-scaffold installs exiting nonzero while remaining installed,
cleanup marker collision and leave override, phase-specific recovery, and
post-lock revalidation.
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast, get_type_hints
from unittest.mock import patch

import pytest

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.cli import (
    ParsedCommand,
    _decode_existing_manifest,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    _init_failure,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _manifest_identity,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    _project_changes,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _recorded_render,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    execute_command,
    main,
    parse_argv,
)
from scripts.bootstrap.diagnostics import RecoveryFailure
from scripts.bootstrap.errors import (
    CommandError,
    ErrnoClass,
    TransactionError,
    TransactionPrimitive,
)
from scripts.bootstrap.identity import PosixMode, TargetIdentity
from scripts.bootstrap.journal import (
    JournalEnvelope,
    JournalTarget,
    PreparationIdentity,
    PreparationRole,
    PreparationSpec,
    encode_journal,
    new_transaction_id,
)
from scripts.bootstrap.manifest import CandidateManifest
from scripts.bootstrap.plan_digest import PlanReceipt, reconstruct_plan
from scripts.bootstrap.planner import CreateFileOperation, ReplaceFileOperation
from scripts.bootstrap.presentation import (
    CommandResult,
    render_json,
    render_text,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.transaction import derive_preparation_specs, derive_preparations
from scripts.bootstrap.values import JournalPhase
from tests.factory import (
    REPO_ROOT,
    SnapshotConfig,
    SnapshotProject,
    build_snapshot_project,
    pristine_snapshot,
    seed_repo,
    write_answer_bundle,
)
from tests.fixtures import PRD, README, SUPPLIED_CONTRIBUTING, SUPPLIED_SECURITY

ROOT = Path(__file__).resolve().parent.parent


def test_lifecycle_manifest_helpers_preserve_candidate_type() -> None:
    decode_annotations = get_type_hints(_decode_existing_manifest)
    recorded_annotations = get_type_hints(_recorded_render)
    identity_annotations = get_type_hints(_manifest_identity)

    assert decode_annotations["return"] == Result[CandidateManifest, CommandError]
    assert recorded_annotations["manifest"] is CandidateManifest
    assert identity_annotations["manifest"] is CandidateManifest


def _parse(argv: list[str]) -> ParsedCommand:
    match parse_argv(argv):
        case Ok(parsed):
            assert not isinstance(parsed, str)
            return parsed
        case Err(error):
            raise AssertionError(f"parse failed: {error}")


def _exit_code(result: CommandResult) -> int:
    from scripts.bootstrap.presentation import (
        _family_exit_code,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    )

    return _family_exit_code(result.command, result.outcome)


def _target_identity(root: Path) -> TargetIdentity:
    from scripts.bootstrap.identity import target_identity

    info = os.stat(root)
    return target_identity(
        os.fsencode(str(root)), device=info.st_dev, inode=info.st_ino
    )


def _build_cli_project(tmp_path: Path) -> SnapshotProject:
    """Build a synthetic snapshot project without a bundle."""
    return build_snapshot_project(
        tmp_path,
        SnapshotConfig(template="synthetic"),
        pristine=pristine_snapshot(),
    )


def _build_cli_fixture(tmp_path: Path) -> tuple[SnapshotProject, Path]:
    """Build a synthetic snapshot project and its all-scaffold bundle."""
    project = _build_cli_project(tmp_path)
    bundle = write_answer_bundle(tmp_path, supplied=False, record=project.hook_runs)
    return project, bundle


def _run_cli(argv: list[str], *, template_root: str) -> CommandResult:
    return execute_command(_parse(argv), template_root=template_root)


# --- CliFamilyTests ---------------------------------------------------------


def test_help_exits_zero() -> None:
    assert main(["--help"]) == 0
    assert main(["status", "--help"]) == 0


def test_status_invalid_journal_exits_two(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    _ = (state_root / "journal.json").write_text("not json", encoding="utf-8")
    result = _run_cli(
        ["status", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 2
    assert "state_root" in render_text(result)


def test_status_invalid_manifest_exits_two(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    manifest = project.root / ".rygor/project.json"
    manifest.parent.mkdir(exist_ok=True)
    _ = manifest.write_text("not json", encoding="utf-8")
    result = _run_cli(
        ["status", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 2
    assert "manifest" in render_text(result)


def test_status_reports_hook_not_evaluated(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    result = _run_cli(
        ["status", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert "hook: not evaluated" in render_text(result)


def test_explain_adds_decision_trace(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parsed = _parse(["--explain", "status", "--target", str(project.root)])
    result = execute_command(parsed, template_root=str(project.template_root))
    text = render_text(result, explain=True)
    assert "state: status" in text
    assert "decision: describe_status" in text


def test_color_always_emits_ansi(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parsed = _parse(["--color", "always", "status", "--target", str(project.root)])
    result = execute_command(parsed, template_root=str(project.template_root))
    assert "\x1b[" in render_text(result, color=True)
    assert "\x1b[" not in render_text(result, color=False)


def test_invalid_option_value_is_invalid_value() -> None:
    from scripts.bootstrap.errors import UsageError, UsageErrorKind

    for argv in (
        ["--format", "yaml", "status"],
        ["--color", "red", "status"],
    ):
        match parse_argv(argv):
            case Err(UsageError(kind=UsageErrorKind.INVALID_VALUE)):
                pass
            case _:
                raise AssertionError(
                    f"expected INVALID_VALUE for an invalid option value: {argv}"
                )


def test_usage_families_exit_two() -> None:
    cases = [
        ["frobnicate"],
        ["apply"],
        ["plan", "apply"],
        ["adopt"],
        ["plan", "adopt"],
        ["init", "--from", "x"],
        ["reconcile", "--overwrite-drift"],
        ["plan", "reconcile", "--overwrite-drift", "--out", "-"],
        ["restore", "--path", "README.md", "--path", "README.md"],
        ["--format", "json", "--quiet", "status"],
        ["--format", "json", "--color", "always", "status"],
    ]
    for argv in cases:
        match parse_argv(argv):
            case Ok(_):
                raise AssertionError(f"expected a usage error for {argv}")
            case Err(_):
                pass


def test_init_writes_reviewable_bundle(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    output = tmp_path / "out-bundle"
    result = _run_cli(
        [
            "init",
            "--from",
            str(bundle / "bootstrap.json"),
            "--output",
            str(output),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert (output / "bootstrap.json").is_file()
    occupied = _run_cli(
        [
            "init",
            "--from",
            str(bundle / "bootstrap.json"),
            "--output",
            str(output),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(occupied) == 1


def test_init_materializes_file_content(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parent = tmp_path / "second"
    parent.mkdir()
    record = parent / "hook-runs"
    bundle = write_answer_bundle(parent, supplied=True, record=record)
    output = tmp_path / "out-content"
    result = _run_cli(
        [
            "init",
            "--from",
            str(bundle / "bootstrap.json"),
            "--output",
            str(output),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    expected = {
        "README.md": README,
        "docs/prd.md": PRD,
        "SECURITY.md": SUPPLIED_SECURITY,
        "CONTRIBUTING.md": SUPPLIED_CONTRIBUTING,
        "scripts/validate-project": "#!/bin/sh\necho run >> "
        + str(record)
        + "\nexit 0\n",
    }
    for relative, content in expected.items():
        target = output / relative
        assert target.is_file(), relative
        assert target.read_text(encoding="utf-8") == content
    assert stat.S_IMODE((output / "docs").stat().st_mode) == 0o755


def test_init_failure_maps_oserror_to_closed_outcome() -> None:
    result = _init_failure(
        TransactionPrimitive.REMOVE_DIRECTORY,
        OSError(errno.ENOENT, "not a directory"),
        "subject",
    )
    assert result.command == "init"
    assert isinstance(result.outcome, RecoveryFailure)
    assert _exit_code(result) == 2


def test_init_maps_mkdir_failure_to_closed_outcome(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parent = tmp_path / "third"
    parent.mkdir()
    bundle = write_answer_bundle(parent, supplied=True, record=parent / "hook-runs")
    output = tmp_path / "out-mkdir"
    error = TransactionError.primitive_failed(
        TransactionPrimitive.CREATE_DIRECTORY, ErrnoClass.NO_SPACE, "stage"
    )
    with patch(
        "scripts.bootstrap.cli.mkdir_parents_0755",
        return_value=Err(error),
    ):
        result = _run_cli(
            [
                "init",
                "--from",
                str(bundle / "bootstrap.json"),
                "--output",
                str(output),
            ],
            template_root=str(project.template_root),
        )
    assert _exit_code(result) == 2


def test_init_maps_rmdir_failure_to_closed_outcome(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parent = tmp_path / "fourth"
    parent.mkdir()
    bundle = write_answer_bundle(parent, supplied=True, record=parent / "hook-runs")
    output = tmp_path / "out-rmdir"
    target = tmp_path / "out-rmdir-target"
    target.mkdir()
    output.symlink_to(target, target_is_directory=True)
    result = _run_cli(
        [
            "init",
            "--from",
            str(bundle / "bootstrap.json"),
            "--output",
            str(output),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 2


def test_init_maps_rename_failure_to_closed_outcome(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parent = tmp_path / "fifth"
    parent.mkdir()
    bundle = write_answer_bundle(parent, supplied=True, record=parent / "hook-runs")
    output = tmp_path / "out-rename"
    with patch(
        "scripts.bootstrap.cli.os.rename",
        side_effect=OSError(errno.EXDEV, "cross-device link"),
    ):
        result = _run_cli(
            [
                "init",
                "--from",
                str(bundle / "bootstrap.json"),
                "--output",
                str(output),
            ],
            template_root=str(project.template_root),
        )
    assert _exit_code(result) == 2


def test_init_rejects_reserved_markers(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    bundle = tmp_path / "marked"
    bundle.mkdir()
    (bundle / "content").mkdir()
    _ = (bundle / "content" / "readme.md").write_text(
        "<!-- rygor:placeholder:readme -->\n", encoding="utf-8"
    )
    _ = (bundle / "bootstrap.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": {"name": "example", "default_branch": "main"},
                "profile": {"id": "portable"},
                "content": {
                    "prd": {"mode": "scaffold"},
                    "readme": {"mode": "file", "path": "content/readme.md"},
                    "validation_hook": {"mode": "scaffold"},
                    "security_policy": {"mode": "scaffold"},
                    "contributing": {"mode": "scaffold"},
                },
                "licensing": {"mode": "retain-apache-2.0"},
                "capability_settings": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    result = _run_cli(
        [
            "init",
            "--from",
            str(bundle / "bootstrap.json"),
            "--output",
            str(tmp_path / "out"),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 2


def test_status_describes_scaffold_and_never_exits_one(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    result = _run_cli(
        ["status", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    text = render_text(result)
    assert "scaffold" in text
    assert "github" in text
    assert project.run_count() == 0


def test_status_unsupported_target_describes_and_exits_zero(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    result = _run_cli(
        ["status", "--target", str(plain)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert "unsupported" in render_text(result)


def test_plan_apply_produces_receipt_and_exits_zero(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    result = _run_cli(
        [
            "plan",
            "apply",
            "--bundle",
            str(bundle),
            "--target",
            str(project.root),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    envelope = cast(dict[str, object], json.loads(render_json(result)))
    state = cast(dict[str, object], envelope["state"])
    assert isinstance(state["receipt"], dict)
    assert project.run_count() == 0


def test_plan_apply_out_file_exclusive(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    receipt = tmp_path / "receipt.json"
    base = [
        "plan",
        "apply",
        "--bundle",
        str(bundle),
        "--target",
        str(project.root),
        "--out",
        str(receipt),
    ]
    first = _run_cli(base, template_root=str(project.template_root))
    assert _exit_code(first) == 0
    assert receipt.is_file()
    second = _run_cli(base, template_root=str(project.template_root))
    # An occupied --out destination is an argument invariant (usage), so
    # the planning family exits 2 before any observation happens.
    assert _exit_code(second) == 2


def test_all_scaffold_apply_installs_and_exits_one(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    result = _run_cli(
        ["apply", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 1
    assert (project.root / ".rygor/project.json").is_file()
    assert project.run_count() == 1


def test_apply_revalidates_initial_candidate_before_writing(tmp_path: Path) -> None:
    from scripts.bootstrap.observation import (
        ResolvedShellTarget,
        SystemObservation,
    )
    from scripts.bootstrap.observation import (
        observe_system as real_observe,
    )
    from scripts.bootstrap.values import ResourceLimits

    project, bundle = _build_cli_fixture(tmp_path)
    calls = 0

    def observe_then_change(
        resolved: ResolvedShellTarget,
        *,
        coherent: bool,
        template_root: str,
        limits: ResourceLimits,
    ) -> Result[SystemObservation, CommandError]:
        nonlocal calls
        calls += 1
        if calls == 2:
            _ = (project.root / "README.md").write_text(
                "changed while acquiring the lock\n", encoding="utf-8"
            )
        return real_observe(
            resolved,
            coherent=coherent,
            template_root=template_root,
            limits=limits,
        )

    with patch("scripts.bootstrap.cli.observe_system", side_effect=observe_then_change):
        result = _run_cli(
            [
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(project.root),
            ],
            template_root=str(project.template_root),
        )

    assert calls == 2
    assert _exit_code(result) == 2
    assert "PRECONDITION_CHANGED" in render_text(result)
    assert not (project.root / ".rygor/project.json").exists()
    assert project.run_count() == 0


def test_restore_retains_existing_readiness_findings(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    applied = _run_cli(
        ["apply", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(applied) == 1
    restored = _run_cli(
        ["restore", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(restored) == 1
    assert "BOOTSTRAP_READINESS_BLOCKING" in render_text(restored)


def test_supplied_apply_exits_zero(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    parent = tmp_path / "supplied"
    parent.mkdir()
    supplied = write_answer_bundle(parent, supplied=True, record=project.hook_runs)
    result = _run_cli(
        ["apply", "--bundle", str(supplied), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert project.run_count() == 1


def test_apply_already_installed_refuses(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    _ = _run_cli(
        ["apply", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    second = _run_cli(
        ["apply", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(second) == 1
    assert "run uv run --python 3.14 scripts/validate_repository.py" in render_text(
        second
    )


# --- AdoptionTests -----------------------------------------------------------


def _adoption_target(parent: Path, **files: str) -> Path:
    """Create one manifest-free, non-bare Git working tree for adoption."""

    parent.mkdir(parents=True, exist_ok=True)
    return seed_repo(
        parent,
        {"notes.txt": "adopter notes\n", **files},
        name="adoptee",
    )


def _adoption_bundle(parent: Path, record: Path, *, hook_status: int = 0) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    bundle = write_answer_bundle(parent, supplied=True, record=record)
    if hook_status != 0:
        hook = bundle / "content/validate-project"
        _ = hook.write_text(f"#!/bin/sh\necho run >> {record}\nexit {hook_status}\n")
        hook.chmod(0o755)
    return bundle


def test_plan_adopt_writes_receipt_without_mutating_target(tmp_path: Path) -> None:
    from scripts.bootstrap.plan_digest import decode_receipt, encode_receipt
    from tests.fixtures import assert_ok

    target = _adoption_target(tmp_path)
    bundle = _adoption_bundle(tmp_path / "bundle", tmp_path / "hook-runs")
    receipt = tmp_path / "receipt.json"
    result = _run_cli(
        [
            "plan",
            "adopt",
            "--bundle",
            str(bundle),
            "--target",
            str(target),
            "--out",
            str(receipt),
        ],
        template_root=str(REPO_ROOT),
    )
    assert _exit_code(result) == 0
    assert receipt.is_file()
    decoded = assert_ok(decode_receipt(receipt.read_bytes()))
    envelope = cast(dict[str, object], json.loads(render_json(result)))
    state = cast(dict[str, object], envelope["state"])
    assert state["kind"] == "plan_receipt"
    assert json.loads(encode_receipt(decoded)) == state["receipt"]
    assert envelope["command"] == "plan adopt"
    assert not (target / "README.md").exists()
    assert not (target / ".rygor").exists()
    assert (target / "notes.txt").read_text() == "adopter notes\n"


def test_adopt_installs_and_exits_zero_on_hook_success(tmp_path: Path) -> None:
    target = _adoption_target(tmp_path)
    hook_runs = tmp_path / "hook-runs"
    _ = hook_runs.write_text("", encoding="utf-8")
    bundle = _adoption_bundle(tmp_path / "bundle", hook_runs)
    result = _run_cli(
        ["adopt", "--bundle", str(bundle), "--target", str(target)],
        template_root=str(REPO_ROOT),
    )
    assert _exit_code(result) == 0
    manifest = cast(
        dict[str, object], json.loads((target / ".rygor/project.json").read_text())
    )
    provenance = cast(dict[str, object], manifest["provenance"])
    assert provenance["generation_path"] == "adopted"
    assert (target / "AGENTS.md").is_file()
    assert (target / "CLAUDE.md").is_file()
    assert (target / "notes.txt").read_text() == "adopter notes\n"
    assert hook_runs.read_text().splitlines() == ["run"]


def test_adopt_installed_but_unready_exits_one_without_rollback(
    tmp_path: Path,
) -> None:
    target = _adoption_target(tmp_path)
    hook_runs = tmp_path / "hook-runs"
    _ = hook_runs.write_text("", encoding="utf-8")
    bundle = _adoption_bundle(tmp_path / "bundle", hook_runs, hook_status=3)
    result = _run_cli(
        ["adopt", "--bundle", str(bundle), "--target", str(target)],
        template_root=str(REPO_ROOT),
    )
    assert _exit_code(result) == 1
    assert (target / ".rygor/project.json").is_file()
    assert "action_required" in render_text(result)
    assert hook_runs.read_text().splitlines() == ["run"]


def test_adopt_refusals_exit_one_with_named_next_actions(tmp_path: Path) -> None:
    project, scaffold_bundle = _build_cli_fixture(tmp_path)
    bundle = _adoption_bundle(tmp_path / "adopt", project.hook_runs)
    over_scaffold = _run_cli(
        ["adopt", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(over_scaffold) == 1
    assert "APPLY_REQUIRED" in render_text(over_scaffold)
    assert project.run_count() == 0
    applied = _run_cli(
        ["apply", "--bundle", str(scaffold_bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(applied) == 1
    assert (project.root / ".rygor/project.json").is_file()
    over_project = _run_cli(
        ["adopt", "--bundle", str(bundle), "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(over_project) == 1
    assert "STATUS_REQUIRED" in render_text(over_project)


def test_adopt_contract_failures_exit_two(tmp_path: Path) -> None:
    target = _adoption_target(tmp_path, **{"README.md": "adopter readme\n"})
    bundle = _adoption_bundle(tmp_path / "bundle", tmp_path / "hook-runs")
    result = _run_cli(
        [
            "plan",
            "adopt",
            "--bundle",
            str(bundle),
            "--target",
            str(target),
        ],
        template_root=str(REPO_ROOT),
    )
    assert _exit_code(result) == 2
    assert "README.md" in render_text(result)


def test_status_names_adopt_next_actions_on_unmanaged_trees(tmp_path: Path) -> None:
    target = _adoption_target(tmp_path)
    result = _run_cli(
        ["status", "--target", str(target)],
        template_root=str(REPO_ROOT),
    )
    assert _exit_code(result) == 0
    text = render_text(result)
    assert "init" in text
    assert "plan adopt" in text
    assert not (target / ".rygor").exists()
    envelope = cast(dict[str, object], json.loads(render_json(result)))
    assert "plan adopt" in json.dumps(envelope["diagnostics"])


def test_adopt_json_emits_exactly_one_envelope_per_outcome(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.bootstrap.cli import main as cli_main

    target = _adoption_target(tmp_path / "json-target")
    hook_runs = tmp_path / "hook-runs"
    _ = hook_runs.write_text("", encoding="utf-8")
    bundle = _adoption_bundle(tmp_path / "bundle", hook_runs)
    unready_target = _adoption_target(tmp_path / "unready-target")
    unready_bundle = _adoption_bundle(
        tmp_path / "unready-bundle", hook_runs, hook_status=3
    )
    colliding = _adoption_target(tmp_path / "collide", **{"README.md": ""})
    cases = [
        (
            [
                "--format",
                "json",
                "plan",
                "adopt",
                "--bundle",
                str(bundle),
                "--target",
                str(target),
            ],
            "plan adopt",
            0,
        ),
        (
            [
                "--format",
                "json",
                "adopt",
                "--bundle",
                str(unready_bundle),
                "--target",
                str(unready_target),
            ],
            "adopt",
            1,
        ),
        (
            [
                "--format",
                "json",
                "adopt",
                "--bundle",
                str(bundle),
                "--target",
                str(colliding),
            ],
            "adopt",
            2,
        ),
    ]
    for argv, command, expected_exit in cases:
        _ = capsys.readouterr()
        assert cli_main(argv) == expected_exit
        rendered = capsys.readouterr().out
        document = cast(dict[str, object], json.loads(rendered))
        assert rendered.count('"schema_version"') == 1
        assert document["command"] == command
        assert document["exit_code"] == expected_exit


def test_valid_cleanup_apply_removes_declared_paths(tmp_path: Path) -> None:
    _project, bundle = _build_cli_fixture(tmp_path)
    parent = tmp_path / "clean-valid"
    parent.mkdir()
    cleanup_project = build_snapshot_project(
        parent,
        SnapshotConfig(template="synthetic", maintenance=True),
        pristine=pristine_snapshot(),
    )
    result = execute_command(
        _parse(
            [
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(cleanup_project.root),
            ]
        ),
        template_root=str(cleanup_project.template_root),
    )
    assert _exit_code(result) == 1  # scaffold slots remain unready
    assert not (cleanup_project.root / "tests").exists()
    assert not (cleanup_project.root / ".rygor/maintenance-artifacts.json").exists()
    assert (cleanup_project.root / ".rygor/project.json").is_file()
    assert cleanup_project.run_count() == 1
    # A completed transaction leaves no stage litter behind.
    for stage_root in (
        cleanup_project.root / ".rygor-stage",
        cleanup_project.root / "docs/.rygor-stage",
        cleanup_project.root / "scripts/.rygor-stage",
    ):
        assert not stage_root.exists()


def test_cleanup_mismatch_and_leave_override(tmp_path: Path) -> None:
    _project, bundle = _build_cli_fixture(tmp_path)
    parent = tmp_path / "cleanup"
    parent.mkdir()
    cleanup_project = build_snapshot_project(
        parent,
        SnapshotConfig(template="synthetic", maintenance=True),
        pristine=pristine_snapshot(),
    )
    # Damage one declared cleanup path so the inventory no longer matches.
    _ = (cleanup_project.root / "tests/test_script_cores.py").write_text(
        "drift\n", encoding="utf-8"
    )
    refused = execute_command(
        _parse(
            [
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(cleanup_project.root),
            ]
        ),
        template_root=str(cleanup_project.template_root),
    )
    assert _exit_code(refused) == 1
    assert "CLEANUP_CONTRACT_INVALID" in render_text(refused)
    assert "tests" in render_text(refused)
    assert "--leave-maintenance-artifacts" in render_text(refused)
    assert (cleanup_project.root / ".rygor/maintenance-artifacts.json").is_file()
    leave = execute_command(
        _parse(
            [
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(cleanup_project.root),
                "--leave-maintenance-artifacts",
            ]
        ),
        template_root=str(cleanup_project.template_root),
    )
    assert _exit_code(leave) == 1  # scaffold slots remain unready
    assert (cleanup_project.root / ".rygor/maintenance-artifacts.json").is_file()
    assert (cleanup_project.root / ".rygor/project.json").is_file()


def test_protected_target_refuses(tmp_path: Path) -> None:
    _project, bundle = _build_cli_fixture(tmp_path)
    parent = tmp_path / "protected"
    parent.mkdir()
    protected_project = build_snapshot_project(
        parent,
        SnapshotConfig(template="synthetic"),
        pristine=pristine_snapshot(),
    )
    _ = subprocess.run(
        [
            "git",
            "-C",
            str(protected_project.root),
            "remote",
            "add",
            "origin",
            "https://github.com/knirski/rygor.git",
        ],
        check=True,
        capture_output=True,
    )
    result = execute_command(
        _parse(
            [
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(protected_project.root),
            ]
        ),
        template_root=str(protected_project.template_root),
    )
    assert _exit_code(result) == 1


def test_recover_no_journal_exits_zero_without_hook(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert project.run_count() == 0


def test_recover_stale_pending_discards(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    _ = (state_root / "journal.pending").write_text("stale", encoding="utf-8")
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert not (state_root / "journal.pending").exists()


def test_recover_invalid_journal_exits_two(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    _ = (state_root / "journal.json").write_text("not json", encoding="utf-8")
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 2
    assert (state_root / "journal.json").is_file()


def test_recover_target_mismatch_exits_one(tmp_path: Path) -> None:
    from scripts.bootstrap.identity import target_identity

    project = _build_cli_project(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    other = target_identity(b"/somewhere-else", device=1, inode=2)
    envelope = JournalEnvelope(
        operation="initial",
        target=JournalTarget.from_identity(other),
        phase=JournalPhase.PLANNED,
        transaction_id=new_transaction_id(),
        preparations=(),
    )
    _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 1
    assert (state_root / "journal.json").is_file()


def test_planned_recovery_cleans_preparations(tmp_path: Path) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    planned = _run_cli(
        [
            "plan",
            "apply",
            "--bundle",
            str(bundle),
            "--target",
            str(project.root),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(planned) == 0
    receipt = cast(dict[str, object], planned.state_document)["receipt"]
    identity = PreparationIdentity(
        transaction_id="ab" * 32,
        operation_index=0,
        role=PreparationRole.STAGE,
        ownership_token_sha256="cd" * 32,
        expected_kind="file",
        expected_raw_sha256="ef" * 32,
        expected_mode=PosixMode(0o644),
    )
    envelope = JournalEnvelope(
        operation="initial",
        target=JournalTarget.from_identity(_target_identity(project.root)),
        phase=JournalPhase.PLANNED,
        transaction_id="ab" * 32,
        preparations=(identity,),
        receipt=cast(PlanReceipt, receipt),
    )
    _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert not (state_root / "journal.json").exists()


def test_sealed_recovery_cleans_surviving_stages(tmp_path: Path) -> None:
    # A crash after install but before cleanup leaves a SEALED journal and
    # marked stage directories.  Recovery must finish the forward cleanup
    # using the journaled identities (original ownership-token hashes),
    # never freshly minted tokens.
    project, bundle = _build_cli_fixture(tmp_path)
    state_root = project.root / ".git/rygor"
    state_root.mkdir(mode=0o700)
    planned = _run_cli(
        [
            "plan",
            "apply",
            "--bundle",
            str(bundle),
            "--target",
            str(project.root),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(planned) == 0
    receipt = cast(dict[str, object], planned.state_document)["receipt"]
    installed = _run_cli(
        [
            "apply",
            "--bundle",
            str(bundle),
            "--target",
            str(project.root),
        ],
        template_root=str(project.template_root),
    )
    assert _exit_code(installed) == 1
    receipt = cast(dict[str, object], planned.state_document)["receipt"]
    match reconstruct_plan(
        cast(PlanReceipt, receipt), target=_target_identity(project.root)
    ):
        case Err(error):
            raise AssertionError(f"receipt reconstruction failed: {error}")
        case Ok(plan):
            pass
    transaction_id = "ab" * 32
    token = bytes.fromhex("cd" * 32)
    specs = derive_preparation_specs(plan)
    preparations = derive_preparations(plan, transaction_id, (token,) * len(specs))

    def is_root_file_stage(spec: PreparationSpec) -> bool:
        if spec.role is not PreparationRole.STAGE or spec.expected_kind != "file":
            return False
        operation = plan.ordered_operations[spec.operation_index]
        match operation:
            case CreateFileOperation(path=path) | ReplaceFileOperation(path=path):
                return "/" not in path.value
            case _:
                return False

    stage_spec = next(spec for spec in specs if is_root_file_stage(spec))
    stage_identity = next(
        identity
        for identity in preparations
        if identity.role is PreparationRole.STAGE
        and identity.operation_index == stage_spec.operation_index
    )
    envelope = JournalEnvelope(
        operation="initial",
        target=JournalTarget.from_identity(_target_identity(project.root)),
        phase=JournalPhase.SEALED,
        transaction_id=transaction_id,
        preparations=preparations,
        receipt=cast(PlanReceipt, receipt),
    )
    _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
    stage_root = project.root / ".rygor-stage"
    stage_dir = stage_root / transaction_id / str(stage_spec.operation_index)
    stage_dir.mkdir(parents=True)
    marker = canonical_json(
        {
            "transaction_id": transaction_id,
            "operation_index": stage_identity.operation_index,
            "role": stage_identity.role.value,
            "token": token.hex(),
        }
    )
    _ = (stage_dir / "marker").write_bytes(marker)
    result = _run_cli(
        ["recover", "--target", str(project.root)],
        template_root=str(project.template_root),
    )
    assert _exit_code(result) == 0
    assert not (state_root / "journal.json").exists()
    assert not stage_dir.exists()
    assert not stage_root.exists()


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["status", "--target", "PLACEHOLDER"],
            id="status",
        ),
        pytest.param(
            [
                "plan",
                "apply",
                "--bundle",
                "PLACEHOLDER_BUNDLE",
                "--target",
                "PLACEHOLDER",
            ],
            id="plan-apply",
        ),
        pytest.param(
            [
                "adopt",
                "--bundle",
                "PLACEHOLDER_BUNDLE",
                "--target",
                "PLACEHOLDER",
            ],
            id="adopt",
        ),
        pytest.param(
            [
                "plan",
                "adopt",
                "--bundle",
                "PLACEHOLDER_BUNDLE",
                "--target",
                "PLACEHOLDER",
            ],
            id="plan-adopt",
        ),
        pytest.param(
            ["recover", "--target", "PLACEHOLDER"],
            id="recover",
        ),
    ],
)
def test_text_json_parity(tmp_path: Path, argv: list[str]) -> None:
    project, bundle = _build_cli_fixture(tmp_path)
    resolved = [
        str(project.root)
        if arg == "PLACEHOLDER"
        else str(bundle)
        if arg == "PLACEHOLDER_BUNDLE"
        else arg
        for arg in argv
    ]
    parsed = _parse(resolved)
    result = execute_command(parsed, template_root=str(project.template_root))
    text = render_text(result)
    envelope = cast(dict[str, object], json.loads(render_json(result)))
    assert envelope["exit_code"] == _exit_code(result)
    assert str(envelope["outcome_class"]) in text


def test_main_json_emits_single_envelope(tmp_path: Path) -> None:
    project = _build_cli_project(tmp_path)
    code = main(["--format", "json", "status", "--target", str(project.root)])
    assert code == 0


def test_main_json_usage_error_emits_single_envelope() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(["--format", "json", "status", "--unexpected"])

    assert code == 2
    assert stderr.getvalue() == ""
    document = cast(dict[str, object], json.loads(stdout.getvalue()))
    assert document["command"] == "bootstrap"
    assert document["outcome_class"] == "invalid_request"
    assert document["exit_code"] == 2


# --- EntryPointTests ---------------------------------------------------------


def test_entry_point_help_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy

    monkeypatch.setattr(sys, "argv", ["bootstrap_project.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        _ = runpy.run_path(
            str(ROOT / "scripts/bootstrap_project.py"), run_name="__main__"
        )
    assert exc_info.value.code == 0


def test_entry_point_usage_error_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy

    monkeypatch.setattr(sys, "argv", ["bootstrap_project.py", "--bogus"])
    with pytest.raises(SystemExit) as exc_info:
        _ = runpy.run_path(
            str(ROOT / "scripts/bootstrap_project.py"), run_name="__main__"
        )
    assert exc_info.value.code == 2


# --- ProjectChangesTests -----------------------------------------------------


@pytest.mark.parametrize(
    "generation",
    [
        pytest.param("github", id="github"),
        pytest.param("adopted", id="adopted"),
    ],
)
def test_snapshot_status_reports_the_recorded_generation(generation: str) -> None:
    from scripts.bootstrap.intents import GenerationPath
    from scripts.bootstrap.state import (
        ExistingProject,
        ManagedVerified,
        RecordedProjectState,
        SnapshotExistingProject,
        SnapshotSourceSame,
        TargetSnapshot,
    )

    gen = GenerationPath(generation)
    observation = ExistingProject(
        state=SnapshotExistingProject(
            recorded=RecordedProjectState(
                generation=gen,
                source_fingerprint="a" * 64,
            ),
            condition=SnapshotSourceSame(managed=ManagedVerified()),
            snapshot=TargetSnapshot(()),
        )
    )
    changes = _project_changes(observation)
    generation_change = next(
        change for change in changes if change.kind == "generation"
    )
    assert generation_change.subject == gen.value
    assert generation_change.detail == "a" * 16
