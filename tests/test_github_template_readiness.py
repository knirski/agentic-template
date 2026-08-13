#!/usr/bin/env python3
"""Exercise the GitHub-style same-tree generation path."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_GENERATED = {
    "scripts/check_project_readiness.py",
    "scripts/validate_project.py",
    "scripts/validate_repository.py",
    "scripts/validate_template.py",
}
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
Run `python3 scripts/validate_repository.py`.
"""


class GitHubSnapshot(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"
        if shutil.which("git"):
            self.project.mkdir()
            tracked = (
                subprocess.run(
                    ["git", "-C", str(ROOT), "ls-files", "-z"],
                    check=True,
                    capture_output=True,
                )
                .stdout.decode()
                .split("\0")
            )
            manifest = set(filter(None, tracked)) | REQUIRED_GENERATED
            for relative in sorted(manifest):
                source = ROOT / relative
                target = self.project / relative
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        else:
            shutil.copytree(
                ROOT,
                self.project,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".direnv",
                    "__pycache__",
                    "result",
                    ".venv",
                    ".hypothesis",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".mypy_cache",
                    ".coverage",
                ),
            )
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse((self.project / ".direnv").exists())
        self.assertFalse((self.project / "untracked-canary.txt").exists())
        for relative in ("docs/prd.md", "README.md", "scripts/validate_project.py"):
            path = self.project / relative
            path.chmod(path.stat().st_mode | 0o600)

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/check_project_readiness.py"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/validate_repository.py"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_untouched_snapshot_fails_then_minimal_configuration_passes(self) -> None:
        untouched = self.run_checker()
        self.assertEqual(untouched.returncode, 1)
        self.assertIn("READINESS_PRD_MARKER", untouched.stderr)
        self.assertIn("READINESS_README_BOILERPLATE", untouched.stderr)
        (self.project / "docs/prd.md").write_text(PRD, encoding="utf-8")
        (self.project / "README.md").write_text(README, encoding="utf-8")
        hook = self.project / "scripts/validate_project.py"
        hook.write_text(f"#!{sys.executable}\nprint('ok')\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | 0o100)
        configured = self.run_validator()
        self.assertEqual(configured.returncode, 0, configured.stderr)


if __name__ == "__main__":
    unittest.main()
