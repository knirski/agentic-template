#!/usr/bin/env python3
"""Deterministic capability-profile-driven project bootstrap CLI.

This entry point is a thin adapter: parsing, observation, decisions, the
transaction interpreter, recovery, and presentation all live in
``scripts/bootstrap/cli.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
