"""Small immutable result algebra used by the bootstrap functional core."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

ValueT = TypeVar("ValueT")
MappedT = TypeVar("MappedT")
ErrorT = TypeVar("ErrorT")
MappedErrorT = TypeVar("MappedErrorT")


@dataclass(frozen=True, slots=True)
class Ok[ValueT]:
    value: ValueT

    def map(self, function: Callable[[ValueT], MappedT]) -> Ok[MappedT]:
        return Ok(function(self.value))

    def bind(
        self, function: Callable[[ValueT], Result[MappedT, ErrorT]]
    ) -> Result[MappedT, ErrorT]:
        return function(self.value)

    def map_error(self, function: Callable[[ErrorT], MappedErrorT]) -> Ok[ValueT]:
        del function
        return self


@dataclass(frozen=True, slots=True)
class Err[ErrorT]:
    error: ErrorT

    def map(self, function: Callable[[ValueT], MappedT]) -> Err[ErrorT]:
        del function
        return self

    def bind(
        self, function: Callable[[ValueT], Result[MappedT, ErrorT]]
    ) -> Err[ErrorT]:
        del function
        return self

    def map_error(
        self, function: Callable[[ErrorT], MappedErrorT]
    ) -> Err[MappedErrorT]:
        return Err(function(self.error))


type Result[ValueT, ErrorT] = Ok[ValueT] | Err[ErrorT]


def accumulate[ValueT, ErrorT](
    results: tuple[Result[ValueT, ErrorT], ...],
) -> Result[tuple[ValueT, ...], tuple[ErrorT, ...]]:
    """Collect independent errors while preserving successful values in input order."""

    values: list[ValueT] = []
    errors: list[ErrorT] = []
    for result in results:
        match result:
            case Ok():
                values.append(result.value)
            case Err():
                errors.append(result.error)
    if errors:
        return Err(tuple(errors))
    return Ok(tuple(values))
