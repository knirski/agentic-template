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
VALID_README = """# Product\n## Setup\nSetup.\n## Validation\nRun `python3 scripts/validate-repository.py`.\n"""


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def main() -> int:
    copier = shutil.which("copier")
    command = [copier] if copier else ["uvx", "--from", f"copier=={VERSION}", "copier"]
    if copier and run(command + ["--version"]).stdout.strip() != f"copier {VERSION}":
        print(f"Copier {VERSION} is required", file=sys.stderr)
        return 1
    if not copier and not shutil.which("uvx"):
        print("Copier is required; install it with: uv tool install copier", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="agentic-template-copier.") as raw:
        workspace = Path(raw)
        source, project = workspace / "source", workspace / "project"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", ".direnv", "result"))
        git = ["git", "-C", str(source)]
        for args in (("init", "--initial-branch=main"), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Copier Test"), ("add", "."), ("commit", "-m", "template v0.1.0"), ("tag", "v0.1.0")):
            result = run(git + list(args))
            if result.returncode:
                print(result.stderr, file=sys.stderr)
                return result.returncode
        result = run(command + ["copy", str(source), str(project), "--vcs-ref", "v0.1.0", "--defaults"])
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            return result.returncode
        if not (project / ".copier-answers.yml").is_file() or (project / "scripts/test-copier.py").exists():
            print("Copier output ownership contract failed", file=sys.stderr)
            return 1
        validation = run([sys.executable, "scripts/validate-template.py"], cwd=project)
        if validation.returncode:
            print(validation.stderr, file=sys.stderr)
            return validation.returncode
        initial_readiness = run([sys.executable, "scripts/check-project-readiness.py"], cwd=project)
        if initial_readiness.returncode != 1:
            print("untouched Copier output must fail readiness", file=sys.stderr)
            return 1
        project_git = ["git", "-C", str(project)]
        for args in (("init", "--initial-branch=main"), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Copier Test"), ("add", "."), ("commit", "-m", "generated project")):
            run(project_git + list(args))
        (project / "docs/prd.md").write_text(VALID_PRD, encoding="utf-8")
        (project / "README.md").write_text(VALID_README, encoding="utf-8")
        project_hook = project / "scripts/validate-project.py"
        project_hook.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        project_hook.chmod(project_hook.stat().st_mode | 0o100)
        configured = run([sys.executable, "scripts/validate-repository.py"], cwd=project)
        if configured.returncode:
            print(configured.stderr, file=sys.stderr)
            return configured.returncode
        shutil.rmtree(project / "scripts/__pycache__", ignore_errors=True)
        with (source / "NOTICE.md").open("a", encoding="utf-8") as handle:
            handle.write("\nCopier smoke-test marker.\n")
        source_hook = source / "scripts/validate-project.py"
        with source_hook.open("a", encoding="utf-8") as handle:
            handle.write("\n# template hook update\n")
        run(git + ["add", "NOTICE.md", "scripts/validate-project.py"])
        run(git + ["commit", "-m", "template v0.2.0"])
        run(git + ["tag", "v0.2.0"])
        with (project / "README.md").open("a", encoding="utf-8") as handle:
            handle.write("\nLocal project customization.\n")
        with project_hook.open("a", encoding="utf-8") as handle:
            handle.write("\n# local hook customization\n")
        expected_hook_text = project_hook.read_text(encoding="utf-8")
        run(project_git + ["add", "README.md", "docs/prd.md", "scripts/validate-project.py"])
        run(project_git + ["commit", "-m", "project customization"])
        result = run(command + ["update", "--vcs-ref", "v0.2.0", "--defaults"], cwd=project)
        hook_text = project_hook.read_text(encoding="utf-8")
        conflict_evidence = any(project.glob("**/*.rej")) or any(project.glob("**/*.conflict")) or "<<<<<<<" in hook_text
        if result.returncode and not conflict_evidence:
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
        if hook_text != expected_hook_text or "Copier smoke-test marker." not in (project / "NOTICE.md").read_text(encoding="utf-8") or "Local project customization." not in (project / "README.md").read_text(encoding="utf-8"):
            print(result.stderr, file=sys.stderr)
            return 1
    print("copier contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
