"""Pure generated-project dependency metadata and ``pyproject.toml`` rendering.

Capability definitions declare non-secret runtime dependencies, a supported
Python range, and a uv invocation.  This module validates that metadata with
closed grammars, derives the effective dependency table and Python range for a
capability selection, and renders the bootstrap-managed generated
``pyproject.toml``.  Bootstrap never resolves, locks, or installs packages: a
generated project's adopter-facing next action after installation is ``uv lock``
followed by ``uv sync``, and the source repository's own ``pyproject.toml`` and
``uv.lock`` remain source-only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from scripts.bootstrap.result import Err, Ok, Result

# The bootstrap engine baseline: the generated project runs the template-owned
# validators, whose core uses pydantic and the render boundary's YAML scalar
# encoder uses PyYAML.  These are always present in the generated
# ``pyproject.toml``; selected capabilities add their own declarations.
BASELINE_RUNTIME_DEPENDENCIES: Final[tuple[str, ...]] = ("pydantic>=2", "pyyaml>=6.0.3")
BASELINE_PYTHON_RANGE: Final[str] = ">=3.14"
GENERATED_PYPROJECT_PATH: Final[str] = "pyproject.toml"
GENERATED_PYPROJECT_VERSION: Final[str] = "0.1.0"

_VERSION_PART = r"\d+(?:\.\d+){0,3}"
_COMPARATOR = r"(?:>=|<=|>|<)"
# One optional comparator clause; the closed v1 grammar has no equality clauses,
# so the effective range intersection stays a simple lower/upper bound meet.
_CLAUSE = re.compile(rf"(?P<op>{_COMPARATOR})\s*(?P<version>{_VERSION_PART})")
_DEPENDENCY_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    + rf"\s*(?P<spec>{_COMPARATOR}\s*{_VERSION_PART})?$"
)
_PYTHON_RANGE_PATTERN = re.compile(
    rf"^(?:{_COMPARATOR}\s*{_VERSION_PART})(?:,\s*{_COMPARATOR}\s*{_VERSION_PART})*$"
)
_INVOCATION_PATTERN = re.compile(r"^(?:uv|uvx)(?: (?!\.{1,2}$)[A-Za-z0-9._/-]+)+$")
# PEP 503-style separator collapsing for the dependency dedup key.
_NAME_SEPARATORS = re.compile(r"[-_.]+")

# The declaration surface every capability definition (catalog and render
# boundary) exposes to the effective-dependency derivation.
RUNTIME_DEPENDENCY_MAX_LENGTH: Final[int] = 128
PYTHON_RANGE_MAX_LENGTH: Final[int] = 128
INVOCATION_MAX_LENGTH: Final[int] = 128


class DependencyErrorKind(StrEnum):
    INVALID_DEPENDENCY = "invalid_dependency"
    INVALID_PYTHON_RANGE = "invalid_python_range"
    INCOMPATIBLE_PYTHON_RANGE = "incompatible_python_range"
    INVALID_INVOCATION = "invalid_invocation"
    UNKNOWN_CAPABILITY = "unknown_capability"


@dataclass(frozen=True, slots=True)
class DependencyError:
    kind: DependencyErrorKind
    subject: str = ""


class RuntimeDependencySource(Protocol):
    """The dependency-metadata surface shared by catalog and render definitions."""

    runtime_dependencies: tuple[str, ...]
    supported_python: str
    invocation: str | None


def _parse_version(value: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in value.split("."))
    # Normalize trailing zero components so comparisons are arity-independent:
    # (3, 14) and (3, 14, 0) are the same PEP 440 version.
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def _format_version(value: tuple[int, ...]) -> str:
    parts = list(value)
    while len(parts) > 1 and parts[-1] == 0:
        del parts[-1]
    return ".".join(str(part) for part in parts)


def _normalize_dependency(value: str) -> str:
    match = _DEPENDENCY_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(value)
    name = match.group("name")
    spec = match.group("spec")
    if spec is None:
        return name
    clause = _CLAUSE.fullmatch(spec)
    if clause is None:  # pragma: no cover - the pattern implies the clause grammar
        raise ValueError(value)
    return f"{name}{clause.group('op')}{_format_version(_parse_version(clause.group('version')))}"


def _parse_python_range(
    value: str,
) -> Result[tuple[tuple[str, tuple[int, ...]], ...], DependencyError]:
    if (
        len(value) > PYTHON_RANGE_MAX_LENGTH
        or _PYTHON_RANGE_PATTERN.fullmatch(value) is None
    ):
        return Err(DependencyError(DependencyErrorKind.INVALID_PYTHON_RANGE, value))
    clauses: list[tuple[str, tuple[int, ...]]] = []
    for raw in value.split(","):
        clause = _CLAUSE.fullmatch(raw.strip())
        if clause is None:  # pragma: no cover - the pattern implies the clause grammar
            return Err(DependencyError(DependencyErrorKind.INVALID_PYTHON_RANGE, value))
        clauses.append((clause.group("op"), _parse_version(clause.group("version"))))
    # Canonical order: lower bounds first by version, then upper bounds by
    # version; at an equal version a strict comparator sorts before its
    # non-strict counterpart so the meet's tiebreaker stays deterministic.
    clauses.sort(
        key=lambda clause: (
            0 if clause[0] in (">=", ">") else 1,
            clause[1],
            clause[0] not in (">", "<"),
        )
    )
    return Ok(tuple(clauses))


def validate_runtime_dependency(value: str) -> Result[str, DependencyError]:
    """Validate one runtime dependency declaration and return its canonical form."""
    if len(value) > RUNTIME_DEPENDENCY_MAX_LENGTH:
        return Err(DependencyError(DependencyErrorKind.INVALID_DEPENDENCY, value))
    try:
        return Ok(_normalize_dependency(value))
    except ValueError:
        return Err(DependencyError(DependencyErrorKind.INVALID_DEPENDENCY, value))


def validate_supported_python(value: str) -> Result[str, DependencyError]:
    """Validate a supported-Python specifier and return its canonical form."""
    match _parse_python_range(value):
        case Err(error):
            return Err(error)
        case Ok(clauses):
            pass
    return Ok(
        ",".join(
            f"{operator}{_format_version(version)}" for operator, version in clauses
        )
    )


def validate_invocation(value: str | None) -> Result[str | None, DependencyError]:
    """Validate a uv invocation declaration; ``None`` means the capability has none."""
    if value is None:
        return Ok(None)
    if (
        len(value) > INVOCATION_MAX_LENGTH
        or _INVOCATION_PATTERN.fullmatch(value) is None
    ):
        return Err(DependencyError(DependencyErrorKind.INVALID_INVOCATION, value))
    return Ok(value)


def validate_dependency_metadata(
    runtime_dependencies: tuple[str, ...],
    supported_python: str,
    invocation: str | None,
) -> None:
    """Validate capability dependency metadata, raising ValueError on the first failure.

    Shared by the catalog and render-boundary ``CapabilityDefinition`` models so
    the two surfaces cannot drift.
    """
    for value in runtime_dependencies:
        match validate_runtime_dependency(value):
            case Ok(_):
                pass
            case Err(error):
                raise ValueError(f"invalid runtime dependency: {error.subject}")
    match validate_supported_python(supported_python):
        case Ok(_):
            pass
        case Err(error):
            raise ValueError(f"invalid supported Python range: {error.subject}")
    match validate_invocation(invocation):
        case Ok(_):
            pass
        case Err(error):
            raise ValueError(f"invalid invocation: {error.subject}")


def _dependency_key(value: str) -> str:
    """Return the PEP 503-style dedup key for a canonical dependency declaration."""
    match = _DEPENDENCY_PATTERN.fullmatch(value)
    if match is None:  # pragma: no cover - canonical values always match the grammar
        return value
    return _NAME_SEPARATORS.sub("-", match.group("name")).lower()


def effective_dependencies(
    capability_ids: tuple[str, ...],
    catalog: Mapping[str, RuntimeDependencySource],
) -> Result[tuple[str, ...], DependencyError]:
    """Return the ordered, deduplicated runtime dependency table for a selection.

    The baseline engine dependencies come first; selected capability
    declarations follow in capability order.  Each declaration is emitted in
    its canonical form and deduplicated by its normalized distribution name,
    keeping the first declared form.
    """
    result: list[str] = []
    seen: set[str] = set()
    for value in BASELINE_RUNTIME_DEPENDENCIES:
        result.append(value)
        seen.add(_dependency_key(value))
    for capability_id in capability_ids:
        definition = catalog.get(capability_id)
        if definition is None:
            return Err(
                DependencyError(DependencyErrorKind.UNKNOWN_CAPABILITY, capability_id)
            )
        for value in definition.runtime_dependencies:
            match validate_runtime_dependency(value):
                case Ok(canonical):
                    key = _dependency_key(canonical)
                    if key not in seen:
                        seen.add(key)
                        result.append(canonical)
                case Err(error):
                    return Err(error)
    return Ok(tuple(result))


def effective_python_range(
    capability_ids: tuple[str, ...],
    catalog: Mapping[str, RuntimeDependencySource],
) -> Result[str, DependencyError]:
    """Return the intersection of the baseline and selected capability ranges.

    The generated ``pyproject.toml``'s ``requires-python`` is the narrowest
    range every selected capability supports; an empty intersection is an
    incompatible selection and names the capability that introduced it.
    """
    lower: tuple[tuple[int, ...], bool] | None = None
    upper: tuple[tuple[int, ...], bool] | None = None
    sources: list[tuple[str, str]] = [(BASELINE_PYTHON_RANGE, "baseline")]
    for capability_id in capability_ids:
        definition = catalog.get(capability_id)
        if definition is None:
            return Err(
                DependencyError(DependencyErrorKind.UNKNOWN_CAPABILITY, capability_id)
            )
        sources.append((definition.supported_python, capability_id))
    for value, owner in sources:
        match _parse_python_range(value):
            case Err(error):
                return Err(error)
            case Ok(clauses):
                pass
        for operator, version in clauses:
            strict = operator not in (">=", "<=")
            if operator in (">=", ">"):
                if (
                    lower is None
                    or version > lower[0]
                    or (version == lower[0] and strict and not lower[1])
                ):
                    lower = (version, strict)
            else:
                if (
                    upper is None
                    or version < upper[0]
                    or (version == upper[0] and strict and not upper[1])
                ):
                    upper = (version, strict)
        if (
            lower is not None
            and upper is not None
            and (
                lower[0] > upper[0] or (lower[0] == upper[0] and (lower[1] or upper[1]))
            )
        ):
            return Err(
                DependencyError(DependencyErrorKind.INCOMPATIBLE_PYTHON_RANGE, owner)
            )
    rendered: list[str] = []
    if lower is not None:
        rendered.append((">" if lower[1] else ">=") + _format_version(lower[0]))
    if upper is not None:
        rendered.append(("<" if upper[1] else "<=") + _format_version(upper[0]))
    return Ok(",".join(rendered))


def render_generated_pyproject(
    name: str,
    python_range: str,
    dependencies: tuple[str, ...],
) -> bytes:
    """Render the deterministic bootstrap-managed generated ``pyproject.toml``."""
    lines = [
        "[project]",
        f'name = "{name}"',
        f'version = "{GENERATED_PYPROJECT_VERSION}"',
        f'requires-python = "{python_range}"',
    ]
    if dependencies:
        lines.append("dependencies = [")
        lines.extend(f'    "{dependency}",' for dependency in dependencies)
        lines.append("]")
    return "\n".join(lines).encode("utf-8") + b"\n"
