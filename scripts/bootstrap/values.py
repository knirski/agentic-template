"""Immutable primitive values and explicit v1 resource bounds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scripts.bootstrap.result import Err, Ok, Result


class LimitKind(StrEnum):
    PATHS = "paths"
    OPERATIONS = "operations"
    FILE_BYTES = "file_bytes"
    UNIQUE_BYTES = "unique_bytes"
    DIAGNOSTICS = "diagnostics"
    PATH_BYTES = "path_bytes"
    COMPONENT_BYTES = "component_bytes"
    COMPONENTS = "components"


class JournalPhase(StrEnum):
    PLANNED = "PLANNED"
    MUTATING = "MUTATING"
    RESTORED = "RESTORED"
    SEALED = "SEALED"


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_paths: int = 4096
    max_operations: int = 8192
    max_file_bytes: int = 16 * 1024 * 1024
    max_unique_bytes: int = 128 * 1024 * 1024
    max_diagnostics: int = 4096
    max_path_bytes: int = 1024
    max_component_bytes: int = 255
    max_components: int = 64


DEFAULT_LIMITS = ResourceLimits()


@dataclass(frozen=True, slots=True)
class LimitViolation:
    kind: LimitKind
    observed: int
    limit: int


def check_limit(
    kind: LimitKind, observed: int, limits: ResourceLimits = DEFAULT_LIMITS
) -> Result[int, LimitViolation]:
    """Check a complete observed count without accepting a partial value."""

    limits_by_kind = {
        LimitKind.PATHS: limits.max_paths,
        LimitKind.OPERATIONS: limits.max_operations,
        LimitKind.FILE_BYTES: limits.max_file_bytes,
        LimitKind.UNIQUE_BYTES: limits.max_unique_bytes,
        LimitKind.DIAGNOSTICS: limits.max_diagnostics,
        LimitKind.PATH_BYTES: limits.max_path_bytes,
        LimitKind.COMPONENT_BYTES: limits.max_component_bytes,
        LimitKind.COMPONENTS: limits.max_components,
    }
    limit = limits_by_kind[kind]
    if observed < 0 or observed > limit:
        return Err(LimitViolation(kind=kind, observed=observed, limit=limit))
    return Ok(observed)


def freeze(value: object) -> object:
    """Convert supported decoded containers into recursively immutable values."""

    if value is None or isinstance(value, (str, bytes, bool, int)):
        return value
    if isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
        return tuple(freeze(item) for item in items)
    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(freeze(item) for item in items)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in mapping):
            raise TypeError("frozen mappings require string keys")
        string_mapping = cast(dict[str, object], mapping)
        return tuple(
            (key, freeze(string_mapping[key])) for key in sorted(string_mapping)
        )
    if isinstance(value, (set, frozenset)):
        items = cast(set[object] | frozenset[object], value)
        return frozenset(freeze(item) for item in items)
    raise TypeError(f"unsupported mutable or shell value: {type(value).__name__}")
