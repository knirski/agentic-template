#!/usr/bin/env python3
"""Exercise the Copier generation path end-to-end through the bootstrap CLI.

Copies the tracked source tree, overlays the canonical seed-once scaffold (the
source does not yet ship ``CONTRIBUTING.md`` and the extensionless hook; T20
completes that transition), runs ``copier copy``, and installs supplied and
all-scaffold bundles through the generated project's own CLI entry point.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

VERSION = "9.17.0"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.test_github_template_readiness import (  # noqa: E402
    CLEANUP_PATHS,
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    _scaffold_hook,
    _write_bundle,
    run,
)

RETAINED_COPIER_PATHS = (
    ".agentic-template/source-ownership.json",
    ".copier-answers.yml",
    "AGENTS.md",
    "copier.yml",
    "docs/agents/domain.md",
    "scripts/bootstrap_project.py",
    "scripts/check-release-eligibility.py",
    "scripts/validate_repository.py",
)


def copier_command() -> list[str] | None:
    copier = shutil.which("copier")
    command = [copier] if copier else ["uvx", "--from", f"copier=={VERSION}", "copier"]
    if copier and run([*command, "--version"]).stdout.strip() != f"copier {VERSION}":
        return None
    if not copier and not shutil.which("uvx"):
        return None
    return command


def main() -> int:
    command = copier_command()
    if command is None:
        print(
            "Copier is required; install it with: uv tool install copier",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(
        prefix="agentic-template-copier-bootstrap."
    ) as raw:
        workspace = Path(raw)
        source, project = workspace / "source", workspace / "project"
        _ = shutil.copytree(
            ROOT,
            source,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".direnv", "result"),
        )
        record = workspace / "hook-runs"
        _ = record.write_text("", encoding="utf-8")
        # Overlay the seed-once scaffold the source does not ship yet: the
        # extensionless hook and CONTRIBUTING.md are absent from the source,
        # and its real SECURITY.md is not marker-bearing placeholder content.
        hook = source / "scripts/validate-project"
        _ = hook.write_text(_scaffold_hook(record), encoding="utf-8")
        hook.chmod(0o755)
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
            ".agentic-template/maintenance-artifacts.json",
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
        bundle = _write_bundle(workspace, supplied=True, record=record)
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
        if not (project / ".agentic-template/project.json").is_file():
            print("Copier bootstrap apply left no manifest", file=sys.stderr)
            return 1
        if len(record.read_text(encoding="utf-8").splitlines()) != 1:
            print("Copier bootstrap apply hook count != 1", file=sys.stderr)
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
        scaffold_bundle = _write_bundle(
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
        if not (second / ".agentic-template/project.json").is_file():
            print("Copier scaffold apply left no manifest", file=sys.stderr)
            return 1
        if len(record.read_text(encoding="utf-8").splitlines()) != 2:
            print("Copier scaffold apply hook count != 1", file=sys.stderr)
            return 1
    print("copier bootstrap contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
