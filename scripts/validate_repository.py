#!/usr/bin/env python3
"""Run the generated-project validation stages in a deterministic order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
STAGES = (
    ("template contract", ROOT / "scripts/validate_template.py", True),
    ("project readiness", ROOT / "scripts/check_project_readiness.py", True),
    ("project validation", ROOT / "scripts/validate_project.py", False),
)


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_repository.py", file=sys.stderr)
        return 2
    for label, script, use_python in STAGES:
        print(f"==> {label}", flush=True)
        try:
            command = [sys.executable, str(script)] if use_python else [str(script)]
            result = subprocess.run(command, cwd=ROOT, check=False)
        except OSError as exc:
            print(
                f"REPOSITORY_VALIDATION_INTERNAL_ERROR: {script.relative_to(ROOT)}: {exc}; next: restore the validation script",
                file=sys.stderr,
            )
            return 2
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
