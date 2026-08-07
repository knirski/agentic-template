#!/usr/bin/env python3
"""Run the generated-project validation stages in a deterministic order."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagePassed:
    exit_code: int = 0


@dataclass(frozen=True)
class _ValidationState:
    next_stage: str | None


@dataclass(frozen=True)
class ValidationProgram:
    stages: tuple[str, ...]

    def start(self) -> _ValidationState:
        return _ValidationState(self.stages[0] if self.stages else None)

    def advance(
        self, state: _ValidationState, _observation: StagePassed
    ) -> _ValidationState:
        index = (
            self.stages.index(state.next_stage) + 1
            if state.next_stage
            else len(self.stages)
        )
        return _ValidationState(
            self.stages[index] if index < len(self.stages) else None
        )


ROOT = Path(__file__).resolve().parent.parent
STAGES = (
    ("template contract", ROOT / "scripts/validate_template.py", True),
    ("project readiness", ROOT / "scripts/check_project_readiness.py", True),
    ("project validation", ROOT / "scripts/validate_project.py", False),
)


def stage_command(script: Path, use_python: bool, python_executable: str) -> list[str]:
    return [python_executable, str(script)] if use_python else [str(script)]


def stage_failed(returncode: int) -> bool:
    return returncode != 0


def validation_program() -> ValidationProgram:
    return ValidationProgram(tuple(label for label, _, _ in STAGES))


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_repository.py", file=sys.stderr)
        return 2
    program = validation_program()
    state = program.start()
    for label, script, use_python in STAGES:
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
        if stage_failed(result.returncode):
            return result.returncode
        state = program.advance(state, StagePassed())
        if state.next_stage is None:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
