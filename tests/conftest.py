"""Shared pytest configuration for the test suite."""

import pytest

from tests.git_config import configure_deterministic_git_environment


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
