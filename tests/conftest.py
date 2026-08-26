"""Shared pytest configuration for the test suite."""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.factory import (
    SnapshotConfig,
    build_snapshot_project,
    copy_tree,
    pristine_snapshot,
    seed_repo,
    write_answer_bundle,
)
from tests.git_config import configure_deterministic_git_environment

type BundleOptions = dict[str, dict[str, str | bool]]
type RepoFiles = dict[str, str | bytes]

_MakeBundle = Callable[
    [bool, Path, str, list[str] | None, BundleOptions | None],
    str,
]

_MakeSeedRepo = Callable[
    [RepoFiles, str],
    str,
]


@pytest.fixture(scope="session", autouse=True)
def deterministic_git_env() -> None:
    """Disable detached Git maintenance in fixture repositories.

    On this btrfs checkout, detached Git auto-maintenance children survived the
    synchronous Git subprocesses used by the fixtures and wrote into their
    ``.git`` directories during teardown. An audit-hook probe found no
    in-process teardown writes; a flow probe failed 15 of 80 baseline
    iterations, while all 80 passed with these settings injected. The
    maintenance injection uses the same environment mechanism as this fixture.
    """
    configure_deterministic_git_environment()


@pytest.fixture(scope="session")
def pristine_source() -> str:
    """Return the path to the per-worker pristine source snapshot.

    Delegates to ``factory.pristine_snapshot()`` which builds a copy of the
    tracked source once per process and caches it via ``lru_cache(1)``. Under
    xdist each worker builds its own copy (~15ms).
    """
    return str(pristine_snapshot())


@pytest.fixture
def scaffolded_project(tmp_path: Path, pristine_source: str) -> str:
    """Build a default-config snapshot project in the test's tmp directory.

    Uses ``SnapshotConfig()`` (live template, no maintenance, no copier marker)
    and the session-scoped pristine source. Returns the project root path.
    """
    project = build_snapshot_project(
        tmp_path, SnapshotConfig(), pristine=pristine_snapshot()
    )
    return str(project.root)


@pytest.fixture
def make_bundle(tmp_path: Path) -> _MakeBundle:
    """Return a callable that writes an answer bundle into the test's tmp dir."""

    def _make_bundle(
        supplied: bool,
        record: Path,
        name: str = "bundle",
        capabilities: list[str] | None = None,
        capability_settings: BundleOptions | None = None,
    ) -> str:
        bundle = write_answer_bundle(
            tmp_path,
            supplied=supplied,
            record=record,
            name=name,
            capabilities=capabilities,
            capability_settings=capability_settings,
        )
        return str(bundle)

    return _make_bundle


@pytest.fixture
def make_seed_repo(tmp_path: Path) -> _MakeSeedRepo:
    """Return a callable that creates a committed git repo in the test's tmp dir."""

    def _make_seed_repo(
        files: RepoFiles,
        name: str = "repo",
    ) -> str:
        root = seed_repo(tmp_path, files, name=name)
        return str(root)

    return _make_seed_repo


@pytest.fixture
def materialized_tree(tmp_path: Path, pristine_source: str) -> str:
    """Return a copy of the pristine source tree with no git metadata.

    Uses ``factory.copy_tree`` with the canonical ignore set. The result is a
    plain directory tree under the test's tmp dir.
    """
    target = tmp_path / "materialized"
    copy_tree(pristine_snapshot(), target)
    return str(target)
