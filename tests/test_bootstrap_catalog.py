from __future__ import annotations

import os

import pytest

from scripts.bootstrap.bundles import decode_bundle
from scripts.bootstrap.catalog import CATALOG
from scripts.bootstrap.profiles import PROFILE_CAPABILITIES
from scripts.bootstrap.resolver import (
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
