"""Shared fixture helpers for the generation-path end-to-end suites.

The GitHub-snapshot suite (test_github_template_readiness.py) and the Copier
suite (test_copier_bootstrap.py) both build a tracked-source copy, overlay the
seed-once scaffold, write an answer bundle, and drive the bootstrap CLI.  The
helpers live here with public names so neither suite imports the other's
internals; the CLI suite keeps its own synthetic fixtures.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PRD = """# Product
## Problem
Problem.
## Goals
Goals.
## Non-goals
No.
## Users and workflows
Users.
## Requirements
### REQ-001: Works
Acceptance body.
## Quality attributes
Reliable.
## Release criteria
Green.
## Open questions
None.
"""
README = """# Product
## Setup
Setup.
## Validation
Run `python3 scripts/validate_repository.py`.
"""
SUPPLIED_SECURITY = "# Security\n\nReport privately.\n"
SUPPLIED_CONTRIBUTING = "# Contributing\n\nWelcome.\n"
SCAFFOLD_CONTRIBUTING = (
    "# Contributing\n\n<!-- agentic-template:placeholder:contributing -->\n"
)
SCAFFOLD_SECURITY = (
    "# Security Policy\n\n<!-- agentic-template:placeholder:security -->\n"
)
SCAFFOLD_HOOK_TEMPLATE = (
    "#!/bin/sh\n"
    "# agentic-template:unconfigured:validate-project\n"
    "echo run >> {record}\n"
    "exit 0\n"
)

# The finite source-only set declared by .agentic-template/source-ownership.json
# and removed by an initial GitHub snapshot apply.
CLEANUP_PATHS = (
    ".github/workflows/copier-smoke.yml",
    ".github/workflows/mutation.yml",
    ".github/workflows/template-ci.yml",
    ".python-version",
    "docs/specs",
    "flake.lock",
    "flake.nix",
    "pyproject.toml",
    "tests",
    "uv.lock",
)


def run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=env, text=True, capture_output=True, check=False
    )


def tracked_files(root: Path) -> list[str]:
    """List the repository's tracked files (what a fixture copy must contain)."""
    return [
        entry
        for entry in run(["git", "-C", str(root), "ls-files", "-z"]).stdout.split("\0")
        if entry
    ]


def copy_tracked(source_root: Path, target: Path) -> None:
    """Copy every tracked file of ``source_root`` into ``target`` with modes."""
    target.mkdir()
    for relative in sorted(tracked_files(source_root)):
        source = source_root / relative
        if not source.is_file():
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, destination)


def scaffold_hook(record: Path) -> str:
    """The seed-once placeholder hook, recording executions to ``record``."""
    return SCAFFOLD_HOOK_TEMPLATE.format(record=record)


def write_bundle(
    parent: Path,
    *,
    supplied: bool,
    record: Path,
    name: str = "bundle",
    capabilities: tuple[str, ...] | None = None,
    capability_settings: dict[str, dict[str, str | bool]] | None = None,
) -> Path:
    """Write a bootstrap answer bundle: supplied content or scaffold modes.

    ``capabilities`` writes a custom profile selection and
    ``capability_settings`` its settings; both omitted, the bundle is the
    portable profile (no capabilities) used by the generation-path suites.
    """
    bundle = parent / name
    bundle.mkdir()
    content_paths = {
        "prd": "content/prd.md",
        "readme": "content/readme.md",
        "validation_hook": "content/validate-project",
        "security_policy": "content/security.md",
        "contributing": "content/contributing.md",
    }
    if supplied:
        content_dir = bundle / "content"
        content_dir.mkdir()
        _ = (content_dir / "prd.md").write_text(PRD, encoding="utf-8")
        _ = (content_dir / "readme.md").write_text(README, encoding="utf-8")
        _ = (content_dir / "security.md").write_text(
            SUPPLIED_SECURITY, encoding="utf-8"
        )
        _ = (content_dir / "contributing.md").write_text(
            SUPPLIED_CONTRIBUTING, encoding="utf-8"
        )
        hook = content_dir / "validate-project"
        _ = hook.write_text(
            "#!/bin/sh\necho run >> " + str(record) + "\nexit 0\n", encoding="utf-8"
        )
        hook.chmod(0o755)
    content: dict[str, object] = {}
    for slot, relative in content_paths.items():
        content[slot] = (
            {"mode": "scaffold"} if not supplied else {"mode": "file", "path": relative}
        )
    profile: dict[str, object] = {"id": "portable"}
    if capabilities is not None:
        profile = {"id": "custom", "capabilities": list(capabilities)}
    document = {
        "schema_version": 1,
        "project": {"name": "example", "default_branch": "main"},
        "profile": profile,
        "content": content,
        "licensing": {"mode": "retain-apache-2.0"},
        "capability_settings": capability_settings or {},
    }
    _ = (bundle / "bootstrap.json").write_text(
        json.dumps(document, sort_keys=True), encoding="utf-8"
    )
    return bundle
