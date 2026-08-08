"""Declarative capability catalog; it contains no executable capability hooks."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from scripts.bootstrap.paths import parse_path
from scripts.bootstrap.result import Ok
from scripts.bootstrap.schemas import Identifier, SettingName, StrictModel


class SettingDefinition(StrictModel):
    name: SettingName
    type: Literal["string", "boolean", "enum"]
    required: bool = False
    default: str | bool | None = None
    choices: tuple[str, ...] = ()
    secret: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> SettingDefinition:
        if self.type == "enum" and not self.choices:
            raise ValueError("enum settings require choices")
        if self.type != "enum" and self.choices:
            raise ValueError("only enum settings may declare choices")
        if self.required and self.default is not None:
            raise ValueError("required settings cannot have defaults")
        if (
            self.type == "string"
            and self.default is not None
            and not isinstance(self.default, str)
        ):
            raise ValueError("string settings require string defaults")
        if (
            self.type == "boolean"
            and self.default is not None
            and not isinstance(self.default, bool)
        ):
            raise ValueError("boolean settings require boolean defaults")
        if (
            self.type == "enum"
            and self.default is not None
            and self.default not in self.choices
        ):
            raise ValueError("enum defaults must be one of the choices")
        if self.secret:
            raise ValueError("secret settings are not supported")
        return self


class ArtifactDefinition(StrictModel):
    id: Identifier
    path: str
    kind: Literal["text", "binary"]
    mode: Literal[0o644, 0o755]

    @model_validator(mode="after")
    def validate_path(self) -> ArtifactDefinition:
        if not isinstance(parse_path(self.path), Ok):
            raise ValueError("artifact path must be repository-relative")
        return self


class ContributionDefinition(StrictModel):
    id: Identifier
    slot: Identifier
    order: int
    kind: Identifier


class CapabilityDefinition(StrictModel):
    id: Identifier
    description: str
    dependencies: tuple[Identifier, ...] = ()
    settings: tuple[SettingDefinition, ...] = ()
    artifacts: tuple[ArtifactDefinition, ...] = ()
    contributions: tuple[ContributionDefinition, ...] = ()
    runtime_dependencies: tuple[str, ...] = ()
    supported_python: str = ">=3.14"
    invocation: str | None = None

    @model_validator(mode="after")
    def validate_unique_members(self) -> CapabilityDefinition:
        for values, label in (
            (self.dependencies, "dependencies"),
            (tuple(setting.name for setting in self.settings), "settings"),
            (tuple(artifact.id for artifact in self.artifacts), "artifacts"),
            (
                tuple(contribution.id for contribution in self.contributions),
                "contributions",
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"capability {label} must be unique")
        if self.id in self.dependencies:
            raise ValueError("capability cannot depend on itself")
        return self


def _capability(
    capability_id: str,
    description: str,
    *,
    dependencies: tuple[str, ...] = (),
    settings: tuple[SettingDefinition, ...] = (),
) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        description=description,
        dependencies=dependencies,
        settings=settings,
    )


CATALOG: dict[str, CapabilityDefinition] = {
    "semantic-release": _capability("semantic-release", "Automated semantic releases."),
    "nix": _capability("nix", "Nix development and CI tooling."),
    "cachix-publish": _capability(
        "cachix-publish",
        "Publish Nix artifacts through Cachix.",
        dependencies=("nix",),
        settings=(
            SettingDefinition(
                name="cache_name",
                type="string",
                required=True,
            ),
        ),
    ),
    "pr-agent-gemini": _capability(
        "pr-agent-gemini", "Qodo PR Agent with a Gemini backend."
    ),
}
