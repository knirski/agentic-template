"""Pure stage-folding algebra for aggregate validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StagePassed:
    exit_code: int = 0


@dataclass(frozen=True, slots=True)
class StageFailed:
    exit_code: int


StageObservation = StagePassed | StageFailed


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
        if isinstance(observation, StageFailed):
            return ValidationState(None, observation.exit_code, observations)
        index = (
            len(observations) if state.next_stage in self.stages else len(self.stages)
        )
        next_stage = self.stages[index] if index < len(self.stages) else None
        return ValidationState(
            next_stage, 0 if next_stage is None else None, observations
        )


def stage_failed(observation: StageObservation) -> bool:
    return isinstance(observation, StageFailed)
