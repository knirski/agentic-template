from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from scripts.bootstrap.bundles import decode_bundle
from scripts.bootstrap.catalog import (
    CATALOG,
    ArtifactDefinition,
    CapabilityDefinition,
    ContributionDefinition,
    SettingDefinition,
)
from scripts.bootstrap.profiles import PROFILE_CAPABILITIES
from scripts.bootstrap.resolver import (
    ResolutionError,
    _setting_value,
    resolve_additions,
    resolve_bundle,
)
from scripts.bootstrap.schemas import AdditionsInput
from tests.test_bootstrap_schemas import bundle_data


def test_all_profiles_have_expected_frozen_expansion() -> None:
    assert PROFILE_CAPABILITIES == {
        "portable": (),
        "release-automated": ("semantic-release",),
        "nix-enabled": ("nix",),
        "integrated": (
            "semantic-release",
            "nix",
            "cachix-publish",
            "pr-agent-gemini",
        ),
    }


def test_integrated_profile_closes_dependencies_and_normalizes_defaults() -> None:
    resolved = resolve_bundle(decode_bundle(bundle_data()))
    assert resolved.effective == (
        "nix",
        "pr-agent-gemini",
        "semantic-release",
        "cachix-publish",
    )
    assert resolved.settings["cachix-publish"]["cache_name"] == "example"


def test_additions_close_dependencies_and_reject_reconfiguration() -> None:
    data = bundle_data(
        profile={"id": "portable"},
        capability_settings={"cachix-publish": {"cache_name": "example"}},
    )
    resolved = resolve_bundle(decode_bundle(data), additions=("cachix-publish",))
    assert resolved.effective == ("nix", "cachix-publish")

    added = resolve_additions(
        resolve_bundle(
            decode_bundle(
                bundle_data(profile={"id": "portable"}, capability_settings={})
            )
        ),
        AdditionsInput(
            schema_version=1,
            add_capabilities=("cachix-publish",),
            capability_settings={"cachix-publish": {"cache_name": " example "}},
        ),
    )
    assert added.settings["cachix-publish"]["cache_name"] == "example"

    with pytest.raises(ValueError, match="reconfigured"):
        resolve_additions(
            resolved,
            AdditionsInput(
                schema_version=1,
                add_capabilities=(),
                capability_settings={"cachix-publish": {"cache_name": "other"}},
            ),
        )


def test_normalized_settings_identity_is_order_independent() -> None:
    first = resolve_bundle(decode_bundle(bundle_data()))
    second = resolve_bundle(
        decode_bundle(
            bundle_data(
                capability_settings={"cachix-publish": {"cache_name": " example "}}
            )
        )
    )
    assert first.settings_identity == second.settings_identity

    with pytest.raises(ValueError, match="secret"):
        resolve_bundle(
            decode_bundle(
                bundle_data(
                    capability_settings={
                        "cachix-publish": {"cache_name": "example", "token": "secret"}
                    }
                )
            )
        )


def test_resolution_does_not_read_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHIX_AUTH_TOKEN", "must-not-be-read")
    before = dict(os.environ)
    resolve_bundle(decode_bundle(bundle_data()))
    assert dict(os.environ) == before


