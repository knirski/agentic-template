#!/usr/bin/env python3
"""Fixture tests for aggregate repository validation."""

from __future__ import annotations

import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGGREGATE = ROOT / "scripts/validate-repository.py"


class AggregateFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(AGGREGATE, self.root / "scripts/validate-repository.py")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_stage(self, name: str, status: int, marker: str) -> None:
        path = self.root / "scripts" / name
        path.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(self.root / marker)!r}).write_text('ran')\nraise SystemExit({status})\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/validate-repository.py", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_stages_run_in_order_and_success_propagates(self) -> None:
        for name, marker in (
            ("validate-template.py", "template"),
            ("check-project-readiness.py", "readiness"),
            ("validate-project.py", "project"),
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
        self.write_stage("validate-template.py", 0, "template")
        self.write_stage("check-project-readiness.py", 7, "readiness")
        self.write_stage("validate-project.py", 0, "project")
        result = self.run_command()
        self.assertEqual(result.returncode, 7)
        self.assertTrue((self.root / "template").exists())
        self.assertTrue((self.root / "readiness").exists())
        self.assertFalse((self.root / "project").exists())

    def test_usage_error_is_two(self) -> None:
        self.assertEqual(self.run_command("unexpected").returncode, 2)


if __name__ == "__main__":
    unittest.main()
