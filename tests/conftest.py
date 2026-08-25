"""Shared pytest configuration for the test suite."""

import os

import pytest


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
    os.environ.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "gc.auto",
            "GIT_CONFIG_VALUE_0": "0",
            "GIT_CONFIG_KEY_1": "gc.autoDetach",
            "GIT_CONFIG_VALUE_1": "false",
            "GIT_CONFIG_KEY_2": "maintenance.auto",
            "GIT_CONFIG_VALUE_2": "false",
        }
    )
