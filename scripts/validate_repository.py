#!/usr/bin/env python3
"""Run the generated-project validation stages in a deterministic order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.validation_program import (  # noqa: E402
    StageFailed,
    StagePassed,
    ValidationProgram,
    stage_failed,
)

STAGES = (
    ("template contract", ROOT / "scripts/validate_template.py", True),
    ("project readiness", ROOT / "scripts/check_project_readiness.py", True),
    ("project validation", ROOT / "scripts/validate_project.py", False),
)


def stage_command(script: Path, use_python: bool, python_executable: str) -> list[str]:
    return [python_executable, str(script)] if use_python else [str(script)]


def validation_program() -> ValidationProgram:
    return ValidationProgram(tuple(label for label, _, _ in STAGES))


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_repository.py", file=sys.stderr)
        return 2
    program = validation_program()
    state = program.start()
    stage_by_label = {
        label: (script, use_python) for label, script, use_python in STAGES
    }
    while state.next_stage is not None:
        label = state.next_stage
        script, use_python = stage_by_label[label]
        print(f"==> {label}", flush=True)
        try:
            command = stage_command(script, use_python, sys.executable)
            result = subprocess.run(command, cwd=ROOT, check=False)
        except OSError as exc:
            print(
                f"REPOSITORY_VALIDATION_INTERNAL_ERROR: {script.relative_to(ROOT)}: {exc}; next: restore the validation script",
                file=sys.stderr,
            )
            return 2
        observation = (
            StagePassed(result.returncode)
            if not stage_failed(result.returncode)
            else StageFailed(result.returncode)
        )
        state = program.advance(state, observation)
    return 0 if state.exit_code is None else state.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
