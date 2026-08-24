from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.bootstrap.bundles import DecodedBundle, decode_bundle, decode_bundle_input
from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.schemas import (
    AdditionsInput,
    BootstrapBundle,
    CollisionsInput,
    FileContent,
)


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
        _ = BootstrapBundle.model_validate({**bundle_data(), "unknown": True})
    with pytest.raises(ValidationError):
        _ = BootstrapBundle.model_validate({**bundle_data(), "schema_version": True})
    with pytest.raises(ValidationError):
        _ = BootstrapBundle.model_validate({**bundle_data(), "schema_version": 2})


def test_bundle_requires_legal_path_for_private_license() -> None:
    with pytest.raises(ValidationError):
        _ = BootstrapBundle.model_validate(
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
        _ = BootstrapBundle.model_validate(
            {**bundle_data(profile=profile), "capability_settings": {}}
        )


def test_file_content_accepts_safe_paths() -> None:
    bundle = BootstrapBundle.model_validate(
        bundle_data(
            content={
                "prd": {"mode": "file", "path": "content/prd.md"},
                "readme": {"mode": "scaffold"},
                "validation_hook": {"mode": "scaffold"},
                "security_policy": {"mode": "scaffold"},
                "contributing": {"mode": "scaffold"},
            }
        )
    )
    content = bundle.content.prd
    assert isinstance(content, FileContent)
    assert content.path == "content/prd.md"


def test_file_content_rejects_unsafe_paths() -> None:
    with pytest.raises(ValidationError):
        _ = BootstrapBundle.model_validate(
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
        _ = AdditionsInput.model_validate({"schema_version": 2})
    with pytest.raises(ValidationError):
        _ = AdditionsInput.model_validate(
            {"schema_version": 1, "add_capabilities": ["nix", "nix"]}
        )
    with pytest.raises(ValidationError):
        _ = AdditionsInput.model_validate(
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
        _ = decode_bundle(
            {**bundle_data(), "capability_settings": {"x": {"token": "secret"}}}
        )
    with pytest.raises(ValidationError):
        _ = decode_bundle(
            {
                **bundle_data(),
                "licensing": {"mode": "provided-project-license", "path": "../license"},
            }
        )


def test_bundle_accepts_collision_declarations() -> None:
    collisions = {"README.md": "replace", "docs/guide.md": "keep-existing"}
    bundle = BootstrapBundle.model_validate({**bundle_data(), "collisions": collisions})
    assert isinstance(bundle.collisions, CollisionsInput)
    assert bundle.collisions.root == collisions
    assert bundle.model_dump(mode="json")["collisions"] == collisions


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "",
        ".",
        "..",
        "a//b",
        "trailing/",
        "a\\b",
        "a/../b",
    ],
)
def test_malformed_collision_paths_are_rejected_naming_the_entry(path: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _ = BootstrapBundle.model_validate(
            {**bundle_data(), "collisions": {path: "replace"}}
        )
    assert path in str(excinfo.value)


@pytest.mark.parametrize("action", ["delete", "REPLACE", "", True, 3, None])
def test_collision_actions_outside_the_closed_set_are_rejected(action: object) -> None:
    with pytest.raises(ValidationError):
        _ = BootstrapBundle.model_validate(
            {**bundle_data(), "collisions": {"README.md": action}}
        )


def test_absent_collisions_field_decodes_identically_to_today() -> None:
    bundle = BootstrapBundle.model_validate(bundle_data())
    assert bundle.collisions is None
    document = bundle.model_dump(mode="json")
    assert "collisions" not in document
    empty = BootstrapBundle.model_validate({**bundle_data(), "collisions": {}})
    assert empty.model_dump(mode="json") == document


_PORTABLE_FILES: dict[str, bytes] = {
    "content/prd.md": b"# Product requirements\n",
    "content/readme.md": b"# Example\n",
    "content/hook": b"#!/bin/sh\n",
    "content/security.md": b"# Security\n",
    "content/contributing.md": b"# Contributing\n",
}


def _portable_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": {"name": "example", "default_branch": "main"},
        "profile": {"id": "portable"},
        "content": {
            "prd": {"mode": "file", "path": "content/prd.md"},
            "readme": {"mode": "file", "path": "content/readme.md"},
            "validation_hook": {"mode": "file", "path": "content/hook"},
            "security_policy": {"mode": "file", "path": "content/security.md"},
            "contributing": {"mode": "file", "path": "content/contributing.md"},
        },
        "licensing": {"mode": "retain-apache-2.0"},
    }


def _decode_disk_bundle(
    tmp_path: Path, name: str, document: dict[str, object]
) -> DecodedBundle:
    root = tmp_path / name
    root.mkdir()
    for relative, content in _PORTABLE_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_bytes(content)
    json_path = root / "bootstrap.json"
    _ = json_path.write_bytes(canonical_json(document))
    match decode_bundle_input(str(json_path)):
        case Ok(decoded):
            return decoded
        case Err(error):
            raise AssertionError(f"expected success, got {error}")


def test_bundle_digest_changes_only_when_declarations_change(tmp_path: Path) -> None:
    absent = _decode_disk_bundle(tmp_path, "absent", _portable_document())
    empty = _decode_disk_bundle(
        tmp_path, "empty", {**_portable_document(), "collisions": {}}
    )
    keep = _decode_disk_bundle(
        tmp_path,
        "keep",
        {**_portable_document(), "collisions": {"README.md": "keep-existing"}},
    )
    replace = _decode_disk_bundle(
        tmp_path,
        "replace",
        {**_portable_document(), "collisions": {"README.md": "replace"}},
    )
    extra = _decode_disk_bundle(
        tmp_path,
        "extra",
        {
            **_portable_document(),
            "collisions": {
                "README.md": "replace",
                "docs/guide.md": "keep-existing",
            },
        },
    )
    reordered = _decode_disk_bundle(
        tmp_path,
        "reordered",
        {
            **_portable_document(),
            "collisions": {
                "docs/guide.md": "keep-existing",
                "README.md": "replace",
            },
        },
    )

    assert empty.bundle_digest == absent.bundle_digest
    assert keep.bundle_digest != absent.bundle_digest
    assert replace.bundle_digest != keep.bundle_digest
    assert extra.bundle_digest != replace.bundle_digest
    assert reordered.bundle_digest == extra.bundle_digest
    assert reordered.document["collisions"] == {
        "README.md": "replace",
        "docs/guide.md": "keep-existing",
    }
