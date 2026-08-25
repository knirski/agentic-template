"""Shared Git configuration for deterministic fixture repositories."""

from __future__ import annotations

import os
from collections.abc import Mapping

_DETERMINISTIC_GIT_ENV: dict[str, str] = {
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


def configure_deterministic_git_environment() -> None:
    """Disable detached Git maintenance in the current test process."""
    os.environ.update(_DETERMINISTIC_GIT_ENV)


def deterministic_git_environment(
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an inherited environment with detached Git maintenance disabled."""
    environment = os.environ.copy()
    environment.update(_DETERMINISTIC_GIT_ENV)
    if overrides is not None:
        environment.update(overrides)
    return environment
