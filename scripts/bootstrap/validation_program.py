"""Pure stage-folding algebra for aggregate validation."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from scripts.bootstrap.errors import ProcessError

STREAM_PREFIX_LIMIT = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CapturedStream:
    """A bounded, hashable description of one untrusted process stream."""

    total_bytes: int
    sha256: str
    prefix_base64: str
    truncated: bool

    @classmethod
    def from_bytes(
        cls, data: bytes, *, prefix_limit: int = STREAM_PREFIX_LIMIT
    ) -> CapturedStream:
        if prefix_limit < 0:
            raise ValueError("prefix_limit must be non-negative")
        prefix = data[:prefix_limit]
        return cls(
            total_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            prefix_base64=base64.b64encode(prefix).decode("ascii"),
            truncated=len(data) > len(prefix),
        )


@dataclass(frozen=True, slots=True)
class StageSignalled:
    """A child terminated by a POSIX signal."""

    signal: int
    stdout: CapturedStream | None = None
    stderr: CapturedStream | None = None


@dataclass(frozen=True, slots=True)
class StageLaunchFailed:
    """The stage process could not be launched."""

    error: ProcessError
    stdout: CapturedStream | None = None
    stderr: CapturedStream | None = None


@dataclass(frozen=True, slots=True)
class StagePassed:
    exit_code: int = 0
    stdout: CapturedStream | None = None
    stderr: CapturedStream | None = None


@dataclass(frozen=True, slots=True)
class StageFailed:
    exit_code: int
    stdout: CapturedStream | None = None
    stderr: CapturedStream | None = None


type StageObservation = StagePassed | StageFailed | StageSignalled | StageLaunchFailed


@dataclass(frozen=True, slots=True)
class ValidationState:
    next_stage: str | None
    exit_code: int | None
    observations: tuple[StageObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationProgram:
    stages: tuple[str, ...]

    def start(self) -> ValidationState:
        return ValidationState(self.stages[0] if self.stages else None, None)

    def advance(
        self, state: ValidationState, observation: StageObservation
    ) -> ValidationState:
        if state.next_stage is None:
            return state
        observations = (*state.observations, observation)
        if stage_failed(observation):
            return ValidationState(None, stage_exit_code(observation), observations)
        index = (
            len(observations) if state.next_stage in self.stages else len(self.stages)
        )
        next_stage = self.stages[index] if index < len(self.stages) else None
        return ValidationState(
            next_stage, 0 if next_stage is None else None, observations
        )


def stage_exit_code(observation: StageObservation) -> int:
    """Map one typed stage outcome to the aggregate process exit status."""

    match observation:
        case StagePassed(exit_code=exit_code) | StageFailed(exit_code=exit_code):
            return exit_code
        case StageSignalled(signal=signal):
            return min(255, 128 + max(signal, 0))
        case StageLaunchFailed():
            return 2


def stage_failed(observation: StageObservation | int) -> bool:
    match observation:
        case int():
            return observation != 0
        case StagePassed(exit_code=exit_code):
            return exit_code != 0
        case StageFailed() | StageSignalled() | StageLaunchFailed():
            return True
