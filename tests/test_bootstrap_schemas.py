from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.bootstrap.bundles import decode_bundle
from scripts.bootstrap.schemas import AdditionsInput, BootstrapBundle


def bundle_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": 1,
        "project": {"name": "example", "default_branch": "main"},
        "profile": {"id": "integrated"},
        "content": {
            "prd": {"mode": "scaffold"},
            "readme": {"mode": "scaffold"},
            "validation_hook": {"mode": "scaffold"},
            "security_policy": {"mode": "scaffold"},
            "contributing": {"mode": "scaffold"},
        },
        "licensing": {"mode": "private", "path": "content/license.txt"},
        "capability_settings": {"cachix-publish": {"cache_name": "example"}},
    }
    data.update(overrides)
    return data


def test_bundle_is_strict_and_closed() -> None:
    bundle = BootstrapBundle.model_validate(bundle_data())
    assert bundle.schema_version == 1
    assert bundle.project.name == "example"

    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate({**bundle_data(), "unknown": True})
    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate({**bundle_data(), "schema_version": True})
    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate({**bundle_data(), "schema_version": 2})


def test_bundle_requires_legal_path_for_private_license() -> None:
    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate(
            {**bundle_data(), "licensing": {"mode": "private"}}
        )


@pytest.mark.parametrize(
    "profile",
    [
        {"id": "custom"},
        {"id": "portable", "capabilities": ["nix"]},
        {"id": "custom", "capabilities": ["nix", "nix"]},
    ],
)
def test_profile_capability_shape_is_closed(profile: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate(
            {**bundle_data(profile=profile), "capability_settings": {}}
        )


def test_file_content_rejects_unsafe_paths() -> None:
    with pytest.raises(ValidationError):
        BootstrapBundle.model_validate(
            bundle_data(
                content={
                    "prd": {"mode": "file", "path": "../prd.md"},
                    "readme": {"mode": "scaffold"},
                    "validation_hook": {"mode": "scaffold"},
                    "security_policy": {"mode": "scaffold"},
                    "contributing": {"mode": "scaffold"},
                }
            )
        )


def test_additions_schema_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        AdditionsInput.model_validate({"schema_version": 2})
    with pytest.raises(ValidationError):
        AdditionsInput.model_validate(
            {"schema_version": 1, "add_capabilities": ["nix", "nix"]}
        )
    with pytest.raises(ValidationError):
        AdditionsInput.model_validate(
            {
                "schema_version": 1,
                "capability_settings": {"nix": {"api_key": "secret"}},
            }
        )


def test_json_capability_arrays_are_normalized_to_tuples() -> None:
    custom = BootstrapBundle.model_validate(
        bundle_data(profile={"id": "custom", "capabilities": ["nix"]})
    )
    assert custom.profile.capabilities == ("nix",)

    additions = AdditionsInput.model_validate(
        {"schema_version": 1, "add_capabilities": ["nix"]}
    )
    assert additions.add_capabilities == ("nix",)


def test_decode_bundle_rejects_secrets_and_bad_paths() -> None:
    with pytest.raises(ValidationError):
        decode_bundle(
            {**bundle_data(), "capability_settings": {"x": {"token": "secret"}}}
        )
    with pytest.raises(ValidationError):
        decode_bundle(
            {
                **bundle_data(),
                "licensing": {"mode": "provided-project-license", "path": "../license"},
            }
        )
