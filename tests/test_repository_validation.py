#!/usr/bin/env python3
"""Fixture tests for aggregate repository validation."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.validate_repository as validate_repository  # noqa: E402
from scripts.bootstrap.validation_program import (  # noqa: E402
    StageFailed as CoreStageFailed,
)
from scripts.bootstrap.validation_program import (  # noqa: E402
    StagePassed as CoreStagePassed,
)
from scripts.bootstrap.validation_program import (  # noqa: E402
    ValidationProgram as CoreValidationProgram,
)

AGGREGATE = ROOT / "scripts/validate_repository.py"


def _write_stage(root: Path, name: str, status: int, marker: str) -> None:
    path = root / "scripts" / name
    _ = path.write_text(
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(root / marker)!r}).write_text('ran')\nraise SystemExit({status})\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_validation(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "scripts/validate_repository.py", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _build_validation_project(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "scripts").mkdir()
    _ = shutil.copy2(AGGREGATE, root / "scripts/validate_repository.py")
    _ = shutil.copytree(ROOT / "scripts/bootstrap", root / "scripts/bootstrap")
    return root


def test_stages_run_in_order_and_success_propagates(tmp_path: Path) -> None:
    root = _build_validation_project(tmp_path)
    for name, marker in (
        ("validate_template.py", "template"),
        ("check_project_readiness.py", "readiness"),
        ("validate-project", "project"),
    ):
        _write_stage(root, name, 0, marker)
    result = _run_validation(root)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("==>") == 3
    assert (root / "template").exists()
    assert (root / "readiness").exists()
    assert (root / "project").exists()


def test_first_failure_status_is_preserved_and_later_stages_do_not_run(
    tmp_path: Path,
) -> None:
    root = _build_validation_project(tmp_path)
    _write_stage(root, "validate_template.py", 0, "template")
    _write_stage(root, "check_project_readiness.py", 7, "readiness")
    _write_stage(root, "validate-project", 0, "project")
    result = _run_validation(root)
    assert result.returncode == 7
    assert (root / "template").exists()
    assert (root / "readiness").exists()
    assert not (root / "project").exists()


def test_usage_error_is_two(tmp_path: Path) -> None:
    root = _build_validation_project(tmp_path)
    assert _run_validation(root, "unexpected").returncode == 2


def test_json_usage_error_is_one_machine_owned_document(tmp_path: Path) -> None:
    root = _build_validation_project(tmp_path)
    result = _run_validation(root, "--format", "json", "unexpected")
    assert result.returncode == 2
    assert result.stderr == ""
    document = cast(dict[str, object], json.loads(result.stdout))
    assert document["command"] == "validate_repository"
    assert document["outcome_class"] == "invalid_request"
    assert document["exit_code"] == 2


def test_json_output_is_one_safe_document(tmp_path: Path) -> None:
    root = _build_validation_project(tmp_path)
    for name, marker in (
        ("validate_template.py", "template"),
        ("check_project_readiness.py", "readiness"),
        ("validate-project", "project"),
    ):
        _write_stage(root, name, 0, marker)
    result = _run_validation(root, "--format", "json")
    assert result.returncode == 0, result.stderr
    assert "==>" not in result.stdout
    document = cast(dict[str, object], json.loads(result.stdout))
    assert document["outcome_class"] == "succeeded"
    stages = cast(list[dict[str, str]], document["stages"])
    assert [stage["label"] for stage in stages] == [
        "template contract",
        "project readiness",
        "project validation",
    ]


def test_quiet_text_output_omits_stage_headers(tmp_path: Path) -> None:
    root = _build_validation_project(tmp_path)
    for name, marker in (
        ("validate_template.py", "template"),
        ("check_project_readiness.py", "readiness"),
        ("validate-project", "project"),
    ):
        _write_stage(root, name, 0, marker)
    result = _run_validation(root, "--quiet")
    assert result.returncode == 0, result.stderr
    assert "==>" not in result.stdout


def test_adapter_uses_shared_typed_validation_program() -> None:
    assert (
        validate_repository.ValidationProgram  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
        is CoreValidationProgram
    )
    assert (
        validate_repository.StagePassed  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
        is CoreStagePassed
    )
    assert (
        validate_repository.StageFailed  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
        is CoreStageFailed
    )
