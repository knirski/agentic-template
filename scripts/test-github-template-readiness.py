#!/usr/bin/env python3
"""Exercise the GitHub-style same-tree generation path."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PRD = """# Product
## Problem
Problem.
## Goals
Goals.
## Non-goals
No.
## Users and workflows
Users.
## Requirements
### REQ-001: Works
Acceptance body.
## Quality attributes
Reliable.
## Release criteria
Green.
## Open questions
None.
"""
README = """# Product
## Setup
Setup.
## Validation
Run `python3 scripts/validate-repository.py`.
"""


class GitHubSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"
        shutil.copytree(ROOT, self.project, ignore=shutil.ignore_patterns(".git", "__pycache__", ".direnv", "result"))
        for path in self.project.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o600)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", "scripts/check-project-readiness.py"], cwd=self.project, text=True, capture_output=True, check=False)

    def test_untouched_snapshot_fails_then_minimal_configuration_passes(self) -> None:
        untouched = self.run_checker()
        self.assertEqual(untouched.returncode, 1)
        self.assertIn("READINESS_PRD_MARKER", untouched.stderr)
        self.assertIn("READINESS_README_BOILERPLATE", untouched.stderr)
        (self.project / "docs/prd.md").write_text(PRD, encoding="utf-8")
        (self.project / "README.md").write_text(README, encoding="utf-8")
        hook = self.project / "scripts/validate-project.py"
        hook.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | 0o100)
        configured = self.run_checker()
        self.assertEqual(configured.returncode, 0, configured.stderr)


if __name__ == "__main__":
    unittest.main()
