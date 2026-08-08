"""Strict, immutable Pydantic schemas for the bootstrap input boundary."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from scripts.bootstrap.paths import parse_path
from scripts.bootstrap.result import Ok

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$",
        strict=True,
    ),
]
SettingName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        strict=True,
    ),
]
ProjectName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._-]*$",
        strict=True,
    ),
]
BranchName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
        strict=True,
    ),
]
RepoPathString = Annotated[str, StringConstraints(min_length=1, strict=True)]
type SettingValue = str | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_assignment=True,
    )


class ProjectInput(StrictModel):
    name: ProjectName
    default_branch: BranchName


class FileContent(StrictModel):
    mode: Literal["file"]
    path: RepoPathString

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        parsed = parse_path(value)
        if hasattr(parsed, "error"):
            raise ValueError("path must be a safe repository-relative path")
        return value


class ScaffoldContent(StrictModel):
    mode: Literal["scaffold"]


type ContentChoice = Annotated[
    FileContent | ScaffoldContent,
    Field(discriminator="mode"),
]


class ContentInputs(StrictModel):
    prd: ContentChoice
    readme: ContentChoice
    validation_hook: ContentChoice
    security_policy: ContentChoice
    contributing: ContentChoice


class LicensingInput(StrictModel):
    mode: Literal["retain-apache-2.0", "provided-project-license", "private"]
    path: RepoPathString | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None and not isinstance(parse_path(value), Ok):
            raise ValueError("path must be a safe repository-relative path")
        return value

    @model_validator(mode="after")
    def validate_mode_path(self) -> LicensingInput:
        requires_path = self.mode in {"provided-project-license", "private"}
        if requires_path != (self.path is not None):
            raise ValueError(
                "licensing path is required exactly for supplied license modes"
            )
        return self


class ProfileInput(StrictModel):
    id: Identifier
    capabilities: tuple[Identifier, ...] | None = None

    @model_validator(mode="after")
    def validate_custom_capabilities(self) -> ProfileInput:
        if (self.id == "custom") != (self.capabilities is not None):
            raise ValueError(
                "custom requires capabilities and named profiles reject them"
            )
        if self.capabilities is not None and len(set(self.capabilities)) != len(
            self.capabilities
        ):
            raise ValueError("profile capabilities must be unique")
        return self


class BootstrapBundle(StrictModel):
    schema_version: StrictInt
    project: ProjectInput
    profile: ProfileInput
    content: ContentInputs
    licensing: LicensingInput
    capability_settings: dict[Identifier, dict[SettingName, SettingValue]] = Field(
        default_factory=dict
    )

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported bootstrap schema version")
        return value

    @field_validator("capability_settings")
    @classmethod
    def reject_secret_settings(
        cls, value: dict[str, dict[str, SettingValue]]
    ) -> dict[str, dict[str, SettingValue]]:
        secret_words = (
            "secret",
            "token",
            "password",
            "credential",
            "api-key",
            "api_key",
        )
        if any(
            any(word in key.lower() for word in secret_words)
            for settings in value.values()
            for key in settings
        ):
            raise ValueError("secret settings are not accepted")
        return value


class AdditionsInput(StrictModel):
    schema_version: StrictInt
    add_capabilities: tuple[Identifier, ...] = ()
    capability_settings: dict[Identifier, dict[SettingName, SettingValue]] = Field(
        default_factory=dict
    )

    @field_validator("schema_version")
    @classmethod
    def supported_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("unsupported additions schema version")
        return value

    @field_validator("add_capabilities")
    @classmethod
    def unique_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("added capabilities must be unique")
        return value

    @field_validator("capability_settings")
    @classmethod
    def reject_secret_settings(
        cls, value: dict[str, dict[str, SettingValue]]
    ) -> dict[str, dict[str, SettingValue]]:
        secret_words = (
            "secret",
            "token",
            "password",
            "credential",
            "api-key",
            "api_key",
        )
        if any(
            any(word in key.lower() for word in secret_words)
            for settings in value.values()
            for key in settings
        ):
            raise ValueError("secret settings are not accepted")
        return value
