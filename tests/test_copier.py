#!/usr/bin/env python3
"""Smoke-test Copier copy and update ownership boundaries."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "9.17.0"
ROOT = Path(__file__).resolve().parent.parent
VALID_PRD = """# Product\n## Problem\nProblem.\n## Goals\nGoals.\n## Non-goals\nNo.\n## Users and workflows\nUsers.\n## Requirements\n### REQ-001: Works\nBody.\n## Quality attributes\nReliable.\n## Release criteria\nGreen.\n## Open questions\nNone.\n"""
VALID_README = """# Product\n## Setup\nSetup.\n## Validation\nRun `python3.14 scripts/validate_repository.py`.\n"""
VALID_SECURITY = "# Security\n\nReport issues privately.\n"
VALID_CONTRIBUTING = "# Contributing\n\nContribution guidance.\n"


def run(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def main() -> int:
    copier = shutil.which("copier")
    if copier and run([copier, "--version"]).stdout.strip() == f"copier {VERSION}":
        command = [copier]
    elif shutil.which("uvx"):
        command = ["uvx", "--from", f"copier=={VERSION}", "copier"]
    else:
        print(
            "Copier is required; install it with: uv tool install copier",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(prefix="rygor-copier.") as raw:
        workspace = Path(raw)
        source, project = workspace / "source", workspace / "project"
        _ = shutil.copytree(
            ROOT,
            source,
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
        git = ["git", "-C", str(source)]
        for args in (
            ("init", "--initial-branch=main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Copier Test"),
            ("add", "."),
            ("commit", "-m", "template v0.1.0"),
            ("tag", "v0.1.0"),
        ):
            result = run(git + list(args))
            if result.returncode:
                print(result.stderr, file=sys.stderr)
                return result.returncode
        result = run(
            [
                *command,
                "copy",
                str(source),
                str(project),
                "--vcs-ref",
                "v0.1.0",
                "--defaults",
            ]
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode
        if not (project / ".copier-answers.yml").is_file() or any(
            (project / path).exists()
            for path in (
                ".git",
                ".python-version",
                "pyproject.toml",
                "uv.lock",
                "tests",
            )
        ):
            print("Copier output ownership contract failed", file=sys.stderr)
            return 1
        if (project / ".github/workflows/project-validation.yml").exists():
            print(
                "Copier output claimed the adopter-owned project-validation workflow",
                file=sys.stderr,
            )
            return 1
        initial_readiness = run(
            [sys.executable, "scripts/check_project_readiness.py"], cwd=project
        )
        if initial_readiness.returncode != 1:
            print("untouched Copier output must fail readiness", file=sys.stderr)
            return 1
        # The adopter-owned reusable workflow is seeded by bootstrap, not by
        # Copier.  Continue this smoke test at the post-bootstrap validation
        # boundary after proving the raw Copier output excluded it above.
        _ = shutil.copy2(
            ROOT / ".github/workflows/project-validation.yml",
            project / ".github/workflows/project-validation.yml",
        )
        _ = (project / "SECURITY.md").write_text(VALID_SECURITY, encoding="utf-8")
        _ = (project / "CONTRIBUTING.md").write_text(
            VALID_CONTRIBUTING, encoding="utf-8"
        )
        project_git = ["git", "-C", str(project)]
        for args in (
            ("init", "--initial-branch=main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Copier Test"),
            ("add", "."),
            ("commit", "-m", "generated project"),
        ):
            _ = run(project_git + list(args))
        _ = (project / "docs/prd.md").write_text(VALID_PRD, encoding="utf-8")
        _ = (project / "README.md").write_text(VALID_README, encoding="utf-8")
        project_hook = project / "scripts/validate-project"
        _ = project_hook.write_text(
            "#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8"
        )
        project_hook.chmod(project_hook.stat().st_mode | 0o100)
        configured = run(
            [sys.executable, "scripts/validate_repository.py"], cwd=project
        )
        if configured.returncode:
            print(configured.stderr, file=sys.stderr)
            return configured.returncode
        shutil.rmtree(project / "scripts/__pycache__", ignore_errors=True)
        with (source / "NOTICE.md").open("a", encoding="utf-8") as handle:
            _ = handle.write("\nCopier smoke-test marker.\n")
        source_scaffold_hook = (
            source / "scripts/bootstrap/fragments/scaffolds/validate-project"
        )
        with source_scaffold_hook.open("a", encoding="utf-8") as handle:
            _ = handle.write("\n# template scaffold update\n")
        _ = run(
            [
                *git,
                "add",
                "NOTICE.md",
                "scripts/bootstrap/fragments/scaffolds/validate-project",
            ]
        )
        _ = run([*git, "commit", "-m", "template v0.2.0"])
        _ = run([*git, "tag", "v0.2.0"])
        with (project / "README.md").open("a", encoding="utf-8") as handle:
            _ = handle.write("\nLocal project customization.\n")
        with project_hook.open("a", encoding="utf-8") as handle:
            _ = handle.write("\n# local hook customization\n")
        project_scaffold_hook = (
            project / "scripts/bootstrap/fragments/scaffolds/validate-project"
        )
        with project_scaffold_hook.open("a", encoding="utf-8") as handle:
            _ = handle.write("\n# local scaffold customization\n")
        _ = run(
            [
                *project_git,
                "add",
                "README.md",
                "docs/prd.md",
                "scripts/validate-project",
                "scripts/bootstrap/fragments/scaffolds/validate-project",
            ]
        )
        _ = run([*project_git, "commit", "-m", "project customization"])
        result = run(
            [*command, "update", "--vcs-ref", "v0.2.0", "--defaults"], cwd=project
        )
        hook_text = project_hook.read_text(encoding="utf-8")
        scaffold_hook_text = project_scaffold_hook.read_text(encoding="utf-8")
        conflict_evidence = (
            any(project.glob("**/*.rej"))
            or any(project.glob("**/*.conflict"))
            or "<<<<<<<" in hook_text
            or "<<<<<<<" in scaffold_hook_text
        )
        if result.returncode and not conflict_evidence:
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
        if (
            # Copier owns generated-lifecycle source inputs, while the
            # adopter-owned root hook remains outside Copier ownership.
            "# template scaffold update" not in scaffold_hook_text
            or "# local scaffold customization" not in scaffold_hook_text
            or "# local hook customization" not in hook_text
            or "Copier smoke-test marker."
            not in (project / "NOTICE.md").read_text(encoding="utf-8")
            or "Local project customization."
            not in (project / "README.md").read_text(encoding="utf-8")
        ):
            print(result.stderr, file=sys.stderr)
            return 1
    print("copier contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
