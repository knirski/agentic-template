"""Pure profile, dependency, and normalized-setting resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.catalog import CATALOG, CapabilityDefinition, SettingDefinition
from scripts.bootstrap.identity import tagged_digest
from scripts.bootstrap.profiles import PROFILE_CAPABILITIES
from scripts.bootstrap.schemas import AdditionsInput, BootstrapBundle, SettingValue


class ResolutionError(ValueError):
    """A deterministic input or catalog resolution failure."""


@dataclass(frozen=True, slots=True)
class ResolvedBundle:
    profile_id: str
    requested: tuple[str, ...]
    effective: tuple[str, ...]
    settings: Mapping[str, Mapping[str, SettingValue]]

    @property
    def settings_identity(self) -> str:
        return normalized_settings_identity(self.settings)


def _topological_order(capability_ids: set[str]) -> tuple[str, ...]:
    result: list[str] = []
    remaining = set(capability_ids)
    while remaining:
        available = sorted(
            capability_id
            for capability_id in remaining
            if set(CATALOG[capability_id].dependencies).isdisjoint(remaining)
        )
        if not available:
            raise ResolutionError("capability dependency cycle")
        result.extend(available)
        remaining.difference_update(available)
    return tuple(result)


def _closure(
    requested: tuple[str, ...], catalog: Mapping[str, CapabilityDefinition]
) -> set[str]:
    effective: set[str] = set()
    pending = list(requested)
    while pending:
        capability_id = pending.pop()
        if capability_id in effective:
            continue
        if capability_id not in catalog:
            raise ResolutionError(f"unknown capability: {capability_id}")
        effective.add(capability_id)
        pending.extend(catalog[capability_id].dependencies)
    return effective


def _setting_value(
    definition: SettingDefinition,
    supplied: Mapping[str, SettingValue],
) -> SettingValue:
    if definition.name in supplied:
        value = supplied[definition.name]
    elif definition.default is not None:
        value = definition.default
    elif definition.required:
        raise ResolutionError(f"missing required setting: {definition.name}")
    else:
        raise ResolutionError(f"setting has no deterministic value: {definition.name}")
    if definition.secret:
        raise ResolutionError(f"secret setting is not accepted: {definition.name}")
    if definition.type == "string" and not isinstance(value, str):
        raise ResolutionError(f"setting must be a string: {definition.name}")
    if definition.type == "boolean" and not isinstance(value, bool):
        raise ResolutionError(f"setting must be a boolean: {definition.name}")
    if definition.type == "enum" and (
        not isinstance(value, str) or value not in definition.choices
    ):
        raise ResolutionError(f"setting is outside its enum: {definition.name}")
    return value.strip() if isinstance(value, str) else value


def _resolve_settings(
    effective: tuple[str, ...], supplied: Mapping[str, Mapping[str, SettingValue]]
) -> Mapping[str, Mapping[str, SettingValue]]:
    unknown_capabilities = set(supplied).difference(effective)
    if unknown_capabilities:
        raise ResolutionError(
            f"settings supplied for unselected capability: {sorted(unknown_capabilities)[0]}"
        )
    resolved: dict[str, Mapping[str, SettingValue]] = {}
    for capability_id in effective:
        definition = CATALOG[capability_id]
        declared = {setting.name: setting for setting in definition.settings}
        values = supplied.get(capability_id, {})
        unknown_settings = set(values).difference(declared)
        if unknown_settings:
            key = sorted(unknown_settings)[0]
            raise ResolutionError(f"unknown setting: {capability_id}.{key}")
        normalized = {
            setting.name: _setting_value(setting, values)
            for setting in definition.settings
        }
        resolved[capability_id] = MappingProxyType(normalized)
    return MappingProxyType(resolved)


def resolve_bundle(
    bundle: BootstrapBundle,
    *,
    additions: tuple[str, ...] = (),
) -> ResolvedBundle:
    profile_id = bundle.profile.id
    requested = (
        bundle.profile.capabilities
        if profile_id == "custom"
        else PROFILE_CAPABILITIES.get(profile_id)
    )
    if requested is None:
        raise ResolutionError(f"unknown profile: {profile_id}")
    combined = tuple(requested) + tuple(additions)
    if len(set(combined)) != len(combined):
        raise ResolutionError(
            "capability additions must not repeat profile capabilities"
        )
    effective_set = _closure(combined, CATALOG)
    effective = _topological_order(effective_set)
    settings = _resolve_settings(effective, bundle.capability_settings)
    return ResolvedBundle(profile_id, combined, effective, settings)


def normalized_settings_identity(
    settings: Mapping[str, Mapping[str, SettingValue]],
) -> str:
    """Return a tagged identity for normalized settings, independent of map insertion order."""

    payload = {
        capability_id: dict(values)
        for capability_id, values in sorted(settings.items())
    }
    return tagged_digest(b"normalized-settings", canonical_json(payload))


def resolve_additions(
    current: ResolvedBundle,
    additions: AdditionsInput,
) -> ResolvedBundle:
    """Resolve an append-only capability addition against an existing frozen selection."""

    requested = current.requested + additions.add_capabilities
    if len(set(requested)) != len(requested):
        raise ResolutionError("capability additions must be new IDs")
    effective_set = _closure(requested, CATALOG)
    effective = _topological_order(effective_set)
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
            raise ResolutionError(
                f"existing settings cannot be reconfigured: {capability_id}"
            )
        supplied[capability_id] = normalized_values
    settings = _resolve_settings(effective, supplied)
    return ResolvedBundle(current.profile_id, requested, effective, settings)
