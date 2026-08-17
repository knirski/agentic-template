"""Declarative capability catalog; it contains no executable capability hooks."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from scripts.bootstrap.dependencies import validate_dependency_metadata
from scripts.bootstrap.paths import parse_path
from scripts.bootstrap.result import Err, Ok
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
        match parse_path(self.path):
            case Ok(
                _
            ):  # pragma: no cover  coverage.py attributes case headers to the neighboring branch
                pass
            case Err(_):
                raise ValueError("artifact path must be repository-relative")
        return self


class ContributionDefinition(StrictModel):
    id: Identifier
    slot: Identifier
    order: int
    kind: Identifier


class DocumentFragmentDefinition(StrictModel):
    id: Identifier
    document: str
    order: int

    @model_validator(mode="after")
    def validate_document(self) -> DocumentFragmentDefinition:
        match parse_path(self.document):
            case Ok(
                _
            ):  # pragma: no cover  coverage.py attributes case headers to the neighboring branch
                pass
            case Err(_):
                raise ValueError("fragment document must be repository-relative")
        return self


class CapabilityDefinition(StrictModel):
    id: Identifier
    description: str
    dependencies: tuple[Identifier, ...] = ()
    settings: tuple[SettingDefinition, ...] = ()
    artifacts: tuple[ArtifactDefinition, ...] = ()
    contributions: tuple[ContributionDefinition, ...] = ()
    document_fragments: tuple[DocumentFragmentDefinition, ...] = ()
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
            (
                tuple(fragment.id for fragment in self.document_fragments),
                "document_fragments",
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"capability {label} must be unique")
        if self.id in self.dependencies:
            raise ValueError("capability cannot depend on itself")
        return self

    @model_validator(mode="after")
    def validate_capability_metadata(self) -> CapabilityDefinition:
        validate_dependency_metadata(
            self.runtime_dependencies, self.supported_python, self.invocation
        )
        return self


def _capability(
    capability_id: str,
    description: str,
    *,
    dependencies: tuple[str, ...] = (),
    settings: tuple[SettingDefinition, ...] = (),
    artifacts: tuple[ArtifactDefinition, ...] = (),
    contributions: tuple[ContributionDefinition, ...] = (),
    document_fragments: tuple[DocumentFragmentDefinition, ...] = (),
    runtime_dependencies: tuple[str, ...] = (),
    invocation: str | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        description=description,
        dependencies=dependencies,
        settings=settings,
        artifacts=artifacts,
        contributions=contributions,
        document_fragments=document_fragments,
        runtime_dependencies=runtime_dependencies,
        invocation=invocation,
    )


CATALOG: dict[str, CapabilityDefinition] = {
    "semantic-release": _capability(
        "semantic-release",
        "Automated semantic releases.",
        artifacts=(
            ArtifactDefinition(
                id="releaserc",
                path=".releaserc",
                kind="text",
                mode=0o644,
            ),
            ArtifactDefinition(
                id="semantic-release-workflow",
                path=".github/workflows/semantic-release.yml",
                kind="text",
                mode=0o644,
            ),
        ),
        contributions=(
            ContributionDefinition(
                id="release",
                slot="release-job",
                order=0,
                kind="yaml",
            ),
        ),
        runtime_dependencies=("python-semantic-release>=9",),
        invocation="uvx semantic-release",
    ),
    "nix": _capability(
        "nix",
        "Nix development and CI tooling.",
        artifacts=(
            ArtifactDefinition(
                id="flake-nix",
                path="flake.nix",
                kind="text",
                mode=0o644,
            ),
            ArtifactDefinition(
                id="flake-lock",
                path="flake.lock",
                kind="text",
                mode=0o644,
            ),
            ArtifactDefinition(
                id="nix-workflow",
                path=".github/workflows/nix.yml",
                kind="text",
                mode=0o644,
            ),
        ),
        contributions=(
            ContributionDefinition(
                id="nix-check",
                slot="capability-checks",
                order=0,
                kind="yaml",
            ),
        ),
    ),
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
        artifacts=(
            ArtifactDefinition(
                id="cachix-publish-workflow",
                path=".github/workflows/cachix-publish.yml",
                kind="text",
                mode=0o644,
            ),
        ),
        contributions=(
            ContributionDefinition(
                id="cachix-publish",
                slot="publish-job",
                order=0,
                kind="yaml",
            ),
        ),
    ),
    "pr-agent-gemini": _capability(
        "pr-agent-gemini",
        "Qodo PR Agent with a Gemini backend.",
        artifacts=(
            ArtifactDefinition(
                id="pr-agent-toml",
                path=".pr_agent.toml",
                kind="text",
                mode=0o644,
            ),
            ArtifactDefinition(
                id="pr-agent-workflow",
                path=".github/workflows/pr-agent.yml",
                kind="text",
                mode=0o644,
            ),
            ArtifactDefinition(
                id="pr-agent-commands-workflow",
                path=".github/workflows/pr-agent-commands.yml",
                kind="text",
                mode=0o644,
            ),
        ),
        # No generated-project runtime dependency: the generated workflows run
        # PR Agent through its pinned GitHub action, and the ``pr-agent``
        # package's exact transitive pins (``pyyaml==6.0.1``, ``ujson==5.8.0``)
        # are not installable on the generated project's Python 3.14.  The
        # local command stays declared through the invocation metadata.
        invocation="uvx pr-agent",
    ),
}


def catalog_surface() -> dict[str, dict[str, object]]:
    """The frozen v1 catalog surface: the stable-ID compatibility contract.

    ``validate_template.py`` compares the live catalog against the recorded
    fixture; within v1 a capability may update artifact bodies and
    documentation but may not change any member of this surface.
    """

    return {
        capability_id: {
            "dependencies": list(definition.dependencies),
            "settings": [
                {
                    "name": setting.name,
                    "type": setting.type,
                    "required": setting.required,
                    "default": setting.default,
                    "choices": list(setting.choices),
                }
                for setting in definition.settings
            ],
            "artifacts": [
                {
                    "id": artifact.id,
                    "path": artifact.path,
                    "kind": artifact.kind,
                    "mode": artifact.mode,
                }
                for artifact in definition.artifacts
            ],
            "contributions": [
                {
                    "id": contribution.id,
                    "slot": contribution.slot,
                    "order": contribution.order,
                    "kind": contribution.kind,
                }
                for contribution in definition.contributions
            ],
            "document_fragments": [
                {
                    "id": fragment.id,
                    "document": fragment.document,
                    "order": fragment.order,
                }
                for fragment in definition.document_fragments
            ],
            "runtime_dependencies": list(definition.runtime_dependencies),
            "supported_python": definition.supported_python,
            "invocation": definition.invocation,
        }
        for capability_id, definition in sorted(CATALOG.items())
    }
