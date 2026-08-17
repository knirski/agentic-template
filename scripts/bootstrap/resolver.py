"""Pure profile, dependency, and normalized-setting resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import assert_never

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.catalog import CATALOG, CapabilityDefinition, SettingDefinition
from scripts.bootstrap.identity import tagged_digest
from scripts.bootstrap.profiles import PROFILE_CAPABILITIES
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.schemas import AdditionsInput, BootstrapBundle, SettingValue


class ResolutionErrorKind(StrEnum):
    UNKNOWN_CAPABILITY = "unknown_capability"
    UNKNOWN_PROFILE = "unknown_profile"
    DEPENDENCY_CYCLE = "dependency_cycle"
    DUPLICATE_ADDITION = "duplicate_addition"
    UNKNOWN_SETTING = "unknown_setting"
    MISSING_REQUIRED_SETTING = "missing_required_setting"
    UNDETERMINED_SETTING = "undetermined_setting"
    SECRET_SETTING = "secret_setting"
    TYPE_VIOLATION = "type_violation"
    ENUM_VIOLATION = "enum_violation"
    PATTERN_VIOLATION = "pattern_violation"
    UNSELECTED_SETTINGS = "unselected_settings"
    RECONFIGURE_SETTINGS = "reconfigure_settings"


@dataclass(frozen=True, slots=True)
class ResolutionFailure:
    kind: ResolutionErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedBundle:
    profile_id: str
    requested: tuple[str, ...]
    effective: tuple[str, ...]
    settings: Mapping[str, Mapping[str, SettingValue]]

    @property
    def settings_identity(self) -> str:
        return normalized_settings_identity(self.settings)


def _topological_order(
    capability_ids: set[str],
) -> Result[tuple[str, ...], ResolutionFailure]:
    result: list[str] = []
    remaining = set(capability_ids)
    while remaining:
        available = sorted(
            capability_id
            for capability_id in remaining
            if set(CATALOG[capability_id].dependencies).isdisjoint(remaining)
        )
        if not available:
            return Err(ResolutionFailure(ResolutionErrorKind.DEPENDENCY_CYCLE))
        result.extend(available)
        remaining.difference_update(available)
    return Ok(tuple(result))


def _closure(
    requested: tuple[str, ...], catalog: Mapping[str, CapabilityDefinition]
) -> Result[set[str], ResolutionFailure]:
    effective: set[str] = set()
    pending = list(requested)
    while pending:
        capability_id = pending.pop()
        if capability_id in effective:
            continue
        if capability_id not in catalog:
            return Err(
                ResolutionFailure(ResolutionErrorKind.UNKNOWN_CAPABILITY, capability_id)
            )
        effective.add(capability_id)
        pending.extend(catalog[capability_id].dependencies)
    return Ok(effective)


def _setting_value(
    definition: SettingDefinition,
    supplied: Mapping[str, SettingValue],
) -> Result[SettingValue, ResolutionFailure]:
    if definition.name in supplied:
        value = supplied[definition.name]
    elif definition.default is not None:
        value = definition.default
    elif definition.required:
        return Err(
            ResolutionFailure(
                ResolutionErrorKind.MISSING_REQUIRED_SETTING, definition.name
            )
        )
    else:
        return Err(
            ResolutionFailure(ResolutionErrorKind.UNDETERMINED_SETTING, definition.name)
        )
    if definition.secret:
        return Err(
            ResolutionFailure(ResolutionErrorKind.SECRET_SETTING, definition.name)
        )
    match definition.type:
        case "string":
            if not isinstance(value, str):
                return Err(
                    ResolutionFailure(
                        ResolutionErrorKind.TYPE_VIOLATION, definition.name
                    )
                )
            normalized = value.strip()
            if (
                definition.pattern is not None
                and re.fullmatch(definition.pattern, normalized) is None
            ):
                return Err(
                    ResolutionFailure(
                        ResolutionErrorKind.PATTERN_VIOLATION, definition.name
                    )
                )
        case "boolean":
            if not isinstance(value, bool):
                return Err(
                    ResolutionFailure(
                        ResolutionErrorKind.TYPE_VIOLATION, definition.name
                    )
                )
        case "enum":
            if not isinstance(value, str) or value not in definition.choices:
                return Err(
                    ResolutionFailure(
                        ResolutionErrorKind.ENUM_VIOLATION, definition.name
                    )
                )
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            return assert_never(
                definition.type
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
    return Ok(value.strip() if isinstance(value, str) else value)


def _resolve_settings(
    effective: tuple[str, ...], supplied: Mapping[str, Mapping[str, SettingValue]]
) -> Result[Mapping[str, Mapping[str, SettingValue]], ResolutionFailure]:
    unknown_capabilities = set(supplied).difference(effective)
    if unknown_capabilities:
        return Err(
            ResolutionFailure(
                ResolutionErrorKind.UNSELECTED_SETTINGS,
                sorted(unknown_capabilities)[0],
            )
        )
    resolved: dict[str, Mapping[str, SettingValue]] = {}
    for capability_id in effective:
        definition = CATALOG[capability_id]
        declared = {setting.name: setting for setting in definition.settings}
        values = supplied.get(capability_id, {})
        unknown_settings = set(values).difference(declared)
        if unknown_settings:
            key = sorted(unknown_settings)[0]
            return Err(
                ResolutionFailure(
                    ResolutionErrorKind.UNKNOWN_SETTING, f"{capability_id}.{key}"
                )
            )
        normalized: dict[str, SettingValue] = {}
        for setting in definition.settings:
            match _setting_value(setting, values):
                case Err(failure):
                    return Err(failure)
                case Ok(value):
                    normalized[setting.name] = value
        resolved[capability_id] = MappingProxyType(normalized)
    return Ok(MappingProxyType(resolved))


def resolve_bundle(
    bundle: BootstrapBundle,
    *,
    additions: tuple[str, ...] = (),
) -> Result[ResolvedBundle, ResolutionFailure]:
    profile_id = bundle.profile.id
    requested = (
        bundle.profile.capabilities
        if profile_id == "custom"
        else PROFILE_CAPABILITIES.get(profile_id)
    )
    if requested is None:
        return Err(ResolutionFailure(ResolutionErrorKind.UNKNOWN_PROFILE, profile_id))
    combined = tuple(requested) + tuple(additions)
    if len(set(combined)) != len(combined):
        return Err(ResolutionFailure(ResolutionErrorKind.DUPLICATE_ADDITION))
    match _closure(combined, CATALOG):
        case Err(failure):
            return Err(failure)
        case Ok(effective_set):
            pass
    match _topological_order(effective_set):
        case Err(failure):
            return Err(failure)
        case Ok(effective):
            pass
    match _resolve_settings(effective, bundle.capability_settings):
        case Err(failure):
            return Err(failure)
        case Ok(settings):
            pass
    return Ok(ResolvedBundle(profile_id, combined, effective, settings))


def normalized_settings_identity(
    settings: Mapping[str, Mapping[str, SettingValue]],
) -> str:
    """Return a tagged identity for normalized settings, independent of map insertion order."""

    payload = {
        capability_id: dict(values)
        for capability_id, values in sorted(settings.items())
    }
    return tagged_digest(b"normalized-settings", canonical_json(payload))


def resolve_recorded_selection(
    *,
    profile_id: str,
    requested: tuple[str, ...],
    additions: tuple[str, ...],
    settings: Mapping[str, Mapping[str, SettingValue]],
) -> Result[ResolvedBundle, ResolutionFailure]:
    """Resolve a recorded profile plus append-only additions against the catalog.

    ``status`` and lifecycle operations use this instead of fabricating a
    bundle: the recorded selection already carries the frozen profile id,
    requested ids, additions, and persisted normalized settings.
    """

    combined = tuple(requested) + tuple(additions)
    if len(set(combined)) != len(combined):
        return Err(ResolutionFailure(ResolutionErrorKind.DUPLICATE_ADDITION))
    match _closure(combined, CATALOG):
        case Err(failure):
            return Err(failure)
        case Ok(effective_set):
            pass
    match _topological_order(effective_set):
        case Err(failure):
            return Err(  # pragma: no cover  defensive — the closed catalog is a dependency DAG
                failure
            )
        case Ok(effective):
            pass
    match _resolve_settings(effective, settings):
        case Err(failure):
            return Err(failure)
        case Ok(resolved):
            pass
    return Ok(ResolvedBundle(profile_id, combined, effective, resolved))


def resolve_additions(
    current: ResolvedBundle,
    additions: AdditionsInput,
) -> Result[ResolvedBundle, ResolutionFailure]:
    """Resolve an append-only capability addition against an existing frozen selection."""

    requested = current.requested + additions.add_capabilities
    if len(set(requested)) != len(requested):
        return Err(ResolutionFailure(ResolutionErrorKind.DUPLICATE_ADDITION))
    match _closure(requested, CATALOG):
        case Err(failure):
            return Err(failure)
        case Ok(effective_set):
            pass
    match _topological_order(effective_set):
        case Err(failure):
            return Err(failure)
        case Ok(effective):
            pass
    supplied: dict[str, Mapping[str, SettingValue]] = {
        capability_id: dict(values)
        for capability_id, values in current.settings.items()
    }
    for capability_id, values in additions.capability_settings.items():
        normalized_values = {
            key: value.strip() if isinstance(value, str) else value
            for key, value in values.items()
        }
        if (
            capability_id in current.settings
            and dict(current.settings[capability_id]) != normalized_values
        ):
            return Err(
                ResolutionFailure(
                    ResolutionErrorKind.RECONFIGURE_SETTINGS, capability_id
                )
            )
        supplied[capability_id] = normalized_values
    match _resolve_settings(effective, supplied):
        case Err(failure):
            return Err(failure)
        case Ok(settings):
            pass
    return Ok(ResolvedBundle(current.profile_id, requested, effective, settings))
