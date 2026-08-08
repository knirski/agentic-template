"""Stable-ID compatibility checks for the schema-v1 catalog surface."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.bootstrap.catalog import CATALOG, CapabilityDefinition


@dataclass(frozen=True, slots=True)
class CompatibilityIssue:
    capability_id: str
    reason: str


def _surface(definition: CapabilityDefinition) -> tuple[object, ...]:
    return (
        definition.id,
        definition.dependencies,
        tuple(
            (
                setting.name,
                setting.type,
                setting.required,
                setting.default,
                setting.choices,
            )
            for setting in definition.settings
        ),
        tuple((artifact.id, artifact.path) for artifact in definition.artifacts),
    )


CATALOG_V1_SURFACE = {
    capability_id: _surface(definition) for capability_id, definition in CATALOG.items()
}


def check_catalog_compatibility(
    catalog: dict[str, CapabilityDefinition],
    baseline: dict[str, tuple[object, ...]] = CATALOG_V1_SURFACE,
) -> tuple[CompatibilityIssue, ...]:
    issues: list[CompatibilityIssue] = []
    for capability_id, old_surface in baseline.items():
        current = catalog.get(capability_id)
        if current is None:
            issues.append(
                CompatibilityIssue(capability_id, "stable capability was removed")
            )
        elif _surface(current) != old_surface:
            issues.append(
                CompatibilityIssue(capability_id, "stable capability surface changed")
            )
    for capability_id in catalog:
        if capability_id not in baseline:
            continue
    return tuple(issues)
