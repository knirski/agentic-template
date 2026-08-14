"""Shared entrypoint helpers for the repository's executable scripts."""

from __future__ import annotations

import sys


def reject_arguments(
    argv: list[str], prog: str, *, message: str | None = None
) -> int | None:
    """Reject unexpected arguments with a usage line; ``None`` means "run".

    ``message`` replaces the default ``usage: <prog>`` line for entrypoints
    whose contract names a bespoke diagnostic.
    """

    if not argv:
        return None
    print(message if message is not None else f"usage: {prog}", file=sys.stderr)
    return 2
