"""Tests for the focused mutation-testing setup."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class MutationTestingContractTests(unittest.TestCase):
    def test_mutation_scope_targets_deterministic_source_and_direct_tests(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        config = project["tool"]["mutmut"]

        self.assertEqual(
            config["source_paths"],
            [
                "scripts/bootstrap",
                "scripts/check_project_readiness.py",
                "scripts/validate_repository.py",
            ],
        )
        self.assertIn(
            "tests/test_bootstrap_foundations.py",
            config["pytest_add_cli_args_test_selection"],
        )
        self.assertIn(
            "tests/test_script_cores.py", config["pytest_add_cli_args_test_selection"]
        )
        self.assertIn(
            "not test_accumulate_preserves_arbitrary_success_order and not test_canonical_json_round_trips_arbitrary_strict_values",
            config["pytest_add_cli_args_test_selection"],
        )

    def test_mutation_workflow_is_scheduled_and_manual(self) -> None:
        workflow = (ROOT / ".github/workflows/mutation.yml").read_text(encoding="utf-8")

        self.assertIn("schedule:", workflow)
        self.assertIn('cron: "17 3 * * 1"', workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("uv sync --all-groups --locked", workflow)
        self.assertIn("uv run mutmut run", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)


if __name__ == "__main__":
    unittest.main()
