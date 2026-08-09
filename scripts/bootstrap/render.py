"""Pure managed-rendering boundary: RenderInput, blob validation, and render_managed.

The renderer contract is self-contained here: definitions decode to the closed shapes below, and
``render_managed`` consumes only explicit values plus a verified template blob map. Seed-once and
legal adopter bytes are deliberately absent from this boundary; they enter only the initial
compiler, which places them in the operation plan without making them managed output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, assert_never

from pydantic import BeforeValidator, Field, field_validator, model_validator

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.identity import PosixMode, content_identity
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.paths import RepoPath, normalize_text, parse_path
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.schemas import Identifier, SettingName, SettingValue, StrictModel

ContextName = Literal["yaml", "toml", "json", "shell", "markdown"]
CardinalityName = Literal["exactly_one", "zero_or_one", "many"]


class RenderErrorKind(StrEnum):
    MISSING_BLOB = "missing_blob"
    INVALID_TEMPLATE = "invalid_template"
    OWNERSHIP_COLLISION = "ownership_collision"
    PATH_COLLISION = "path_collision"
    UNDECLARED_OUTPUT = "undeclared_output"


@dataclass(frozen=True, slots=True)
class RenderError:
    kind: RenderErrorKind
    reason: str = ""
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    name: str
    default_branch: str


@dataclass(frozen=True, slots=True)
class LicensingInfo:
    mode: str
    content_sha256: str | None


@dataclass(frozen=True, slots=True)
class ProfileInfo:
    id: str
    frozen: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MaintenanceInfo:
    status: str
    retained_paths: tuple[RepoPath, ...]


@dataclass(frozen=True, slots=True)
class SlotContent:
    mode: str
    content_sha256: str | None


def _as_content_id(value: object) -> ContentId:
    if isinstance(value, ContentId):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return ContentId(value)
    raise ValueError("blob reference must be a 64-hex content address")


BlobRef = Annotated[ContentId, BeforeValidator(_as_content_id)]


class SettingSource(StrictModel):
    kind: Literal["setting"]
    capability: Identifier
    setting: SettingName


class ProjectSource(StrictModel):
    kind: Literal["project"]
    key: Literal["name", "default_branch"]


class MaintenanceSource(StrictModel):
    kind: Literal["maintenance"]
    key: Literal["status", "retained_paths"]


SubstitutionSource = Annotated[
    SettingSource | ProjectSource | MaintenanceSource,
    Field(discriminator="kind"),
]


class SubstitutionDefinition(StrictModel):
    name: Identifier
    source: SubstitutionSource


def _validate_repo_path(value: str) -> str:
    if not isinstance(parse_path(value), Ok):
        raise ValueError("path must be a safe repository-relative path")
    return value


def _unique_substitution_names(
    substitutions: tuple[SubstitutionDefinition, ...],
) -> None:
    names = [substitution.name for substitution in substitutions]
    if len(set(names)) != len(names):
        raise ValueError("substitution names must be unique")


class ArtifactDefinition(StrictModel):
    id: Identifier
    path: str
    kind: Literal["text", "binary"]
    install_mode: Literal[0o644, 0o755]
    template_blob: BlobRef
    context: ContextName | None = None
    substitutions: tuple[SubstitutionDefinition, ...] = ()

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_repo_path(value)

    @model_validator(mode="after")
    def validate_shape(self) -> ArtifactDefinition:
        _unique_substitution_names(self.substitutions)
        if self.substitutions and self.context is None:
            raise ValueError("artifacts with substitutions must declare a context")
        return self


class SlotDefinition(StrictModel):
    id: Identifier
    owner_artifact: Identifier
    context: ContextName
    cardinality: CardinalityName
    separator: str = ""
    allowed_contribution_kind: Identifier | None = None


class ContributionDefinition(StrictModel):
    id: Identifier
    slot: Identifier
    order: int
    kind: Identifier
    body_blob: BlobRef
    substitutions: tuple[SubstitutionDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_shape(self) -> ContributionDefinition:
        _unique_substitution_names(self.substitutions)
        return self


class DocumentFragmentDefinition(StrictModel):
    id: Identifier
    document: str
    order: int
    body_blob: BlobRef
    substitutions: tuple[SubstitutionDefinition, ...] = ()

    @field_validator("document")
    @classmethod
    def validate_document(cls, value: str) -> str:
        return _validate_repo_path(value)

    @model_validator(mode="after")
    def validate_shape(self) -> DocumentFragmentDefinition:
        _unique_substitution_names(self.substitutions)
        return self


class CoreDefinition(StrictModel):
    artifacts: tuple[ArtifactDefinition, ...] = ()
    slots: tuple[SlotDefinition, ...] = ()
    contributions: tuple[ContributionDefinition, ...] = ()
    document_fragments: tuple[DocumentFragmentDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_core(self) -> CoreDefinition:
        for values, label in (
            ([artifact.id for artifact in self.artifacts], "artifacts"),
            ([slot.id for slot in self.slots], "slots"),
            ([contribution.id for contribution in self.contributions], "contributions"),
            (
                [fragment.id for fragment in self.document_fragments],
                "document_fragments",
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"core {label} ids must be unique")
        artifact_ids = {artifact.id for artifact in self.artifacts}
        for slot in self.slots:
            if slot.owner_artifact not in artifact_ids:
                raise ValueError(
                    f"slot owner artifact is missing: {slot.owner_artifact}"
                )
        slot_ids = {slot.id for slot in self.slots}
        for contribution in self.contributions:
            if contribution.slot not in slot_ids:
                raise ValueError(f"contribution slot is missing: {contribution.slot}")
        return self


class CapabilityDefinition(StrictModel):
    id: Identifier
    description: str = ""
    artifacts: tuple[ArtifactDefinition, ...] = ()
    contributions: tuple[ContributionDefinition, ...] = ()
    document_fragments: tuple[DocumentFragmentDefinition, ...] = ()

    @model_validator(mode="after")
    def validate_unique_members(self) -> CapabilityDefinition:
        for values, label in (
            ([artifact.id for artifact in self.artifacts], "artifacts"),
            ([contribution.id for contribution in self.contributions], "contributions"),
            (
                [fragment.id for fragment in self.document_fragments],
                "document_fragments",
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"capability {label} ids must be unique")
        return self


@dataclass(frozen=True, slots=True)
class ResolvedContribution:
    slot: str
    owner: str
    contribution_id: str
    order: int
    kind: str
    rendered_body: str


SLOT_MARKER_PREFIX = "agentic-template:slot:"
VALUE_MARKER_PREFIX = "agentic-template:value:"
OPTIONAL_SECTION_PREFIX = "agentic-template:if:"
OPTIONAL_SECTION_BEGIN_SUFFIX = ":begin"
OPTIONAL_SECTION_END_SUFFIX = ":end"

_SLOT_MARKER = re.compile(rb"agentic-template:slot:([a-z][a-z0-9-]*)")
_VALUE_MARKER = re.compile(rb"agentic-template:value:([a-z][a-z0-9-]*)")
_OPTIONAL_SECTION_MARKER = re.compile(
    rb"agentic-template:if:([a-z][a-z0-9-]*):(begin|end)\b"
)

_YAML_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_YAML_RESERVED = frozenset(
    {"true", "false", "yes", "no", "on", "off", "y", "n", "null", "~"}
)
_NUMERIC = re.compile(r"-?\d+(?:\.\d+)?")


def _yaml_scalar(value: str) -> str:
    if (
        _YAML_PLAIN_SAFE.fullmatch(value) is not None
        and value not in _YAML_RESERVED
        and _NUMERIC.fullmatch(value) is None
    ):
        return value
    return "'" + value.replace("'", "''") + "'"


def _toml_scalar(value: str) -> str:
    escaped: list[str] = []
    for char in value:
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\t":
            escaped.append("\\t")
        elif char == "\r":
            escaped.append("\\r")
        elif ord(char) < 0x20:
            escaped.append(f"\\u{ord(char):04x}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _shell_scalar(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _boolean_text(value: bool) -> str:
    return "true" if value else "false"


def encode_scalar(value: SettingValue, context: ContextName) -> str:
    """Encode a normalized scalar value for the declared template context."""
    match context:
        case "yaml":
            return (
                _yaml_scalar(value) if isinstance(value, str) else _boolean_text(value)
            )
        case "toml":
            return (
                _toml_scalar(value) if isinstance(value, str) else _boolean_text(value)
            )
        case "json":
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        case "shell":
            return (
                _shell_scalar(value) if isinstance(value, str) else _boolean_text(value)
            )
        case "markdown":
            return value if isinstance(value, str) else _boolean_text(value)
        case _:  # pragma: no cover
            return assert_never(context)  # pragma: no cover


def resolve_substitution_value(
    source: SubstitutionSource,
    settings: Mapping[str, Mapping[str, SettingValue]],
    project: ProjectInfo,
    maintenance: MaintenanceInfo,
) -> Result[SettingValue, RenderError]:
    match source:
        case SettingSource(capability=capability_id, setting=setting_name):
            values = settings.get(capability_id)
            if values is None or setting_name not in values:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "missing_substitution_value",
                        f"{capability_id}.{setting_name}",
                    )
                )
            return Ok(values[setting_name])
        case ProjectSource(key=key):
            match key:
                case "name":
                    return Ok(project.name)
                case "default_branch":
                    return Ok(project.default_branch)
                case _:  # pragma: no cover
                    return assert_never(key)  # pragma: no cover
        case MaintenanceSource(key=key):
            match key:
                case "status":
                    return Ok(maintenance.status)
                case "retained_paths":
                    return Ok(
                        "\n".join(path.value for path in maintenance.retained_paths)
                    )
                case _:  # pragma: no cover
                    return assert_never(key)  # pragma: no cover
        case _:  # pragma: no cover
            return assert_never(source)  # pragma: no cover


def apply_substitutions(
    template: bytes,
    substitutions: tuple[SubstitutionDefinition, ...],
    *,
    context: ContextName,
    settings: Mapping[str, Mapping[str, SettingValue]],
    project: ProjectInfo,
    maintenance: MaintenanceInfo,
) -> Result[bytes, RenderError]:
    """Replace every value marker with its context-encoded substitution value."""
    by_name = {substitution.name: substitution for substitution in substitutions}
    result: list[bytes] = []
    position = 0
    for match in _VALUE_MARKER.finditer(template):
        name = match.group(1).decode("ascii")
        substitution = by_name.get(name)
        if substitution is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "unknown_substitution", name
                )
            )
        match resolve_substitution_value(
            substitution.source, settings, project, maintenance
        ):
            case Ok(value):
                encoded = encode_scalar(value, context).encode("utf-8")
            case Err(error):
                return Err(error)
        result.append(template[position : match.start()])
        result.append(encoded)
        position = match.end()
    result.append(template[position:])
    return Ok(b"".join(result))


@dataclass(frozen=True, slots=True)
class RenderInput:
    render_input_version: int
    generation_path: GenerationPath
    project: ProjectInfo
    licensing: LicensingInfo
    profile: ProfileInfo
    additions: tuple[str, ...]
    effective: tuple[str, ...]
    definitions: Mapping[str, CapabilityDefinition]
    core: CoreDefinition
    settings: Mapping[str, Mapping[str, SettingValue]]
    contributions: tuple[ResolvedContribution, ...]
    documents: Mapping[RepoPath, tuple[str, ...]]
    maintenance: MaintenanceInfo
    slots: Mapping[str, SlotContent]

    def __post_init__(self) -> None:
        if not isinstance(self.generation_path, GenerationPath):
            raise ValueError("generation_path must be a GenerationPath")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", self.project.name):
            raise ValueError("project name is outside the ASCII class")
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.project.default_branch
        ):
            raise ValueError("default_branch is outside the ASCII class")
        if self.licensing.mode not in {
            "retain-apache-2.0",
            "provided-project-license",
            "private",
        }:
            raise ValueError("licensing mode is outside the closed vocabulary")
        identifier = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
        for capability_id in (*self.effective, *self.additions):
            if identifier.fullmatch(capability_id) is None:
                raise ValueError("capability id is outside the identifier class")
        for digest in (
            self.licensing.content_sha256,
            *(slot.content_sha256 for slot in self.slots.values()),
        ):
            if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("content digest must be a 64-hex sha256")
        for slot in self.slots.values():
            if slot.mode not in {"file", "scaffold"}:
                raise ValueError("slot mode is outside the closed vocabulary")
        for path in self.maintenance.retained_paths:
            if not isinstance(parse_path(path.value), Ok):
                raise ValueError("retained path must be repository-relative")
        for path in self.documents:
            if not isinstance(parse_path(path.value), Ok):
                raise ValueError("document path must be repository-relative")
        object.__setattr__(
            self, "definitions", MappingProxyType(dict(self.definitions))
        )
        object.__setattr__(
            self,
            "settings",
            MappingProxyType(
                {
                    capability_id: MappingProxyType(dict(values))
                    for capability_id, values in self.settings.items()
                }
            ),
        )
        object.__setattr__(self, "documents", MappingProxyType(dict(self.documents)))
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))


@dataclass(frozen=True, slots=True)
class ManagedFile:
    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    content: bytes


ManagedRender = tuple[ManagedFile, ...]


@dataclass(frozen=True, slots=True)
class ManagedInventoryEntry:
    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    sha256: str


ManagedInventory = tuple[ManagedInventoryEntry, ...]


def derive_managed_inventory(managed: ManagedRender) -> ManagedInventory:
    return tuple(
        ManagedInventoryEntry(
            path=file.path,
            kind=file.kind,
            mode=file.mode,
            sha256=content_identity(
                file.content, text=file.kind == "text"
            ).normalized_sha256,
        )
        for file in managed
    )


def _remove_marker_line(content: bytes, marker: bytes) -> bytes:
    """Remove a whole-line marker plus its line's newline."""
    start = content.find(marker)
    end = start + len(marker)
    if content[end : end + 1] == b"\n":
        return content[:start] + content[end + 1 :]
    if start > 0 and content[start - 1 : start] == b"\n":
        return content[: start - 1] + content[end:]
    return content[:start] + content[end:]


