#!/usr/bin/env python3
"""Regenerate the cleanup inventory from the tracked source.

Canonical writer for ``.agentic-template/maintenance-artifacts.json``: the
inventory must describe the tracked source exactly, so it is recomputed
through the readiness fixture of truth (the same function the fixture suites
assert against) and written with the canonical formatting. Release tooling
runs this after version bumps touch inventory-tracked files, keeping main
green without a manual refresh commit.

Trees without the inventory machinery -- generated projects, which receive
the shared release configuration but neither ``tests/`` nor the inventory --
skip with a notice instead of failing the release.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO_ROOT))

INVENTORY_PATH = REPO_ROOT / ".agentic-template" / "maintenance-artifacts.json"
READINESS_MODULE = REPO_ROOT / "tests" / "test_github_template_readiness.py"


def main() -> int:
    """Rewrite the inventory in place, or skip when the machinery is absent."""
    if not INVENTORY_PATH.is_file() or not READINESS_MODULE.is_file():
        print(
            "cleanup-inventory machinery absent; skipping regeneration",
            file=sys.stderr,
        )
        return 0
    from tests.test_github_template_readiness import expected_cleanup_inventory

    # The fixture of truth hashes the working tree via git relative to the
    # process working directory, so anchor it to this repository regardless
    # of where the release hook or a developer invoked the script.
    os.chdir(REPO_ROOT)
    _ = INVENTORY_PATH.write_text(
        json.dumps(expected_cleanup_inventory(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
