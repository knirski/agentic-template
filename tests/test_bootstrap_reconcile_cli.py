"""CLI-level reconcile wiring: receipt verification and the plan/reconcile binding."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from scripts.bootstrap.cli import (
    _verify_reconcile_receipt,  # pyright: ignore[reportPrivateUsage]  shared shell helper with the mutation executor
)
from scripts.bootstrap.errors import UsageError, UsageErrorKind
from scripts.bootstrap.identity import ManifestIdentity, sha256_hex
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    MaintenanceRecord,
    ManifestAdditions,
    ProvenanceRecord,
    build_candidate_manifest,
    decode_manifest,
    encode_manifest,
)
from scripts.bootstrap.plan_digest import build_receipt, encode_receipt
from scripts.bootstrap.planner import (
    OperationPlan,
    TargetSnapshot,
    compile_reconcile_plan,
)
from scripts.bootstrap.render import (
    ManagedFile,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.source_baseline import CopierSourceBaseline
from scripts.bootstrap.values import DEFAULT_LIMITS
from tests import test_source_bootstrap
from tests.bootstrap_fixtures import (
    TARGET,
    copier_source_baseline,
    fixture_answers,
    observed_snapshot,
    render_for,
)
from tests.fixtures import run

CLI = [sys.executable, "scripts/bootstrap_project.py"]


def _manifest(seed: bytes) -> ManifestIdentity:
    value = sha256_hex(seed)
    return ManifestIdentity(payload=value.encode("utf-8"), digest=value)


def _compile(
    managed: tuple[ManagedFile, ...],
    snapshot: TargetSnapshot,
    *,
    overwrite: bool,
) -> OperationPlan:
    result = compile_reconcile_plan(
        generation=GenerationPath.COPIER,
        target_identity=TARGET,
        answers=fixture_answers(),
        existing_additions=ManifestAdditions(),
        new_render=managed,
        existing_inventory=derive_managed_inventory(managed),
        old_source_baseline=copier_source_baseline(b"old"),
        new_source_baseline=copier_source_baseline(b"new"),
        old_manifest=_manifest(b"old"),
        maintenance=MaintenanceRecord(status="clean"),
        snapshot=snapshot,
        overwrite_drift=overwrite,
        limits=DEFAULT_LIMITS,
    )
    match result:
        case Ok(plan):
            return plan
        case Err(error):
            raise AssertionError(f"reconcile compile failed: {error}")


def _plan() -> OperationPlan:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    return _compile(managed, observed_snapshot(managed), overwrite=False)


def _drifted_plan() -> OperationPlan:
    managed, _blobs = render_for((), GenerationPath.COPIER)
    drifted = {managed[0].path.value: b"adopter edit\n"}
    return _compile(managed, observed_snapshot(managed, drift=drifted), overwrite=True)


def _activate_or_skip(raw: Path) -> tuple[Path, Path]:
    """Bootstrap a project, skipping on the environment's known apply breakage.

    This checkout cannot satisfy the cleanup contract (``apply`` reports
    ``CLEANUP_CONTRACT_INVALID`` before any mutation), so the e2e reconcile tests
    skip on exactly that diagnostic and fail loudly on any other failure.
    """

    try:
        return test_source_bootstrap._activate_source(raw)
    except AssertionError as error:
        if "CLEANUP_CONTRACT_INVALID" in str(error):
            pytest.skip(f"apply cannot bootstrap in this environment: {error}")
        raise


class TestVerifyReconcileReceipt:
    def test_matching_plan_receipt_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
            receipt = Path(raw) / "plan.json"
            plan = _plan()
            _ = receipt.write_bytes(encode_receipt(build_receipt(plan)))
            result = _verify_reconcile_receipt(str(receipt), plan, DEFAULT_LIMITS)
            assert isinstance(result, Ok)

    def test_mismatched_plan_receipt_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
            receipt = Path(raw) / "plan.json"
            _ = receipt.write_bytes(encode_receipt(build_receipt(_plan())))
            result = _verify_reconcile_receipt(
                str(receipt), _drifted_plan(), DEFAULT_LIMITS
            )
            assert isinstance(result, Err)
            assert isinstance(result.error, UsageError)
            assert result.error.kind == UsageErrorKind.INVALID_VALUE
            assert "--plan does not match the current reconcile" in result.error.subject

    def test_oversized_plan_receipt_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
            receipt = Path(raw) / "plan.json"
            with receipt.open("wb") as handle:
                _ = handle.write(b"x" * (DEFAULT_LIMITS.max_file_bytes + 1))
            result = _verify_reconcile_receipt(str(receipt), _plan(), DEFAULT_LIMITS)
            assert isinstance(result, Err)
            assert isinstance(result.error, UsageError)
            assert result.error.kind == UsageErrorKind.INVALID_VALUE
            assert "size limit" in result.error.subject

    def test_unreadable_plan_path_is_refused(self) -> None:
        result = _verify_reconcile_receipt(
            "/nonexistent/agentic-template/plan.json", _plan(), DEFAULT_LIMITS
        )
        assert isinstance(result, Err)
        assert isinstance(result.error, UsageError)
        assert result.error.kind == UsageErrorKind.INVALID_VALUE
        assert "--plan unreadable" in result.error.subject

    def test_invalid_receipt_bytes_are_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
            receipt = Path(raw) / "plan.json"
            _ = receipt.write_bytes(b"not a receipt")
            result = _verify_reconcile_receipt(str(receipt), _plan(), DEFAULT_LIMITS)
            assert isinstance(result, Err)
            assert isinstance(result.error, UsageError)
            assert result.error.kind == UsageErrorKind.INVALID_VALUE
            assert "--plan is not a valid receipt" in result.error.subject

    def test_symlink_receipt_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
            receipt = Path(raw) / "plan.json"
            target = Path(raw) / "target.json"
            _ = target.write_bytes(encode_receipt(build_receipt(_plan())))
            receipt.symlink_to(target)
            result = _verify_reconcile_receipt(str(receipt), _plan(), DEFAULT_LIMITS)
            assert isinstance(result, Err)
            assert isinstance(result.error, UsageError)
            assert result.error.kind == UsageErrorKind.INVALID_VALUE
            assert "regular receipt file" in result.error.subject


def _as_copier_project(project: Path) -> None:
    """Rewrite an activated GitHub project as a Copier project on disk.

    The CLI cannot generate a Copier project in this environment (Copier
    adoption runs outside the bundle), so the e2e converts the installed
    snapshot project: the answers file appears and the manifest provenance
    becomes Copier with the same recorded source entries.
    """

    answers = project / ".copier-answers.yml"
    _ = answers.write_text("_commit: e2e-reconcile\n", encoding="utf-8")
    manifest_path = project / ".agentic-template/project.json"
    match decode_manifest(manifest_path.read_bytes()):
        case Err(error):
            raise AssertionError(f"manifest decode failed: {error}")
        case Ok(manifest):
            pass
    copier = CopierSourceBaseline(
        kind="copier",
        fingerprint=manifest.provenance.source_baseline.fingerprint,
        entries=manifest.provenance.source_baseline.entries,
    )
    match build_candidate_manifest(
        answers=manifest.answers,
        additions=manifest.additions,
        provenance=ProvenanceRecord(
            generation_path=GenerationPath.COPIER,
            maintenance=manifest.provenance.maintenance,
            source_baseline=copier,
        ),
        managed=manifest.managed,
    ):
        case Ok(updated):
            _ = manifest_path.write_bytes(encode_manifest(updated))
        case Err(error):
            raise AssertionError(f"manifest rewrite failed: {error}")


def test_reconcile_plan_receipt_binds_execution() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
        project, _record = _activate_or_skip(Path(raw))
        _as_copier_project(project)
        source = project / "docs/agents/domain.md"
        _ = source.write_text("drifted source\n", encoding="utf-8")

        receipt = Path(raw) / "reconcile-plan.json"
        planned = run(
            [
                *CLI,
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert planned.returncode == 0, planned.stdout + planned.stderr
        assert receipt.exists()
        # Planning must not mutate the drifted source.
        assert source.read_text(encoding="utf-8") == "drifted source\n"

        # A stale receipt no longer binds once the plan changes: managed drift
        # changes the planned overwrite, so the preview receipt is refused.
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[
            test_source_bootstrap.CORE_CI_PATH
        ]
        _ = managed.write_bytes(b"adopter edit\n")
        refused = run(
            [
                *CLI,
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ]
        )
        assert refused.returncode == 2, refused.stdout + refused.stderr
        assert "--plan does not match the current reconcile" in (
            refused.stdout + refused.stderr
        )
        assert managed.read_bytes() == b"adopter edit\n"

        # The matching preview binds execution and repairs the managed drift.
        receipt.unlink()
        planned = run(
            [
                *CLI,
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--out",
                str(receipt),
            ]
        )
        assert planned.returncode == 0, planned.stdout + planned.stderr
        reconciled = run(
            [
                *CLI,
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ]
        )
        assert reconciled.returncode == 0, reconciled.stdout + reconciled.stderr
        assert managed.read_bytes() == compiled
        assert source.read_text(encoding="utf-8") == "drifted source\n"


def test_reconcile_refreshes_bootstrap_managed_document_transactionally() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
        project, _record = _activate_or_skip(Path(raw))
        _as_copier_project(project)
        fragment = project / "scripts/bootstrap/fragments/__init__.py"
        original = fragment.read_bytes()
        changed = original.replace(
            b"# Capabilities\n\nThis document",
            b"# Capabilities\n\nReconciled guidance marker.\n\nThis document",
            1,
        )
        assert changed != original
        _ = fragment.write_bytes(changed)

        receipt = Path(raw) / "reconcile-document.json"
        planned = run(
            [
                *CLI,
                "plan",
                "reconcile",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ],
            cwd=project,
        )
        assert planned.returncode == 0, planned.stdout + planned.stderr

        reconciled = run(
            [
                *CLI,
                "reconcile",
                "--target",
                str(project),
                "--overwrite-drift",
                "--plan",
                str(receipt),
            ],
            cwd=project,
        )
        assert reconciled.returncode == 0, reconciled.stdout + reconciled.stderr

        document = project / "docs/capabilities.md"
        assert b"Reconciled guidance marker." in document.read_bytes()
        match decode_manifest(
            (project / ".agentic-template/project.json").read_bytes()
        ):
            case Ok(manifest):
                managed = next(
                    entry
                    for entry in manifest.managed
                    if entry.path.value == document.relative_to(project).as_posix()
                )
            case Err(error):
                raise AssertionError(f"manifest decode failed: {error}")
        assert managed.sha256 == sha256_hex(document.read_bytes())