def _apply_optional_sections(
    content: bytes,
    substitutions_by_name: Mapping[str, SubstitutionDefinition],
    render_input: RenderInput,
) -> Result[bytes, RenderError]:
    sections: list[tuple[str, bytes, bytes]] = []
    stack: list[tuple[str, bytes]] = []
    for match in _OPTIONAL_SECTION_MARKER.finditer(content):
        name = match.group(1).decode("ascii")
        kind = match.group(2).decode("ascii")
        if name not in substitutions_by_name:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "unknown_substitution", name
                )
            )
        if kind == "begin":
            if stack:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "nested_optional_section",
                        name,
                    )
                )
            stack.append((name, match.group(0)))
        else:
            if not stack:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "unbalanced_optional_section",
                        name,
                    )
                )
            begin_name, begin_marker = stack.pop()
            if begin_name != name:
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "unbalanced_optional_section",
                        name,
                    )
                )
            sections.append((name, begin_marker, match.group(0)))
    if stack:
        name = stack[0][0]
        return Err(
            RenderError(
                RenderErrorKind.INVALID_TEMPLATE, "unbalanced_optional_section", name
            )
        )
    result = content
    for name, begin_marker, end_marker in sections:
        match resolve_substitution_value(
            substitutions_by_name[name].source,
            render_input.settings,
            render_input.project,
            render_input.maintenance,
        ):
            case Ok(value) if isinstance(value, bool):
                keep = value
            case Ok(_):
                return Err(
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "optional_section_requires_boolean",
                        name,
                    )
                )
            case Err(error):
                return Err(error)
        if keep:
            result = _remove_marker_line(result, begin_marker)
            result = _remove_marker_line(result, end_marker)
        else:
            start = result.find(begin_marker)
            end = result.find(end_marker, start)
            if start < 0 or end < 0:  # pragma: no cover
                return Err(  # pragma: no cover
                    RenderError(
                        RenderErrorKind.INVALID_TEMPLATE,
                        "unbalanced_optional_section",
                        name,
                    )
                )
            line_start = result.rfind(b"\n", 0, start) + 1
            line_end = result.find(b"\n", end)
            if line_end < 0:
                line_end = len(result)
            else:
                line_end += 1
            result = result[:line_start] + result[line_end:]
    return Ok(result)


