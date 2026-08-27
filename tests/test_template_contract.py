#!/usr/bin/env python3
"""Exercise the source-only template contract and maintainer checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.validate_template as validate_template  # noqa: E402
from scripts.bootstrap import template_contract  # noqa: E402


def _run_script(relative: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_template_contract() -> None:
    result = _run_script("scripts/validate_template.py")
    assert result.returncode == 0, result.stderr


def test_delivery_contract() -> None:
    result = _run_script("tests/test_delivery_contract.py")
    assert result.returncode == 0, result.stderr


def test_no_shell_scripts_or_bash_shebangs() -> None:
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
    assert shell_files == [], f"shell scripts remain: {shell_files}"
    assert bash_files == [], f"bash shebangs remain: {bash_files}"


def test_adapter_delegates_contract_policy_to_bootstrap_core() -> None:
    with (
        patch(
            "scripts.bootstrap.template_contract.required_contract_failures",
            return_value=("delegated failure",),
        ) as policy,
        patch(
            "scripts.validate_template.validate_catalog_surface",
            return_value=(),
        ) as surface,
        patch(
            "scripts.validate_template.validate_readiness_rule_catalog",
            return_value=(),
        ) as readiness_surface,
    ):
        failures = validate_template.validate_contract(Path("."), ())

    assert failures == ("delegated failure",)
    policy.assert_called_once()
    surface.assert_called_once()
    readiness_surface.assert_called_once()


def test_missing_shared_bootstrap_module_fails_template_contract() -> None:
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

    assert f"missing required file: {missing}" in failures


def test_empty_frontmatter_values_do_not_consume_later_lines() -> None:
    assert not template_contract.valid_skill_frontmatter(
        "---\nname:\ndescription:\nx: populated\n---\n"
    )
    assert template_contract.valid_skill_frontmatter(
        "---\nname: skill\ndescription: valid\n---\n"
    )
