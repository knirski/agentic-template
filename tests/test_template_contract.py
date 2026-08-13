#!/usr/bin/env python3
"""Exercise the source-only template contract and maintainer checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.validate_template as validate_template  # noqa: E402
from scripts.bootstrap import template_contract  # noqa: E402


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
        # Dependency and generated directories are environment state, not
        # repository content. A venv contains vendored third-party files --
        # e.g. basedpyright's `nodejs-wheel` ships `.sh` scripts under
        # `.venv/.../node-gyp/` and `.../npm/` -- that are outside the
        # no-shell-scripts repo contract this test enforces. Excluding them
        # keeps the check scoped to repository source, matching the existing
        # `.git` exclusion. This is scoping, not weakening: a real shell
        # script or bash shebang introduced into `scripts/` or `tests/`
        # would still fail here.
        excluded_dirs = {
            ".git",
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            ".worktrees",
            ".hypothesis",
            "mutants",
            "target",
        }
        shell_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file()
            and excluded_dirs.isdisjoint(path.parts)
            and path.suffix == ".sh"
        )
        bash_files = sorted(
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file()
            and excluded_dirs.isdisjoint(path.parts)
            and path.read_bytes().startswith(b"#!")
            and b"bash" in path.read_bytes().splitlines()[0]
        )
        self.assertEqual(shell_files, [], f"shell scripts remain: {shell_files}")
        self.assertEqual(bash_files, [], f"bash shebangs remain: {bash_files}")

    def test_adapter_delegates_contract_policy_to_bootstrap_core(self) -> None:
        with patch(
            "scripts.bootstrap.template_contract.required_contract_failures",
            return_value=("delegated failure",),
        ) as policy:
            failures = validate_template.validate_contract(Path("."), ())

        self.assertEqual(failures, ("delegated failure",))
        policy.assert_called_once()

    def test_missing_shared_bootstrap_module_fails_template_contract(self) -> None:
        missing = "scripts/bootstrap/presentation.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in template_contract.REQUIRED_FILES:
                if relative != missing:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _ = path.write_text("present", encoding="utf-8")
            skill_texts = tuple(
                (
                    f".agents/skills/{skill}/SKILL.md",
                    f"---\nname: {skill}\ndescription: valid\n---\n",
                )
                for skill in template_contract.REQUIRED_SKILLS
            )

            failures = validate_template.validate_contract(
                root, tuple((root / path, text) for path, text in skill_texts)
            )

        self.assertIn(f"missing required file: {missing}", failures)

    def test_empty_frontmatter_values_do_not_consume_later_lines(self) -> None:
        self.assertFalse(
            template_contract.valid_skill_frontmatter(
                "---\nname:\ndescription:\nx: populated\n---\n"
            )
        )
        self.assertTrue(
            template_contract.valid_skill_frontmatter(
                "---\nname: skill\ndescription: valid\n---\n"
            )
        )


if __name__ == "__main__":
    _ = unittest.main()