def _apply_slot_markers(
    content: bytes,
    artifact: ArtifactDefinition,
    render_input: RenderInput,
    slots_by_id: Mapping[str, SlotDefinition],
) -> Result[bytes, RenderError]:
    contributions_by_slot: dict[str, list[ResolvedContribution]] = {}
    for contribution in render_input.contributions:
        contributions_by_slot.setdefault(contribution.slot, []).append(contribution)
    result: list[bytes] = []
    position = 0
    for match in _SLOT_MARKER.finditer(content):
        slot_id = match.group(1).decode("ascii")
        slot = slots_by_id.get(slot_id)
        if slot is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "unknown_slot_marker", slot_id
                )
            )
        if slot.owner_artifact != artifact.id:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "slot_not_owned_by_artifact",
                    slot_id,
                )
            )
        bodies = contributions_by_slot.get(slot_id, ())
        joined = slot.separator.join(
            contribution.rendered_body for contribution in bodies
        )
        result.append(content[position : match.start()])
        result.append(joined.encode("utf-8"))
        position = match.end()
    result.append(content[position:])
    for slot_id, bodies in contributions_by_slot.items():
        if not bodies:  # pragma: no cover
            continue  # pragma: no cover
        slot = slots_by_id.get(slot_id)
        if slot is None or slot.owner_artifact != artifact.id:
            continue
        marker = (SLOT_MARKER_PREFIX + slot_id).encode("utf-8")
        if marker not in content:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE, "missing_slot_marker", slot_id
                )
            )
    return Ok(b"".join(result))


