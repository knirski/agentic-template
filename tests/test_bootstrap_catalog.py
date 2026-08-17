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
    ResolutionErrorKind,
    ResolutionFailure,
    ResolvedBundle,
    _setting_value,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    resolve_additions,
    resolve_bundle,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.schemas import AdditionsInput
from tests.test_bootstrap_schemas import bundle_data


def _ok(result: Result[ResolvedBundle, ResolutionFailure]) -> ResolvedBundle:
    match result:
        case Ok(resolved):
            return resolved
        case Err(failure):
            raise AssertionError(f"resolution failed: {failure}")


def _failure[Value, Failure: ResolutionFailure](
    result: Result[Value, Failure],
) -> Failure:
    match result:
        case Err(failure):
            return failure
        case Ok(_):
            raise AssertionError("resolution unexpectedly succeeded")


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
    resolved = _ok(resolve_bundle(decode_bundle(bundle_data())))
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
    resolved = _ok(resolve_bundle(decode_bundle(data), additions=("cachix-publish",)))
    assert resolved.effective == ("nix", "cachix-publish")

    added = _ok(
        resolve_additions(
            _ok(
                resolve_bundle(
                    decode_bundle(
                        bundle_data(profile={"id": "portable"}, capability_settings={})
                    )
                )
            ),
            AdditionsInput(
                schema_version=1,
                add_capabilities=("cachix-publish",),
                capability_settings={"cachix-publish": {"cache_name": " example "}},
            ),
        )
    )
    assert added.settings["cachix-publish"]["cache_name"] == "example"

    assert (
        _failure(
            resolve_additions(
                resolved,
                AdditionsInput(
                    schema_version=1,
                    add_capabilities=(),
                    capability_settings={"cachix-publish": {"cache_name": "other"}},
                ),
            )
        ).kind
        is ResolutionErrorKind.RECONFIGURE_SETTINGS
    )


def test_normalized_settings_identity_is_order_independent() -> None:
    first = _ok(resolve_bundle(decode_bundle(bundle_data())))
    second = _ok(
        resolve_bundle(
            decode_bundle(
                bundle_data(
                    capability_settings={"cachix-publish": {"cache_name": " example "}}
                )
            )
        )
    )
    assert first.settings_identity == second.settings_identity


def test_resolution_does_not_read_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CACHIX_AUTH_TOKEN", "must-not-be-read")
    before = dict(os.environ)
    _ = _ok(resolve_bundle(decode_bundle(bundle_data())))
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
        {"name": "mode", "type": "boolean", "pattern": "^x$"},
        {"name": "mode", "type": "string", "pattern": "["},
    ],
)
def test_setting_definition_rejects_invalid_shapes(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _ = SettingDefinition.model_validate(data)


def test_catalog_definitions_reject_unsafe_or_duplicate_members() -> None:
    with pytest.raises(ValidationError):
        _ = ArtifactDefinition(id="artifact", path="../unsafe", kind="text", mode=0o644)
    duplicate = SettingDefinition(name="name", type="string")
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="example", description="x", settings=(duplicate, duplicate)
        )
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="example", description="x", dependencies=("example",)
        )
    contribution = ContributionDefinition(id="slot", slot="slot", order=0, kind="yaml")
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="example",
            description="x",
            contributions=(contribution, contribution),
        )


def test_resolution_rejects_invalid_profiles_and_settings() -> None:
    assert (
        _failure(
            resolve_bundle(decode_bundle(bundle_data(profile={"id": "unknown"})))
        ).kind
        is ResolutionErrorKind.UNKNOWN_PROFILE
    )
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(
                    bundle_data(
                        profile={"id": "custom", "capabilities": ["unknown"]},
                        capability_settings={},
                    )
                )
            )
        ).kind
        is ResolutionErrorKind.UNKNOWN_CAPABILITY
    )
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(
                    bundle_data(
                        capability_settings={"cachix-publish": {"unknown": "x"}}
                    )
                )
            )
        ).kind
        is ResolutionErrorKind.UNKNOWN_SETTING
    )
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(
                    bundle_data(capability_settings={"unknown": {"value": "x"}})
                )
            )
        ).kind
        is ResolutionErrorKind.UNSELECTED_SETTINGS
    )
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(
                    bundle_data(profile={"id": "portable"}, capability_settings={})
                ),
                additions=("cachix-publish",),
            )
        ).kind
        is ResolutionErrorKind.MISSING_REQUIRED_SETTING
    )