def test_catalog_uses_declarative_definitions() -> None:
    assert set(CATALOG) == {
        "semantic-release",
        "nix",
        "cachix-publish",
        "pr-agent-gemini",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"name": "mode", "type": "enum"},
        {"name": "mode", "type": "string", "choices": ("x",)},
        {"name": "mode", "type": "string", "required": True, "default": "x"},
        {"name": "mode", "type": "string", "default": True},
        {"name": "mode", "type": "boolean", "default": "true"},
        {"name": "mode", "type": "enum", "choices": ("x",), "default": "y"},
        {"name": "token", "type": "string", "secret": True},
    ],
)
def test_setting_definition_rejects_invalid_shapes(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SettingDefinition.model_validate(data)


def test_catalog_definitions_reject_unsafe_or_duplicate_members() -> None:
    with pytest.raises(ValidationError):
        ArtifactDefinition(id="artifact", path="../unsafe", kind="text", mode=0o644)
    duplicate = SettingDefinition(name="name", type="string")
    with pytest.raises(ValidationError):
        CapabilityDefinition(
            id="example", description="x", settings=(duplicate, duplicate)
        )
    with pytest.raises(ValidationError):
        CapabilityDefinition(id="example", description="x", dependencies=("example",))
    contribution = ContributionDefinition(id="slot", slot="slot", order=0, kind="yaml")
    with pytest.raises(ValidationError):
        CapabilityDefinition(
            id="example",
            description="x",
            contributions=(contribution, contribution),
        )


def test_resolution_rejects_invalid_profiles_and_settings() -> None:
    with pytest.raises(ResolutionError, match="unknown profile"):
        resolve_bundle(decode_bundle(bundle_data(profile={"id": "unknown"})))
    with pytest.raises(ResolutionError, match="unknown capability"):
        resolve_bundle(
            decode_bundle(
                bundle_data(
                    profile={"id": "custom", "capabilities": ["unknown"]},
                    capability_settings={},
                )
            )
        )
    with pytest.raises(ResolutionError, match="unknown setting"):
        resolve_bundle(
            decode_bundle(
                bundle_data(capability_settings={"cachix-publish": {"unknown": "x"}})
            )
        )
    with pytest.raises(ResolutionError, match="settings supplied"):
        resolve_bundle(
            decode_bundle(bundle_data(capability_settings={"unknown": {"value": "x"}}))
        )
    with pytest.raises(ResolutionError, match="missing required"):
        resolve_bundle(
            decode_bundle(
                bundle_data(profile={"id": "portable"}, capability_settings={})
            ),
            additions=("cachix-publish",),
        )


def test_setting_value_validation_covers_closed_setting_types() -> None:
    boolean = SettingDefinition(name="enabled", type="boolean", default=False)
    enum = SettingDefinition(name="mode", type="enum", choices=("a",))
    secret = SettingDefinition.model_construct(
        name="secret",
        type="string",
        required=False,
        default="x",
        choices=(),
        secret=True,
    )
    assert _setting_value(boolean, {}) is False
    with pytest.raises(ResolutionError, match="outside its enum"):
        _setting_value(enum, {"mode": "b"})
    with pytest.raises(ResolutionError, match="secret"):
        _setting_value(secret, {})
    with pytest.raises(ResolutionError, match="must be a string"):
        _setting_value(SettingDefinition(name="name", type="string"), {"name": True})
    with pytest.raises(ResolutionError, match="must be a boolean"):
        _setting_value(
            SettingDefinition(name="enabled", type="boolean"), {"enabled": "yes"}
        )
    with pytest.raises(ResolutionError, match="no deterministic"):
        _setting_value(SettingDefinition(name="name", type="string"), {})


def test_resolution_rejects_cycles_and_duplicate_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        CATALOG,
        "cycle-a",
        CapabilityDefinition(id="cycle-a", description="a", dependencies=("cycle-b",)),
    )
    monkeypatch.setitem(
        CATALOG,
        "cycle-b",
        CapabilityDefinition(id="cycle-b", description="b", dependencies=("cycle-a",)),
    )
    with pytest.raises(ResolutionError, match="cycle"):
        resolve_bundle(
            decode_bundle(
                bundle_data(
                    profile={"id": "custom", "capabilities": ["cycle-a"]},
                    capability_settings={},
                )
            )
        )
    with pytest.raises(ResolutionError, match="repeat"):
        resolve_bundle(decode_bundle(bundle_data()), additions=("semantic-release",))
    with pytest.raises(ResolutionError, match="new IDs"):
        resolve_additions(
            resolve_bundle(decode_bundle(bundle_data())),
            AdditionsInput(schema_version=1, add_capabilities=("semantic-release",)),
        )
