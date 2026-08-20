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
from scripts.bootstrap.manifest import MaintenanceRecord, ManifestAdditions
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
    return _compile(
        managed, observed_snapshot(managed, drift=drifted), overwrite=True
    )


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
            result = _verify_reconcile_receipt(str(receipt), _drifted_plan(), DEFAULT_LIMITS)
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


def test_reconcile_plan_receipt_binds_execution() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-reconcile.") as raw:
        project, _record = _activate_or_skip(Path(raw))
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

        # A stale receipt no longer binds once the plan changes.
        _ = source.write_text("drifted source again\n", encoding="utf-8")
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
        assert refused.returncode == 1, refused.stdout + refused.stderr
        assert "--plan does not match the current reconcile" in (
            refused.stdout + refused.stderr
        )
        assert source.read_text(encoding="utf-8") == "drifted source again\n"

        # The unbound reconcile of source-only drift succeeds and advances.
        reconciled = run([*CLI, "reconcile", "--target", str(project)])
        assert reconciled.returncode == 0, reconciled.stdout + reconciled.stderr
        assert source.read_text(encoding="utf-8") == "drifted source again\n"
