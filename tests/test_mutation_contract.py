"""Tests for the focused mutation-testing setup."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent


def test_mutation_scope_targets_deterministic_source_and_direct_tests() -> None:
    project = cast(
        dict[str, dict[str, dict[str, list[str]]]],
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8")),
    )
    config = project["tool"]["mutmut"]

    assert config["source_paths"] == [
        "scripts/bootstrap",
        "scripts/check_project_readiness.py",
        "scripts/validate_repository.py",
    ]
    assert (
        "tests/test_bootstrap_foundations.py"
        in config["pytest_add_cli_args_test_selection"]
    )
    assert "tests/test_script_cores.py" in config["pytest_add_cli_args_test_selection"]
    assert (
        "not test_canonical_json_round_trips_arbitrary_strict_values"
        in config["pytest_add_cli_args_test_selection"]
    )


def test_mutation_workflow_is_scheduled_and_manual() -> None:
    workflow = (ROOT / ".github/workflows/mutation.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert 'cron: "17 3 * * 1"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "uv sync --all-groups --locked" in workflow
    assert "uv run mutmut run" in workflow
    assert "permissions:\n  contents: read" in workflow
