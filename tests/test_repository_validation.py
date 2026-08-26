#!/usr/bin/env python3
"""Fixture tests for aggregate repository validation."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast, override

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
from tests.factory import copy_tree  # noqa: E402

AGGREGATE = ROOT / "scripts/validate_repository.py"


class AggregateFixtures(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory[str]  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle
    root: Path  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle

    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        _ = shutil.copy2(AGGREGATE, self.root / "scripts/validate_repository.py")
        copy_tree(ROOT / "scripts/bootstrap", self.root / "scripts/bootstrap")

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_stage(self, name: str, status: int, marker: str) -> None:
        path = self.root / "scripts" / name
        _ = path.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(self.root / marker)!r}).write_text('ran')\nraise SystemExit({status})\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/validate_repository.py", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_stages_run_in_order_and_success_propagates(self) -> None:
        for name, marker in (
            ("validate_template.py", "template"),
            ("check_project_readiness.py", "readiness"),
            ("validate-project", "project"),
        ):
            self.write_stage(name, 0, marker)
        result = self.run_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("==>"), 3)
        self.assertTrue((self.root / "template").exists())
        self.assertTrue((self.root / "readiness").exists())
        self.assertTrue((self.root / "project").exists())

    def test_first_failure_status_is_preserved_and_later_stages_do_not_run(
        self,
    ) -> None:
        self.write_stage("validate_template.py", 0, "template")
        self.write_stage("check_project_readiness.py", 7, "readiness")
        self.write_stage("validate-project", 0, "project")
        result = self.run_command()
        self.assertEqual(result.returncode, 7)
        self.assertTrue((self.root / "template").exists())
        self.assertTrue((self.root / "readiness").exists())
        self.assertFalse((self.root / "project").exists())

    def test_usage_error_is_two(self) -> None:
        self.assertEqual(self.run_command("unexpected").returncode, 2)

    def test_json_usage_error_is_one_machine_owned_document(self) -> None:
        result = self.run_command("--format", "json", "unexpected")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        document = cast(dict[str, object], json.loads(result.stdout))
        self.assertEqual(document["command"], "validate_repository")
        self.assertEqual(document["outcome_class"], "invalid_request")
        self.assertEqual(document["exit_code"], 2)

    def test_json_output_is_one_safe_document(self) -> None:
        for name, marker in (
            ("validate_template.py", "template"),
            ("check_project_readiness.py", "readiness"),
            ("validate-project", "project"),
        ):
            self.write_stage(name, 0, marker)
        result = self.run_command("--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("==>", result.stdout)
        document = cast(dict[str, object], json.loads(result.stdout))
        self.assertEqual(document["outcome_class"], "succeeded")
        stages = cast(list[dict[str, str]], document["stages"])
        self.assertEqual(
            [stage["label"] for stage in stages],
            [
                "template contract",
                "project readiness",
                "project validation",
            ],
        )

    def test_quiet_text_output_omits_stage_headers(self) -> None:
        for name, marker in (
            ("validate_template.py", "template"),
            ("check_project_readiness.py", "readiness"),
            ("validate-project", "project"),
        ):
            self.write_stage(name, 0, marker)
        result = self.run_command("--quiet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("==>", result.stdout)

    def test_adapter_uses_shared_typed_validation_program(self) -> None:
        self.assertIs(
            validate_repository.ValidationProgram,  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
            CoreValidationProgram,
        )
        self.assertIs(
            validate_repository.StagePassed,  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
            CoreStagePassed,
        )
        self.assertIs(
            validate_repository.StageFailed,  # pyright: ignore[reportPrivateLocalImportUsage]  deliberate adapter re-export identity check
            CoreStageFailed,
        )


if __name__ == "__main__":
    _ = unittest.main()