def _render_artifact(
    artifact: ArtifactDefinition,
    render_input: RenderInput,
    slots_by_id: Mapping[str, SlotDefinition],
    blobs: VerifiedBlobStore,
) -> Result[bytes, RenderError]:
    template = blobs.get(artifact.template_blob)
    if template is None:  # pragma: no cover
        return Err(  # pragma: no cover
            RenderError(RenderErrorKind.MISSING_BLOB, "", artifact.path)
        )
    substitutions_by_name = {
        substitution.name: substitution for substitution in artifact.substitutions
    }
    match _apply_optional_sections(template, substitutions_by_name, render_input):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
    match _apply_slot_markers(content, artifact, render_input, slots_by_id):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
    if _VALUE_MARKER.search(content):
        if artifact.context is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "missing_artifact_context",
                    artifact.path,
                )
            )
        match apply_substitutions(
            content,
            artifact.substitutions,
            context=artifact.context,
            settings=render_input.settings,
            project=render_input.project,
            maintenance=render_input.maintenance,
        ):
            case Err(error):
                return Err(error)
            case Ok(substituted):
                content = substituted
    if artifact.kind == "text":
        try:
            return Ok(normalize_text(content))
        except ValueError:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "text_artifact_encoding",
                    artifact.path,
                )
            )
    return Ok(content)


