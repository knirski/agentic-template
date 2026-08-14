"""Small immutable result values used by the bootstrap functional core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[ValueT]:
    value: ValueT


@dataclass(frozen=True, slots=True)
class Err[ErrorT]:
    error: ErrorT


type Result[ValueT, ErrorT] = Ok[ValueT] | Err[ErrorT]
