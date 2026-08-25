"""Framework-independent builders shared by the test-suite fixture layers."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, assert_never

from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.scaffold import (
    PROJECT_VALIDATION_SCAFFOLD,
    SCAFFOLD_SOURCE_PATHS,
    cleanup_directory_digest,
)
from tests.fixtures import (
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    scaffold_hook,
    tracked_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

type TemplateSource = Literal["live", "synthetic"]

CANONICAL_IGNORE = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class SnapshotConfig:
    """Configuration for a snapshot project built by the fixture engine."""

    template: TemplateSource = "live"
    maintenance: bool = False
    copier_marker: bool = False


@dataclass(frozen=True)
class SnapshotProject:
    """The reusable handles exposed by a materialized snapshot project."""

    root: Path
    hook_runs: Path
    template_root: Path | None

    def run_count(self) -> int:
        """Return the number of recorded validation-hook executions."""

        return len(self.hook_runs.read_text(encoding="utf-8").splitlines())


_SYNTHETIC_SCAFFOLD_README = "# Placeholder\n\n<!-- rygor:placeholder:readme -->\n"
_SYNTHETIC_SCAFFOLD_PRD = "# Product\n\n<!-- rygor:placeholder:prd -->\n"
_SYNTHETIC_SCAFFOLD_SECURITY = "# Security\n\n<!-- rygor:placeholder:security -->\n"
_SYNTHETIC_SCAFFOLD_CONTRIBUTING = (
    "# Contributing\n\n"
    "<!-- rygor:placeholder:contributing -->\n\n"
    "## Running tests\n\n"
    "Run the test suite serially with `uv run pytest`. For faster feedback on a multi-core machine,\n"
    "run `uv run pytest -n auto` to distribute tests across available workers.\n"
)
_SYNTHETIC_SCAFFOLD_HOOK = (
    "#!/bin/sh\n# rygor:unconfigured:validate-project\necho unconfigured\nexit 0\n"
)
_SYNTHETIC_OVERLAY_PATHS = (
    "README.md",
    "docs/prd.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "scripts/validate-project",
    "LICENSE",
    "NOTICE.md",
    "LICENSES/Apache-2.0.txt",
    "source-contract.txt",
    ".github/workflows/project-validation.yml",
)


def _write_synthetic_template(parent: Path, hook_runs: Path) -> Path:
    template = parent / "template"
    template.mkdir()
    for relative, content, mode in (
        ("README.md", _SYNTHETIC_SCAFFOLD_README, 0o644),
        ("docs/prd.md", _SYNTHETIC_SCAFFOLD_PRD, 0o644),
        ("SECURITY.md", _SYNTHETIC_SCAFFOLD_SECURITY, 0o644),
        ("CONTRIBUTING.md", _SYNTHETIC_SCAFFOLD_CONTRIBUTING, 0o644),
        ("scripts/validate-project", _SYNTHETIC_SCAFFOLD_HOOK, 0o755),
        ("LICENSE", "Apache-2.0\n", 0o644),
        ("NOTICE.md", "Notice.\n", 0o644),
        ("LICENSES/Apache-2.0.txt", "Apache text.\n", 0o644),
        ("source-contract.txt", "template source.\n", 0o644),
    ):
        path = template / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8")
        path.chmod(mode)

    project_validation = template / ".github/workflows/project-validation.yml"
    project_validation.parent.mkdir(parents=True, exist_ok=True)
    _ = project_validation.write_bytes(PROJECT_VALIDATION_SCAFFOLD)
    project_validation.chmod(0o644)
    for installed, source in SCAFFOLD_SOURCE_PATHS.items():
        source_path = template / source.value
        source_path.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(template / installed.value, source_path)

    ownership = template / ".rygor/source-ownership.json"
    ownership.parent.mkdir(parents=True, exist_ok=True)
    _ = ownership.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lifecycle_paths": ["source-contract.txt"],
                "snapshot_cleanup_paths": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    hook = template / "scripts/validate-project"
    _ = hook.write_text(
        "#!/bin/sh\n"
        + "# rygor:unconfigured:validate-project\n"
        + "echo run >> "
        + str(hook_runs)
        + "\nexit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    source = (
        template / SCAFFOLD_SOURCE_PATHS[RepoPath("scripts/validate-project")].value
    )
    _ = shutil.copy2(hook, source)
    return template


def _overlay_live_snapshot(project: Path, hook_runs: Path) -> None:
    hook = project / "scripts/validate-project"
    _ = hook.write_text(scaffold_hook(hook_runs), encoding="utf-8")
    hook.chmod(0o755)
    fragment = project / "scripts/bootstrap/fragments/scaffolds/validate-project"
    _ = fragment.write_text(scaffold_hook(hook_runs), encoding="utf-8")
    _ = (project / "CONTRIBUTING.md").write_text(
        SCAFFOLD_CONTRIBUTING, encoding="utf-8"
    )
    _ = (project / "SECURITY.md").write_text(SCAFFOLD_SECURITY, encoding="utf-8")


def _overlay_synthetic_snapshot(project: Path, template: Path) -> None:
    for relative in _SYNTHETIC_OVERLAY_PATHS:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(template / relative, target)
    _ = shutil.copy2(
        template / ".rygor/source-ownership.json",
        project / ".rygor/source-ownership.json",
    )


def _directory_digest(project: Path) -> str:
    files: list[tuple[RepoPath, bytes, int]] = []
    directories: list[tuple[RepoPath, int]] = []
    root = project / "tests"
    for current, dirs, names in os.walk(root):
        for name in sorted(names):
            path = Path(current) / name
            relative = RepoPath(path.relative_to(project).as_posix())
            files.append(
                (relative, path.read_bytes(), 0o644 | (path.stat().st_mode & 0o100))
            )
        for name in sorted(dirs):
            path = Path(current) / name
            relative = RepoPath(path.relative_to(project).as_posix())
            directories.append((relative, 0o755))
    return cleanup_directory_digest(
        RepoPath("tests"), files=tuple(files), directories=tuple(directories)
    )


def _maintenance_inventory(project: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "path": "tests",
                "kind": "directory",
                "sha256": _directory_digest(project),
            }
        ],
    }


def build_snapshot_project(
    parent: Path,
    config: SnapshotConfig,
    *,
    pristine: Path,
) -> SnapshotProject:
    """Build one seeded snapshot project from a pristine source tree."""

    project = parent / "project"
    _ = shutil.copytree(pristine, project)
    hook_runs = parent / "hook-runs"
    _ = hook_runs.write_text("", encoding="utf-8")
    template_root: Path | None = None

    match config.template:
        case "live":
            _overlay_live_snapshot(project, hook_runs)
        case "synthetic":
            template_root = _write_synthetic_template(parent, hook_runs)
            _overlay_synthetic_snapshot(project, template_root)
        case _:
            assert_never(config.template)

    git("init", "-q", "-b", "main", cwd=project)
    git("add", "-A", cwd=project)
    git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "-m",
        "scaffold",
        cwd=project,
    )

    if config.copier_marker:
        _ = (project / ".copier-answers.yml").write_text(
            "_commit: 0.1.0\n", encoding="utf-8"
        )
    if config.maintenance:
        ownership = project / ".rygor/source-ownership.json"
        _ = ownership.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "lifecycle_paths": [],
                    "snapshot_cleanup_paths": ["tests"],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        inventory = project / ".rygor/maintenance-artifacts.json"
        _ = inventory.write_text(
            json.dumps(_maintenance_inventory(project), sort_keys=True),
            encoding="utf-8",
        )

    return SnapshotProject(project, hook_runs, template_root)


def build_pristine_snapshot(*, root: Path, parent: Path) -> Path:
    """Copy the source file set into a pristine, metadata-free snapshot."""

    target = parent / "pristine"
    target.mkdir(parents=True, exist_ok=True)
    for relative in tracked_files(root):
        source = root / relative
        if not source.is_file():
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, destination)
    return target


@lru_cache(maxsize=1)
def pristine_snapshot(*, root: Path = REPO_ROOT) -> Path:
    """Return one process-local immutable-by-convention source snapshot."""

    parent = Path(tempfile.mkdtemp(prefix="agentic-template-pristine."))
    _ = atexit.register(shutil.rmtree, parent, ignore_errors=True)
    return build_pristine_snapshot(root=root, parent=parent)


def _ignore_names(names: list[str], ignored: frozenset[str]) -> set[str]:
    return set(names).intersection(ignored)


def copy_tree(
    source: Path,
    target: Path,
    *,
    ignore: frozenset[str] = CANONICAL_IGNORE,
) -> None:
    """Copy a tree while applying the repository's canonical fixture ignores."""

    _ = shutil.copytree(
        source,
        target,
        ignore=lambda _directory, names: _ignore_names(names, ignore),
    )


def git(*args: str, cwd: Path) -> None:
    """Run Git in ``cwd`` and raise with its captured stderr on failure."""

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        command = " ".join(("git", *args))
        raise RuntimeError(
            detail or f"{command} failed with exit code {result.returncode}"
        )
