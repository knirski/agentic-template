#!/usr/bin/env python3
"""Fixture tests for the generated-project readiness contract."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts/check_project_readiness.py"
HOOK_SENTINEL = "rygor:unconfigured:validate-project"


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
Run `uv run --python 3.14 scripts/validate_repository.py`.
"""
VALID_HOOK = """#!/usr/bin/env python3
print('project validation passed')
"""
VALID_SECURITY = "# Security\n\nReport issues privately.\n"
VALID_CONTRIBUTING = "# Contributing\n\nContribution guidance.\n"


def _write_file(
    root: Path, relative: str, content: str, executable: bool = False
) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_readiness_checker(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "scripts/check_project_readiness.py", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _snapshot_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (
            path.read_bytes(),
            path.stat().st_mode & 0o777,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def _build_readiness_project(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "docs").mkdir()
    (root / "scripts").mkdir()
    _ = shutil.copy2(CHECKER, root / "scripts/check_project_readiness.py")
    _ = shutil.copytree(ROOT / "scripts/bootstrap", root / "scripts/bootstrap")
    _write_file(root, "docs/prd.md", VALID_PRD)
    _write_file(root, "README.md", VALID_README)
    _write_file(root, "SECURITY.md", VALID_SECURITY)
    _write_file(root, "CONTRIBUTING.md", VALID_CONTRIBUTING)
    _write_file(root, "scripts/validate-project", VALID_HOOK, executable=True)
    return root


def test_valid_fixture_passes(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    result = _run_readiness_checker(root)
    assert result.returncode == 0, result.stderr


def test_markers_and_boilerplate_fail_with_actionable_diagnostics(
    tmp_path: Path,
) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(
        root,
        "docs/prd.md",
        VALID_PRD.replace(
            "# Product",
            "<!-- rygor:placeholder:prd -->\nThis file is authoritative for the Rygor.\n# Product",
        ),
    )
    _write_file(
        root,
        "README.md",
        VALID_README.replace(
            "# Example Product",
            "<!-- rygor:placeholder:readme -->\n# Rygor",
        ),
    )
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    for code, path in (
        ("READINESS_PRD_MARKER", "docs/prd.md"),
        ("READINESS_PRD_BOILERPLATE", "docs/prd.md"),
        ("READINESS_README_MARKER", "README.md"),
        ("READINESS_README_BOILERPLATE", "README.md"),
    ):
        assert code in result.stderr
        assert path in result.stderr
        assert "next:" in result.stderr


def test_requirements_and_heading_contracts(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(
        root,
        "docs/prd.md",
        VALID_PRD.replace("## Goals", "## Goals\n## Goals").replace(
            "### REQ-001: Deliver value",
            "### REQ-001: Deliver value\n### REQ-001: Duplicate",
        ),
    )
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_PRD_HEADING_DUPLICATE" in result.stderr
    assert "READINESS_REQUIREMENT_DUPLICATE" in result.stderr


def test_zero_requirement_id_and_empty_readme_sections_fail(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(root, "docs/prd.md", VALID_PRD.replace("REQ-001", "REQ-000"))
    _write_file(root, "README.md", "# Product\n\n## Setup\n\n## Validation\n")
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_REQUIREMENT_ID" in result.stderr
    assert "READINESS_README_SECTION_EMPTY" in result.stderr


def test_empty_requirement_title_fails(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(
        root,
        "docs/prd.md",
        VALID_PRD.replace("### REQ-001: Deliver value", "### REQ-001:"),
    )
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_REQUIREMENT_TITLE" in result.stderr


def test_heading_case_and_command_section_are_strict(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(root, "docs/prd.md", VALID_PRD.replace("## Problem", "## problem"))
    _write_file(
        root,
        "README.md",
        VALID_README.replace(
            "## Validation\nRun `uv run --python 3.14 scripts/validate_repository.py`.",
            "## Validation\nRun another command.\n\n## Setup\nuv run --python 3.14 scripts/validate_repository.py",
        ),
    )
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_PRD_HEADING_MISSING" in result.stderr
    assert "READINESS_README_COMMAND" in result.stderr


def test_fenced_readme_headings_do_not_count_as_sections(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _write_file(
        root,
        "README.md",
        "# Example Product\n\n```markdown\n## Setup\nInstall the product.\n\n## Validation\nRun the checks.\n```\n",
    )
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_README_SECTION" in result.stderr


def test_validation_hook_symlink_is_rejected(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    target = root / "real-validation-hook"
    _ = target.write_text(VALID_HOOK, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    hook = root / "scripts/validate-project"
    hook.unlink()
    hook.symlink_to(target)
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_HOOK_NOT_REGULAR" in result.stderr


def test_internal_read_error_returns_two(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    _ = (root / "docs/prd.md").write_bytes(b"\xff")
    result = _run_readiness_checker(root)
    assert result.returncode == 2
    assert "INTERNAL_READINESS_ERROR" in result.stderr


def test_fenced_declaration_does_not_count(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    prd = VALID_PRD.replace(
        "### REQ-001: Deliver value\nThe requirement body and acceptance evidence.",
        "```markdown\n### REQ-001: Example\n```\n",
    )
    _write_file(root, "docs/prd.md", prd)
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_REQUIREMENT_MISSING" in result.stderr


def test_hook_is_inspected_without_execution_or_mutation(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    canary = root / "canary"
    hook = root / "scripts/validate-project"
    _ = hook.write_text(
        f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(canary)!r}).write_text('executed')\n{HOOK_SENTINEL!r}\n",
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    before = _snapshot_tree(root)
    result = _run_readiness_checker(root)
    assert result.returncode == 1
    assert "READINESS_HOOK_SENTINEL" in result.stderr
    assert not canary.exists()
    assert before == _snapshot_tree(root)


def test_unexpected_arguments_are_usage_errors(tmp_path: Path) -> None:
    root = _build_readiness_project(tmp_path)
    result = _run_readiness_checker(root, "unexpected")
    assert result.returncode == 2
    assert "READINESS_USAGE_ERROR" in result.stderr