def render_managed(
    render_input: RenderInput,
    blobs: VerifiedBlobStore,
) -> Result[ManagedRender, RenderError]:
    """Render every whole managed artifact and document from explicit inputs and blobs."""
    if render_input.render_input_version != 1:
        return Err(
            RenderError(
                RenderErrorKind.INVALID_TEMPLATE,
                "unsupported_render_input_version",
                str(render_input.render_input_version),
            )
        )
    effective_definitions: list[tuple[str, CapabilityDefinition]] = []
    for capability_id in render_input.effective:
        definition = render_input.definitions.get(capability_id)
        if definition is None:
            return Err(
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "missing_capability_definition",
                    capability_id,
                )
            )
        effective_definitions.append((capability_id, definition))
    owner_pairs: list[tuple[str, tuple[ArtifactDefinition, ...]]] = [
        ("core", render_input.core.artifacts),
        *(
            (capability_id, definition.artifacts)
            for capability_id, definition in effective_definitions
        ),
    ]
    for _owner, artifacts in owner_pairs:
        for artifact in artifacts:
            if blobs.get(artifact.template_blob) is None:
                return Err(RenderError(RenderErrorKind.MISSING_BLOB, "", artifact.path))
    seen_paths: dict[str, str] = {}
    for owner, artifacts in owner_pairs:
        for artifact in artifacts:
            previous = seen_paths.get(artifact.path)
            if previous is not None and previous != owner:
                return Err(
                    RenderError(RenderErrorKind.OWNERSHIP_COLLISION, "", artifact.path)
                )
            seen_paths[artifact.path] = owner
    slots_by_id = {slot.id: slot for slot in render_input.core.slots}
    files: list[ManagedFile] = []
    for _owner, artifacts in owner_pairs:
        for artifact in sorted(artifacts, key=lambda item: item.path.encode("utf-8")):
            match _render_artifact(artifact, render_input, slots_by_id, blobs):
                case Err(error):
                    return Err(error)
                case Ok(content):
                    files.append(
                        ManagedFile(
                            path=RepoPath(artifact.path),
                            kind=artifact.kind,
                            mode=PosixMode(artifact.install_mode),
                            content=content,
                        )
                    )
    declared_documents = {
        fragment.document for fragment in render_input.core.document_fragments
    }
    for _capability_id, definition in effective_definitions:
        declared_documents.update(
            fragment.document for fragment in definition.document_fragments
        )
    for path in sorted(
        render_input.documents, key=lambda item: item.value.encode("utf-8")
    ):
        if path.value in seen_paths:
            return Err(RenderError(RenderErrorKind.PATH_COLLISION, "", path.value))
        if path.value not in declared_documents:
            return Err(RenderError(RenderErrorKind.UNDECLARED_OUTPUT, "", path.value))
        body = "\n\n".join(render_input.documents[path])
        try:
            content = normalize_text(body.encode("utf-8"))
        except ValueError:  # pragma: no cover
            return Err(  # pragma: no cover
                RenderError(
                    RenderErrorKind.INVALID_TEMPLATE,
                    "text_artifact_encoding",
                    path.value,
                )
            )
        files.append(
            ManagedFile(path=path, kind="text", mode=PosixMode.FILE, content=content)
        )
    return Ok(tuple(sorted(files, key=lambda file: file.path.value.encode("utf-8"))))


TemplateBlobMap = VerifiedBlobStore
AdopterBlobMap = VerifiedBlobStore
