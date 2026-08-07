#!/usr/bin/env python3
"""Fixture tests for the generated-project readiness contract."""

from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts/check_project_readiness.py"
HOOK_SENTINEL = "agentic-template:unconfigured:validate-project"


VALID_PRD = """# Product

## Problem
The product problem.
## Goals
The product goals.
## Non-goals
The exclusions.
## Users and workflows
The workflow.
## Requirements
### REQ-001: Deliver value
The requirement body and acceptance evidence.
## Quality attributes
Reliable.
## Release criteria
Green checks.
## Open questions
None.
"""
VALID_README = """# Example Product

## Setup
Install the product.

## Validation
Run `python3.14 scripts/validate_repository.py`.
"""
VALID_HOOK = """#!/usr/bin/env python3
print('project validation passed')
"""


class ReadinessFixtures(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "scripts").mkdir()
        shutil.copy2(CHECKER, self.root / "scripts/check_project_readiness.py")
        self.write("docs/prd.md", VALID_PRD)
        self.write("README.md", VALID_README)
        self.write("scripts/validate_project.py", VALID_HOOK, executable=True)

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, relative: str, content: str, executable: bool = False) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if executable:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_checker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/check_project_readiness.py", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def snapshot(self) -> dict[str, tuple[bytes, int]]:
        return {
            str(path.relative_to(self.root)): (
                path.read_bytes(),
                path.stat().st_mode & 0o777,
            )
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_valid_fixture_passes(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_markers_and_boilerplate_fail_with_actionable_diagnostics(self) -> None:
        self.write(
            "docs/prd.md",
            VALID_PRD.replace(
                "# Product",
                "<!-- agentic-template:placeholder:prd -->\nThis file is authoritative for the Agentic Delivery Template.\n# Product",
            ),
        )
        self.write(
            "README.md",
            VALID_README.replace(
                "# Example Product",
                "<!-- agentic-template:placeholder:readme -->\n# Agentic Delivery Template",
            ),
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        for code, path in (
            ("READINESS_PRD_MARKER", "docs/prd.md"),
            ("READINESS_PRD_BOILERPLATE", "docs/prd.md"),
            ("READINESS_README_MARKER", "README.md"),
            ("READINESS_README_BOILERPLATE", "README.md"),
        ):
            self.assertIn(code, result.stderr)
            self.assertIn(path, result.stderr)
            self.assertIn("next:", result.stderr)

    def test_requirements_and_heading_contracts(self) -> None:
        self.write(
            "docs/prd.md",
            VALID_PRD.replace("## Goals", "## Goals\n## Goals").replace(
                "### REQ-001: Deliver value",
                "### REQ-001: Deliver value\n### REQ-001: Duplicate",
            ),
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_PRD_HEADING_DUPLICATE", result.stderr)
        self.assertIn("READINESS_REQUIREMENT_DUPLICATE", result.stderr)

    def test_zero_requirement_id_and_empty_readme_sections_fail(self) -> None:
        self.write("docs/prd.md", VALID_PRD.replace("REQ-001", "REQ-000"))
        self.write("README.md", "# Product\n\n## Setup\n\n## Validation\n")
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_REQUIREMENT_ID", result.stderr)
        self.assertIn("READINESS_README_SECTION_EMPTY", result.stderr)

    def test_empty_requirement_title_fails(self) -> None:
        self.write(
            "docs/prd.md",
            VALID_PRD.replace("### REQ-001: Deliver value", "### REQ-001:"),
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_REQUIREMENT_TITLE", result.stderr)

    def test_heading_case_and_command_section_are_strict(self) -> None:
        self.write("docs/prd.md", VALID_PRD.replace("## Problem", "## problem"))
        self.write(
            "README.md",
            VALID_README.replace(
                "## Validation\nRun `python3.14 scripts/validate_repository.py`.",
                "## Validation\nRun another command.\n\n## Setup\npython3.14 scripts/validate_repository.py",
            ),
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_PRD_HEADING_MISSING", result.stderr)
        self.assertIn("READINESS_README_COMMAND", result.stderr)

    def test_fenced_readme_headings_do_not_count_as_sections(self) -> None:
        self.write(
            "README.md",
            "# Example Product\n\n```markdown\n## Setup\nInstall the product.\n\n## Validation\nRun the checks.\n```\n",
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_README_SECTION", result.stderr)

    def test_validation_hook_symlink_is_rejected(self) -> None:
        target = self.root / "real-validation-hook"
        target.write_text(VALID_HOOK, encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
        hook = self.root / "scripts/validate_project.py"
        hook.unlink()
        hook.symlink_to(target)
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_HOOK_NOT_EXECUTABLE", result.stderr)

    def test_internal_read_error_returns_two(self) -> None:
        (self.root / "docs/prd.md").write_bytes(b"\xff")
        result = self.run_checker()
        self.assertEqual(result.returncode, 2)
        self.assertIn("INTERNAL_READINESS_ERROR", result.stderr)

    def test_fenced_declaration_does_not_count(self) -> None:
        prd = VALID_PRD.replace(
            "### REQ-001: Deliver value\nThe requirement body and acceptance evidence.",
            "```markdown\n### REQ-001: Example\n```\n",
        )
        self.write("docs/prd.md", prd)
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_REQUIREMENT_MISSING", result.stderr)

    def test_hook_is_inspected_without_execution_or_mutation(self) -> None:
        canary = self.root / "canary"
        hook = self.root / "scripts/validate_project.py"
        hook.write_text(
            f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(canary)!r}).write_text('executed')\n{HOOK_SENTINEL!r}\n",
            encoding="utf-8",
        )
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        before = self.snapshot()
        result = self.run_checker()
        self.assertEqual(result.returncode, 1)
        self.assertIn("READINESS_HOOK_SENTINEL", result.stderr)
        self.assertFalse(canary.exists())
        self.assertEqual(before, self.snapshot())

    def test_unexpected_arguments_are_usage_errors(self) -> None:
        result = self.run_checker("unexpected")
        self.assertEqual(result.returncode, 2)
        self.assertIn("INTERNAL_READINESS_ERROR", result.stderr)


if __name__ == "__main__":
    unittest.main()
