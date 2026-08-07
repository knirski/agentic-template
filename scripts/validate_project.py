#!/usr/bin/env python3
"""Adopter-owned project validation hook.

Replace this file with the generated project's stack-specific validation commands.
"""

from __future__ import annotations

import sys


SENTINEL = "agentic-template:unconfigured:validate-project"


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_project.py", file=sys.stderr)
        return 2
    print(
        f"{SENTINEL}: replace this hook with the project's formatting, linting, tests, and build checks",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
