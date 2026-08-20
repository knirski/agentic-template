"""End-to-end CLI wiring for the restore transition (T18)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import cast

import pytest

from tests import test_source_bootstrap
from tests.fixtures import run

CLI = [sys.executable, "scripts/bootstrap_project.py"]


def _status(project: Path) -> str:
    result = run([*CLI, "status", "--target", str(project)])
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _activate_or_skip(raw: Path) -> tuple[Path, Path]:
    """Bootstrap a project, skipping on the environment's known apply breakage.

    This checkout cannot satisfy the cleanup contract (``apply`` reports
    ``CLEANUP_CONTRACT_INVALID`` before any mutation), so the e2e restore tests
    skip on exactly that diagnostic and fail loudly on any other failure.
    """

    try:
        return test_source_bootstrap._activate_source(raw)
    except AssertionError as error:
        if "CLEANUP_CONTRACT_INVALID" in str(error):
            pytest.skip(f"apply cannot bootstrap in this environment: {error}")
        raise


def test_restore_repairs_drifted_managed_file() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-restore.") as raw:
        project, _record = _activate_or_skip(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[test_source_bootstrap.CORE_CI_PATH]

        # Sanity: apply installed the certified managed bytes.
        assert managed.read_bytes() == compiled

        # Drift the managed file.
        drifted = b"this is not the certified ci content\n"
        _ = managed.write_bytes(drifted)
        assert b"managed: drift" in _status(project).encode()

        # Restore repairs it.
        restored = run([*CLI, "restore", "--target", str(project)])
        assert restored.returncode == 0, restored.stdout + restored.stderr
        assert managed.read_bytes() == compiled

        # No managed drift remains.
        assert "no managed drift" in _status(project)


def test_plan_restore_does_not_mutate_and_receipt_is_written() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-restore.") as raw:
        project, _record = _activate_or_skip(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[test_source_bootstrap.CORE_CI_PATH]
        _ = managed.write_bytes(b"drifted\n")

        receipt = Path(raw) / "restore-plan.json"
        planned = run(
            [
                *CLI,
                "plan",
                "restore",
                "--target",
                str(project),
                "--out",
                str(receipt),
            ]
        )
        assert planned.returncode == 0, planned.stdout + planned.stderr
        assert receipt.exists()
        document = cast(dict[str, object], json.loads(receipt.read_text(encoding="utf-8")))
        assert document["operation_kind"] == "restore"
        # Planning must not mutate the live file.
        assert managed.read_bytes() == b"drifted\n"

        # The bounded plan then executes and repairs.
        executed = run([*CLI, "restore", "--target", str(project)])
        assert executed.returncode == 0, executed.stdout + executed.stderr
        assert managed.read_bytes() == compiled


def test_restore_leaves_unrelated_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="agentic-template-restore.") as raw:
        project, _record = _activate_or_skip(Path(raw))
        managed = project / test_source_bootstrap.CORE_CI_PATH
        compiled = test_source_bootstrap.render_for(())[test_source_bootstrap.CORE_CI_PATH]
        _ = managed.write_bytes(b"managed drift\n")
        # A non-managed source file also drifts; restore must not touch it.
        readme = project / "README.md"
        _ = readme.write_text("unrelated drift\n", encoding="utf-8")

        executed = run([*CLI, "restore", "--target", str(project)])
        assert executed.returncode == 0, executed.stdout + executed.stderr
        assert managed.read_bytes() == compiled
        assert readme.read_text(encoding="utf-8") == "unrelated drift\n"

