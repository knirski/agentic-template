"""Immutable primitive values and explicit v1 resource bounds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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
        return tuple(freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("frozen mappings require string keys")
        return tuple((key, freeze(value[key])) for key in sorted(value))
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    raise TypeError(f"unsupported mutable or shell value: {type(value).__name__}")
