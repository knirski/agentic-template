#!/usr/bin/env python3
"""Exercise the Copier generation path end-to-end through the bootstrap CLI.

Copies the tracked source tree, overlays the remaining canonical seed-once
scaffold files, runs ``copier copy``, and installs supplied and
all-scaffold bundles through the generated project's own CLI entry point.  The
adopter-owned project-validation workflow is excluded from Copier, seeded by
bootstrap, and checked for preservation during a Copier update.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

VERSION = "9.17.0"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixtures import (  # noqa: E402
    CLEANUP_PATHS,
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    run,
    scaffold_hook,
    write_bundle,
)
from tests.git_config import configure_deterministic_git_environment  # noqa: E402

RETAINED_COPIER_PATHS = (
    ".rygor/source-ownership.json",
    ".copier-answers.yml",
    "AGENTS.md",
    "copier.yml",
    "docs/agents/domain.md",
    "scripts/bootstrap_project.py",
    "scripts/check-release-eligibility.py",
    "scripts/validate_repository.py",
)


def copier_command() -> list[str] | None:
    """The pinned Copier command, preferring a matching system install."""
    copier = shutil.which("copier")
    if copier and run([copier, "--version"]).stdout.strip() == f"copier {VERSION}":
        return [copier]
    if shutil.which("uvx"):
        return ["uvx", "--from", f"copier=={VERSION}", "copier"]
    return None


def main() -> int:
    configure_deterministic_git_environment()
    command = copier_command()
    if command is None:
        print(
            "Copier is required; install it with: uv tool install copier",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(prefix="rygor-copier-bootstrap.") as raw:
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
        record = workspace / "hook-runs"
        _ = record.write_text("", encoding="utf-8")
        # Replace the source hook and its canonical scaffold blob with a
        # recording scaffold for this fixture.
        hook = source / "scripts/validate-project"
        _ = hook.write_text(scaffold_hook(record), encoding="utf-8")
        hook.chmod(0o755)
        _ = (
            source / "scripts/bootstrap/fragments/scaffolds/validate-project"
        ).write_text(scaffold_hook(record), encoding="utf-8")
        _ = (source / "CONTRIBUTING.md").write_text(
            SCAFFOLD_CONTRIBUTING, encoding="utf-8"
        )
        _ = (source / "SECURITY.md").write_text(SCAFFOLD_SECURITY, encoding="utf-8")
        git = ["git", "-C", str(source)]
        for args in (
            ("init", "--initial-branch=main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Copier Bootstrap Test"),
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
            print(result.stdout + result.stderr, file=sys.stderr)
            return result.returncode
        # Copier retains generated-lifecycle source and excludes the
        # template-maintenance artifact set.
        for relative in RETAINED_COPIER_PATHS:
            if not (project / relative).is_file():
                print(
                    f"Copier output missing retained path: {relative}", file=sys.stderr
                )
                return 1
        for relative in (
            *CLEANUP_PATHS,
            ".git",
            ".rygor/maintenance-artifacts.json",
        ):
            if (project / relative).exists():
                print(
                    f"Copier output leaked maintainer path: {relative}", file=sys.stderr
                )
                return 1
        for args in (
            ("init", "--initial-branch=main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Copier Bootstrap Test"),
            ("add", "."),
            ("commit", "-m", "generated project"),
        ):
            _ = run(["git", "-C", str(project), *list(args)])
        bundle = write_bundle(workspace, supplied=True, record=record)
        applied = run(
            [
                sys.executable,
                str(project / "scripts/bootstrap_project.py"),
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(project),
            ]
        )
        if applied.returncode != 0:
            print(applied.stdout + applied.stderr, file=sys.stderr)
            return 1
        if not (project / ".rygor/project.json").is_file():
            print("Copier bootstrap apply left no manifest", file=sys.stderr)
            return 1
        generated_pyproject = (
            ROOT / "scripts/fixtures/generated-dependencies/pyproject.toml"
        )
        actual = (project / "pyproject.toml").read_text(encoding="utf-8")
        if actual != generated_pyproject.read_text(encoding="utf-8"):
            print(
                "Copier bootstrap apply left an unexpected generated pyproject",
                file=sys.stderr,
            )
            return 1
        if (project / "uv.lock").exists():
            print("Copier bootstrap apply claimed a uv lock", file=sys.stderr)
            return 1
        if len(record.read_text(encoding="utf-8").splitlines()) != 1:
            print("Copier bootstrap apply hook count != 1", file=sys.stderr)
            return 1
        project_validation = project / ".github/workflows/project-validation.yml"
        if not project_validation.is_file():
            print(
                "Copier bootstrap did not seed project-validation.yml", file=sys.stderr
            )
            return 1
        _ = project_validation.write_text(
            project_validation.read_text(encoding="utf-8")
            + "\n# adopter customization\n",
            encoding="utf-8",
        )
        committed = run(["git", "-C", str(project), "add", "-A"])
        if committed.returncode:
            print(committed.stdout + committed.stderr, file=sys.stderr)
            return committed.returncode
        committed = run(
            [
                "git",
                "-C",
                str(project),
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "user.name=Copier Bootstrap Test",
                "commit",
                "-m",
                "adopter customization",
            ]
        )
        if committed.returncode:
            print(committed.stdout + committed.stderr, file=sys.stderr)
            return committed.returncode
        updated = run([*command, "update", "--defaults"], cwd=project)
        if updated.returncode:
            print(updated.stdout + updated.stderr, file=sys.stderr)
            return updated.returncode
        if "# adopter customization" not in project_validation.read_text(
            encoding="utf-8"
        ):
            print("Copier update overwrote project-validation.yml", file=sys.stderr)
            return 1
        second = workspace / "project-scaffold"
        result = run(
            [
                *command,
                "copy",
                str(source),
                str(second),
                "--vcs-ref",
                "v0.1.0",
                "--defaults",
            ]
        )
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr)
            return result.returncode
        for args in (
            ("init", "--initial-branch=main"),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Copier Bootstrap Test"),
            ("add", "."),
            ("commit", "-m", "generated project"),
        ):
            _ = run(["git", "-C", str(second), *list(args)])
        scaffold_bundle = write_bundle(
            workspace, supplied=False, record=record, name="bundle-scaffold"
        )
        scaffolded = run(
            [
                sys.executable,
                str(second / "scripts/bootstrap_project.py"),
                "apply",
                "--bundle",
                str(scaffold_bundle),
                "--target",
                str(second),
            ]
        )
        # Scaffold slots remain unready: install completes, hook runs once,
        # and the command reports not-ready at exit 1.
        if scaffolded.returncode != 1:
            print(scaffolded.stdout + scaffolded.stderr, file=sys.stderr)
            return 1
        if not (second / ".rygor/project.json").is_file():
            print("Copier scaffold apply left no manifest", file=sys.stderr)
            return 1
        if len(record.read_text(encoding="utf-8").splitlines()) != 2:
            print("Copier scaffold apply hook count != 2", file=sys.stderr)
            return 1
    print("copier bootstrap contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