def test_setting_value_validation_covers_closed_setting_types() -> None:
    boolean = SettingDefinition(name="enabled", type="boolean", default=False)
    enum = SettingDefinition(name="mode", type="enum", choices=("a",))
    patterned = SettingDefinition(
        name="cache_name",
        type="string",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    secret = SettingDefinition.model_construct(
        name="secret",
        type="string",
        required=False,
        default="x",
        choices=(),
        secret=True,
        pattern=None,
    )
    assert _setting_value(boolean, {}) == Ok(False)
    assert (
        _failure(_setting_value(enum, {"mode": "b"})).kind
        is ResolutionErrorKind.ENUM_VIOLATION
    )
    assert (
        _failure(_setting_value(secret, {})).kind is ResolutionErrorKind.SECRET_SETTING
    )
    assert (
        _failure(
            _setting_value(
                SettingDefinition(name="name", type="string"), {"name": True}
            )
        ).kind
        is ResolutionErrorKind.TYPE_VIOLATION
    )
    assert (
        _failure(
            _setting_value(
                SettingDefinition(name="enabled", type="boolean"), {"enabled": "yes"}
            )
        ).kind
        is ResolutionErrorKind.TYPE_VIOLATION
    )
    assert (
        _failure(_setting_value(SettingDefinition(name="name", type="string"), {})).kind
        is ResolutionErrorKind.UNDETERMINED_SETTING
    )
    # Patterned string settings reject shell metacharacters and stray
    # whitespace after normalization.
    assert _setting_value(patterned, {"cache_name": " my-cache_1"}) == Ok("my-cache_1")
    assert (
        _failure(_setting_value(patterned, {"cache_name": "$(curl evil)"})).kind
        is ResolutionErrorKind.PATTERN_VIOLATION
    )
    assert (
        _failure(_setting_value(patterned, {"cache_name": "two words"})).kind
        is ResolutionErrorKind.PATTERN_VIOLATION
    )


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
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(
                    bundle_data(
                        profile={"id": "custom", "capabilities": ["cycle-a"]},
                        capability_settings={},
                    )
                )
            )
        ).kind
        is ResolutionErrorKind.DEPENDENCY_CYCLE
    )
    assert (
        _failure(
            resolve_bundle(
                decode_bundle(bundle_data()), additions=("semantic-release",)
            )
        ).kind
        is ResolutionErrorKind.DUPLICATE_ADDITION
    )
    assert (
        _failure(
            resolve_additions(
                _ok(resolve_bundle(decode_bundle(bundle_data()))),
                AdditionsInput(
                    schema_version=1, add_capabilities=("semantic-release",)
                ),
            )
        ).kind
        is ResolutionErrorKind.DUPLICATE_ADDITION
    )
    assert (
        _failure(
            resolve_additions(
                _ok(resolve_bundle(decode_bundle(bundle_data()))),
                AdditionsInput(schema_version=1, add_capabilities=("ghost",)),
            )
        ).kind
        is ResolutionErrorKind.UNKNOWN_CAPABILITY
    )
    assert (
        _failure(
            resolve_additions(
                _ok(resolve_bundle(decode_bundle(bundle_data()))),
                AdditionsInput(schema_version=1, add_capabilities=("cycle-a",)),
            )
        ).kind
        is ResolutionErrorKind.DEPENDENCY_CYCLE
    )
    assert (
        _failure(
            resolve_additions(
                _ok(
                    resolve_bundle(
                        decode_bundle(
                            bundle_data(
                                profile={"id": "portable"}, capability_settings={}
                            )
                        )
                    )
                ),
                AdditionsInput(schema_version=1, add_capabilities=("cachix-publish",)),
            )
        ).kind
        is ResolutionErrorKind.MISSING_REQUIRED_SETTING
    )
