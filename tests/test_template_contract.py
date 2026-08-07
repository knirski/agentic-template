#!/usr/bin/env python3
"""Exercise the source-only template contract and maintainer checks."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class TemplateContractTests(unittest.TestCase):
    def run_script(self, relative: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / relative)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_template_contract(self) -> None:
        result = self.run_script("scripts/validate_template.py")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_delivery_contract(self) -> None:
        result = self.run_script("tests/test_delivery_contract.py")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_shell_scripts_or_bash_shebangs(self) -> None:
        shell_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.suffix == ".sh"
        )
        bash_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.read_bytes().startswith(b"#!")
            and b"bash" in path.read_bytes().splitlines()[0]
        )
        self.assertEqual(shell_files, [], f"shell scripts remain: {shell_files}")
        self.assertEqual(bash_files, [], f"bash shebangs remain: {bash_files}")


if __name__ == "__main__":
    unittest.main()
