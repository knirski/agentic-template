"""Framework-independent builders shared by the test-suite fixture layers."""

from __future__ import annotations

import atexit
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from tests.fixtures import tracked_files

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
