"""Strict, immutable Pydantic schemas for the bootstrap input boundary."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializerFunctionWrapHandler,
    StrictInt,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)

from scripts.bootstrap.paths import parse_path
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.vocabulary import (
    BRANCH_NAME_PATTERN,
    IDENTIFIER_PATTERN,
    PATH_BEARING_LICENSING_MODES,
    PROJECT_NAME_PATTERN,
    SETTING_NAME_PATTERN,
    is_secret_setting_name,
)

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=IDENTIFIER_PATTERN,
        strict=True,
    ),
]
SettingName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=SETTING_NAME_PATTERN,
        strict=True,
    ),
]
ProjectName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=PROJECT_NAME_PATTERN,
        strict=True,
    ),
]
BranchName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=BRANCH_NAME_PATTERN,
        strict=True,
    ),
]
RepoPathString = Annotated[str, StringConstraints(min_length=1, strict=True)]
type SettingValue = str | bool


def _validate_collision_path(value: str) -> str:
    match parse_path(value):
        case Ok(_):
            return value
        case Err(_):
            raise ValueError(
                f"{value}: collision paths must be safe repository-relative paths"
            )


CollisionPath = Annotated[str, AfterValidator(_validate_collision_path)]
CollisionAction = Literal["keep-existing", "replace"]


class StrictModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
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
        match parse_path(value):
            case Ok(_):
                pass
            case Err(_):
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
    project_validation: ContentChoice = Field(
        default_factory=lambda: ScaffoldContent(mode="scaffold")
    )


class LicensingInput(StrictModel):
    # The literal mirrors vocabulary.LICENSING_MODES; tests pin the two in sync.
    mode: Literal["retain-apache-2.0", "provided-project-license", "private"]
    path: RepoPathString | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None:
            match parse_path(value):
                case Ok(_):
                    pass
                case Err(_):
                    raise ValueError("path must be a safe repository-relative path")
        return value

    @model_validator(mode="after")
    def validate_mode_path(self) -> LicensingInput:
        requires_path = self.mode in PATH_BEARING_LICENSING_MODES
        if requires_path != (self.path is not None):
            raise ValueError(
                "licensing path is required exactly for supplied license modes"
            )
        return self


class ProfileInput(StrictModel):
    id: Identifier
    capabilities: tuple[Identifier, ...] | None = None

    @field_validator("capabilities", mode="before")
    @classmethod
    def normalize_json_capabilities(
        cls, value: list[str] | tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        return tuple(value) if isinstance(value, list) else value

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


class CollisionsInput(RootModel[dict[CollisionPath, CollisionAction]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        strict=True,
        validate_assignment=True,
    )


class BootstrapBundle(StrictModel):
    schema_version: StrictInt
    project: ProjectInput
    profile: ProfileInput
    content: ContentInputs
    licensing: LicensingInput
    capability_settings: dict[Identifier, dict[SettingName, SettingValue]] = Field(
        default_factory=dict
    )
    collisions: CollisionsInput | None = None

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
        if any(
            is_secret_setting_name(key)
            for settings in value.values()
            for key in settings
        ):
            raise ValueError("secret settings are not accepted")
        return value

    @model_serializer(mode="wrap")
    def _serialize_model(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        document = cast(dict[str, object], handler(self))
        if self.collisions is None or not self.collisions.root:
            _ = document.pop("collisions", None)
        return document


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

    @field_validator("add_capabilities", mode="before")
    @classmethod
    def normalize_json_capabilities(
        cls, value: list[str] | tuple[str, ...]
    ) -> tuple[str, ...]:
        return tuple(value) if isinstance(value, list) else value

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
        if any(
            is_secret_setting_name(key)
            for settings in value.values()
            for key in settings
        ):
            raise ValueError("secret settings are not accepted")
        return value
