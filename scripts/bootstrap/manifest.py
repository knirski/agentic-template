"""Candidate project manifest: primary recorded state, checksum, and strict round trips.

``.agentic-template/project.json`` contains only primary recorded fields plus its checksum;
it has no derived block.  Validity is parse, schema, and checksum — nothing else.  The
document never contains product prose, legal text, input source paths, repository owner or
name, timestamps, machine-specific absolute paths, secrets, or claims about seed-once
content; legal and seed-once inputs appear only as content digests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, assert_never, cast

from scripts.bootstrap.canonical_json import (
    StrictJsonValue,
    canonical_json,
    decode_object,
)
from scripts.bootstrap.identity import InstallFileMode, PosixMode, manifest_identity
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.paths import RepoPath, parse_path, path_byte_key, sorted_paths
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
    SourceBaseline,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits
from scripts.bootstrap.vocabulary import (
    BRANCH_NAME,
    COMMIT_SHA,
    IDENTIFIER,
    LICENSING_MODES,
    PROJECT_NAME,
    SETTING_NAME,
    SHA256,
    SLOT_MODES,
    is_sha256,
)

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_PATH = RepoPath(".agentic-template/project.json")

# The five content slots of the bootstrap input bundle; their installed paths and
# placeholder markers are fixed by the design's declared-placeholder-marker table.
SLOT_IDS = frozenset(
    {"readme", "prd", "security_policy", "contributing", "validation_hook"}
)


@dataclass(frozen=True, slots=True)
class SlotContent:
    mode: str
    content_sha256: str | None


@dataclass(frozen=True, slots=True)
class ManagedInventoryEntry:
    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    sha256: str


type ManagedInventory = tuple[ManagedInventoryEntry, ...]

_MAINTENANCE_STATUSES = frozenset({"clean", "retained"})
INSTALL_MODES = InstallFileMode


class ManifestErrorKind(StrEnum):
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    INVALID_JSON = "invalid_json"
    SCHEMA_VIOLATION = "schema_violation"
    CHECKSUM_MISMATCH = "checksum_mismatch"


@dataclass(frozen=True, slots=True)
class ManifestError:
    kind: ManifestErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    name: str
    default_branch: str


@dataclass(frozen=True, slots=True)
class ProfileSelection:
    id: str
    requested: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LicensingRecord:
    mode: str
    content_sha256: str | None


@dataclass(frozen=True, slots=True)
class ManifestAnswers:
    project: ProjectFacts
    profile: ProfileSelection
    settings: Mapping[str, Mapping[str, str | bool]]
    licensing: LicensingRecord
    slots: Mapping[str, SlotContent]

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze_settings(self.settings))
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))


@dataclass(frozen=True, slots=True)
class ManifestAdditions:
    requested: tuple[str, ...] = ()
    settings: Mapping[str, Mapping[str, str | bool]] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze_settings(self.settings))


@dataclass(frozen=True, slots=True)
class MaintenanceRecord:
    status: Literal["clean", "retained"]
    retained_paths: tuple[RepoPath, ...] = ()


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    generation_path: GenerationPath
    maintenance: MaintenanceRecord
    source_baseline: SourceBaseline


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    schema_version: int
    answers: ManifestAnswers
    additions: ManifestAdditions
    provenance: ProvenanceRecord
    managed: ManagedInventory


def _freeze_settings(
    settings: Mapping[str, Mapping[str, str | bool]],
) -> Mapping[str, Mapping[str, str | bool]]:
    return MappingProxyType(
        {
            capability_id: MappingProxyType(dict(values))
            for capability_id, values in settings.items()
        }
    )


def _manifest_error(kind: ManifestErrorKind, subject: str = "") -> ManifestError:
    return ManifestError(kind, subject)


def _sorted_unique_paths(paths: tuple[RepoPath, ...]) -> tuple[RepoPath, ...]:
    return sorted_paths(set(paths))


def path_within_limits(path: RepoPath, limits: ResourceLimits = DEFAULT_LIMITS) -> bool:
    """Return whether a path satisfies the v1 path-byte, component, and component-count limits."""
    if len(path.value.encode("utf-8")) > limits.max_path_bytes:
        return False
    components = path.value.split("/")
    if len(components) > limits.max_components:
        return False
    return all(
        len(component.encode("utf-8")) <= limits.max_component_bytes
        for component in components
    )


def _is_sha256(value: object) -> bool:
    return is_sha256(value)


def _is_identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _is_setting_name(value: object) -> bool:
    return isinstance(value, str) and SETTING_NAME.fullmatch(value) is not None


def _validate_identifier_list(
    values: tuple[str, ...], subject: str
) -> Result[tuple[str, ...], ManifestError]:
    if tuple(sorted(set(values))) != values:
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    for value in values:
        if not _is_identifier(value):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    return Ok(values)


def _validate_settings(
    settings: Mapping[str, Mapping[str, str | bool]],
) -> Result[Mapping[str, Mapping[str, str | bool]], ManifestError]:
    for capability_id, values in settings.items():
        if not _is_identifier(capability_id) or any(
            not _is_setting_name(name)
            or not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
                value, (str, bool)
            )
            for name, value in values.items()
        ):
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION,
                    f"settings.{capability_id}",
                )
            )
    return Ok(settings)


def _validate_managed(
    managed: ManagedInventory,
) -> Result[ManagedInventory, ManifestError]:
    seen_paths: set[str] = set()
    lowered: set[str] = set()
    for entry in managed:
        if entry.path.value in seen_paths or entry.path.value.lower() in lowered:
            return Err(
                _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, entry.path.value)
            )
        seen_paths.add(entry.path.value)
        lowered.add(entry.path.value.lower())
        match parse_path(entry.path.value):
            case Ok(_):
                pass
            case Err(_):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, entry.path.value
                    )
                )
        if (
            entry.kind not in ("text", "binary")
            or entry.mode not in INSTALL_MODES
            or SHA256.fullmatch(entry.sha256) is None
        ):
            return Err(
                _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, entry.path.value)
            )
    if tuple(sorted(managed, key=lambda entry: path_byte_key(entry.path))) != managed:
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "managed"))
    return Ok(managed)


def _validate_answers(
    answers: ManifestAnswers,
) -> Result[ManifestAnswers, ManifestError]:
    if PROJECT_NAME.fullmatch(answers.project.name) is None:
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "project.name"))
    if BRANCH_NAME.fullmatch(answers.project.default_branch) is None:
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, "project.default_branch"
            )
        )
    if not _is_identifier(answers.profile.id):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "profile.id"))
    match _validate_identifier_list(answers.profile.requested, "profile.requested"):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    if answers.licensing.mode not in LICENSING_MODES:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "licensing.mode")
        )
    if answers.licensing.content_sha256 is not None and not _is_sha256(
        answers.licensing.content_sha256
    ):
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, "licensing.content_sha256"
            )
        )
    match _validate_settings(answers.settings):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    for slot_id, content in answers.slots.items():
        if slot_id not in SLOT_IDS or content.mode not in SLOT_MODES:
            return Err(
                _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, f"slots.{slot_id}")
            )
        if content.content_sha256 is not None and not _is_sha256(
            content.content_sha256
        ):
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION,
                    f"slots.{slot_id}.content_sha256",
                )
            )
    return Ok(answers)


def _validate_provenance(
    provenance: ProvenanceRecord,
) -> Result[ProvenanceRecord, ManifestError]:
    if provenance.generation_path not in (GenerationPath.GITHUB, GenerationPath.COPIER):
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "generation_path")
        )
    if provenance.maintenance.status not in _MAINTENANCE_STATUSES:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "maintenance.status")
        )
    retained = provenance.maintenance.retained_paths
    for path in retained:
        match parse_path(path.value):
            case Ok(_):
                pass
            case Err(_):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "maintenance.retained_paths"
                    )
                )
    if _sorted_unique_paths(retained) != retained:
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, "maintenance.retained_paths"
            )
        )
    baseline = provenance.source_baseline
    match baseline:
        case GitHubSourceBaseline():
            if (
                provenance.generation_path is not GenerationPath.GITHUB
                or COMMIT_SHA.fullmatch(baseline.snapshot_commit) is None
            ):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline"
                    )
                )
        case CopierSourceBaseline():
            if provenance.generation_path is not GenerationPath.COPIER:
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline"
                    )
                )
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            return Err(  # pragma: no cover  # pyright: ignore[reportUnreachable] — unreachable only because recommended mode proves the match exhaustive
                _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline")
            )
    if SHA256.fullmatch(baseline.fingerprint) is None:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline")
        )
    seen_paths: set[str] = set()
    for entry in baseline.entries:
        if entry.path.value in seen_paths:
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline.entries"
                )
            )
        seen_paths.add(entry.path.value)
        match parse_path(entry.path.value):
            case Ok(_):
                pass
            case Err(_):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline.entries"
                    )
                )
        if (
            entry.kind not in ("file", "directory")
            or entry.mode not in INSTALL_MODES
            or (entry.kind == "directory" and entry.mode != PosixMode.DIRECTORY)
            or SHA256.fullmatch(entry.sha256) is None
        ):
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION, "source_baseline.entries"
                )
            )
    return Ok(provenance)


def build_candidate_manifest(
    *,
    answers: ManifestAnswers,
    additions: ManifestAdditions,
    provenance: ProvenanceRecord,
    managed: ManagedInventory,
) -> Result[CandidateManifest, ManifestError]:
    """Validate primary values and freeze them into one schema-v1 candidate manifest."""
    match _validate_answers(answers):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_identifier_list(additions.requested, "additions.requested"):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_settings(additions.settings):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    overlapping = set(answers.settings).intersection(additions.settings)
    if overlapping:
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION,
                f"settings.{sorted(overlapping)[0]}",
            )
        )
    match _validate_provenance(provenance):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_managed(managed):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    return Ok(
        CandidateManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            answers=answers,
            additions=additions,
            provenance=provenance,
            managed=managed,
        )
    )


def baseline_document(baseline: SourceBaseline) -> dict[str, object]:
    """Canonical source-baseline document shared by the manifest and the plan receipt."""
    entries = [
        {
            "path": entry.path.value,
            "kind": entry.kind,
            "mode": entry.mode.value,
            "sha256": entry.sha256,
        }
        for entry in baseline.entries
    ]
    match baseline:
        case GitHubSourceBaseline():
            return {
                "kind": "github",
                "fingerprint": baseline.fingerprint,
                "entries": entries,
                "snapshot_commit": baseline.snapshot_commit,
            }
        case CopierSourceBaseline():
            return {
                "kind": "copier",
                "fingerprint": baseline.fingerprint,
                "entries": entries,
            }
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            return assert_never(
                baseline
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — unreachable only because recommended mode proves the match exhaustive


def manifest_document(manifest: CandidateManifest) -> dict[str, object]:
    """Return the canonical document value that the checksum tags (checksum excluded)."""
    return {
        "schema_version": manifest.schema_version,
        "answers": {
            "project": {
                "name": manifest.answers.project.name,
                "default_branch": manifest.answers.project.default_branch,
            },
            "profile": {
                "id": manifest.answers.profile.id,
                "requested": list(manifest.answers.profile.requested),
            },
            "settings": {
                capability_id: dict(values)
                for capability_id, values in manifest.answers.settings.items()
            },
            "licensing": {
                "mode": manifest.answers.licensing.mode,
                "content_sha256": manifest.answers.licensing.content_sha256,
            },
            "slots": {
                slot_id: {
                    "mode": content.mode,
                    "content_sha256": content.content_sha256,
                }
                for slot_id, content in manifest.answers.slots.items()
            },
        },
        "additions": {
            "requested": list(manifest.additions.requested),
            "settings": {
                capability_id: dict(values)
                for capability_id, values in manifest.additions.settings.items()
            },
        },
        "provenance": {
            "generation_path": manifest.provenance.generation_path.value,
            "maintenance": {
                "status": manifest.provenance.maintenance.status,
                "retained_paths": [
                    path.value
                    for path in manifest.provenance.maintenance.retained_paths
                ],
            },
            "source_baseline": baseline_document(manifest.provenance.source_baseline),
        },
        "managed": [
            {
                "path": entry.path.value,
                "kind": entry.kind,
                "mode": entry.mode.value,
                "sha256": entry.sha256,
            }
            for entry in manifest.managed
        ],
    }


def manifest_checksum(document: Mapping[str, object]) -> str:
    """Tag the canonical document bytes; the checksum field itself is never hashed."""
    return manifest_identity(document).digest


def encode_manifest(manifest: CandidateManifest) -> bytes:
    """Serialize the candidate manifest with its checksum as canonical JSON bytes."""
    document = manifest_document(manifest)
    return canonical_json({**document, "checksum": manifest_checksum(document)})


def decode_manifest(data: bytes) -> Result[CandidateManifest, ManifestError]:
    """Strictly decode a manifest: parse, schema, and checksum are the only validity."""

    def _reason(reason: str) -> ManifestError:
        if reason == "json":
            return _manifest_error(ManifestErrorKind.INVALID_JSON)
        return _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, reason)

    match decode_object(
        data,
        error=_reason,
        max_bytes=DEFAULT_LIMITS.max_file_bytes,
        allowed_keys=frozenset(
            {
                "schema_version",
                "answers",
                "additions",
                "provenance",
                "managed",
                "checksum",
            }
        ),
    ):
        case Err(error):
            return Err(error)
        case Ok(value):
            pass
    schema_version = value.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        return Err(
            _manifest_error(
                ManifestErrorKind.UNSUPPORTED_SCHEMA_VERSION, str(schema_version)
            )
        )
    checksum = value.get("checksum")
    if not _is_sha256(checksum):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "checksum"))
    document = {key: item for key, item in value.items() if key != "checksum"}
    if manifest_checksum(document) != checksum:
        return Err(_manifest_error(ManifestErrorKind.CHECKSUM_MISMATCH))
    match _decode_answers(document.get("answers")):
        case Err(error):
            return Err(error)
        case Ok(answers):
            pass
    match _decode_additions(document.get("additions")):
        case Err(error):
            return Err(error)
        case Ok(additions):
            pass
    match _decode_provenance(document.get("provenance")):
        case Err(error):
            return Err(error)
        case Ok(provenance):
            pass
    match _decode_managed(document.get("managed")):
        case Err(error):
            return Err(error)
        case Ok(managed):
            pass
    # Decode and build must share one schema: re-run the build-side invariants.
    candidate = CandidateManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        answers=answers,
        additions=additions,
        provenance=provenance,
        managed=managed,
    )
    match build_candidate_manifest(
        answers=candidate.answers,
        additions=candidate.additions,
        provenance=candidate.provenance,
        managed=candidate.managed,
    ):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    return Ok(candidate)


def _expect_mapping(
    value: StrictJsonValue, subject: str
) -> Result[dict[str, StrictJsonValue], ManifestError]:
    if not isinstance(value, Mapping):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    return Ok(dict(value))


def _expect_closed_mapping(
    value: StrictJsonValue, subject: str, allowed: frozenset[str]
) -> Result[dict[str, StrictJsonValue], ManifestError]:
    """Require an exact key set so decode accepts only documents the builder emits."""
    match _expect_mapping(value, subject):
        case Err(error):
            return Err(error)
        case Ok(mapping):
            pass
    if set(mapping) != set(allowed):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    return Ok(mapping)


def _decode_string_list(
    value: StrictJsonValue, subject: str
) -> Result[tuple[str, ...], ManifestError]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    return Ok(cast(tuple[str, ...], tuple(value)))


def _decode_settings(
    value: StrictJsonValue, subject: str
) -> Result[Mapping[str, Mapping[str, str | bool]], ManifestError]:
    match _expect_mapping(value, subject):
        case Err(error):
            return Err(error)
        case Ok(mapping):
            pass
    settings: dict[str, Mapping[str, str | bool]] = {}
    for capability_id, raw_values in mapping.items():
        match _expect_mapping(raw_values, f"{subject}.{capability_id}"):
            case Err(error):
                return Err(error)
            case Ok(values):
                pass
        if not _is_identifier(capability_id):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
        decoded_values: dict[str, str | bool] = {}
        for name, item in values.items():
            if not _is_setting_name(name) or not isinstance(item, (str, bool)):
                return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
            decoded_values[name] = item
        settings[capability_id] = MappingProxyType(decoded_values)
    return Ok(MappingProxyType(settings))


def _decode_slot(
    value: StrictJsonValue, slot_id: str
) -> Result[SlotContent, ManifestError]:
    match _expect_closed_mapping(
        value, f"answers.slots.{slot_id}", frozenset({"mode", "content_sha256"})
    ):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
    mode = content.get("mode")
    digest = content.get("content_sha256")
    if (
        not isinstance(mode, str)
        or mode not in SLOT_MODES
        or (digest is not None and not _is_sha256(digest))
    ):
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, f"answers.slots.{slot_id}"
            )
        )
    return Ok(
        SlotContent(
            mode=mode,
            content_sha256=digest if isinstance(digest, str) else None,
        )
    )


def _decode_answers(value: StrictJsonValue) -> Result[ManifestAnswers, ManifestError]:
    match _expect_closed_mapping(
        value,
        "answers",
        frozenset({"project", "profile", "licensing", "settings", "slots"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(answers):
            pass
    match _expect_closed_mapping(
        answers.get("project"),
        "answers.project",
        frozenset({"name", "default_branch"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(project):
            pass
    name = project.get("name")
    default_branch = project.get("default_branch")
    if not isinstance(name, str) or not isinstance(default_branch, str):
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "answers.project")
        )
    match _expect_closed_mapping(
        answers.get("profile"),
        "answers.profile",
        frozenset({"id", "requested"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(profile):
            pass
    profile_id = profile.get("id")
    if not isinstance(profile_id, str):
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "answers.profile")
        )
    match _decode_string_list(profile.get("requested"), "answers.profile.requested"):
        case Err(error):
            return Err(error)
        case Ok(requested):
            pass
    match _expect_closed_mapping(
        answers.get("licensing"),
        "answers.licensing",
        frozenset({"mode", "content_sha256"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(licensing):
            pass
    licensing_mode = licensing.get("mode")
    raw_license_digest = licensing.get("content_sha256")
    if not isinstance(licensing_mode, str) or licensing_mode not in LICENSING_MODES:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "answers.licensing")
        )
    if raw_license_digest is None:
        license_digest: str | None = None
    elif isinstance(raw_license_digest, str) and SHA256.fullmatch(raw_license_digest):
        license_digest = raw_license_digest
    else:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "answers.licensing")
        )
    match _decode_settings(answers.get("settings"), "answers.settings"):
        case Err(error):
            return Err(error)
        case Ok(settings):
            pass
    match _expect_mapping(answers.get("slots"), "answers.slots"):
        case Err(error):
            return Err(error)
        case Ok(slots):
            pass
    decoded_slots: dict[str, SlotContent] = {}
    for slot_id, raw_content in slots.items():
        if slot_id not in SLOT_IDS:
            return Err(
                _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "answers.slots")
            )
        match _decode_slot(raw_content, slot_id):
            case Err(error):
                return Err(error)
            case Ok(content):
                decoded_slots[slot_id] = content
    return Ok(
        ManifestAnswers(
            project=ProjectFacts(name=name, default_branch=default_branch),
            profile=ProfileSelection(id=profile_id, requested=requested),
            settings=settings,
            licensing=LicensingRecord(
                mode=licensing_mode, content_sha256=license_digest
            ),
            slots=MappingProxyType(decoded_slots),
        )
    )


def _decode_additions(
    value: StrictJsonValue,
) -> Result[ManifestAdditions, ManifestError]:
    match _expect_closed_mapping(
        value, "additions", frozenset({"requested", "settings"})
    ):
        case Err(error):
            return Err(error)
        case Ok(additions):
            pass
    match _decode_string_list(additions.get("requested"), "additions.requested"):
        case Err(error):
            return Err(error)
        case Ok(requested):
            pass
    match _decode_settings(additions.get("settings"), "additions.settings"):
        case Err(error):
            return Err(error)
        case Ok(settings):
            pass
    return Ok(ManifestAdditions(requested=requested, settings=settings))


def _decode_retained_paths(
    value: StrictJsonValue,
) -> Result[tuple[RepoPath, ...], ManifestError]:
    match _decode_string_list(value, "provenance.maintenance.retained_paths"):
        case Err(error):
            return Err(error)
        case Ok(paths):
            pass
    decoded: list[RepoPath] = []
    for path in paths:
        match parse_path(path):
            case Err(_):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION,
                        "provenance.maintenance.retained_paths",
                    )
                )
            case Ok(parsed):
                pass
        if not path_within_limits(parsed):
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION,
                    "provenance.maintenance.retained_paths",
                )
            )
        decoded.append(parsed)
    return Ok(tuple(decoded))


def _decode_source_entries(
    value: StrictJsonValue, subject: str
) -> Result[tuple[LifecycleSourceEntry, ...], ManifestError]:
    if not isinstance(value, list):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
    entries: list[LifecycleSourceEntry] = []
    for raw_entry in value:
        match _expect_closed_mapping(
            raw_entry, subject, frozenset({"path", "kind", "mode", "sha256"})
        ):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        path = entry.get("path")
        kind = entry.get("kind")
        mode = entry.get("mode")
        raw_digest = entry.get("sha256")
        if (
            not isinstance(path, str)
            or kind not in ("file", "directory")
            or not isinstance(mode, int)
            or mode not in INSTALL_MODES
            or (kind == "directory" and mode != PosixMode.DIRECTORY)
            or not isinstance(raw_digest, str)
            or SHA256.fullmatch(raw_digest) is None
        ):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
        match parse_path(path):
            case Err(_):
                return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
            case Ok(parsed):
                pass
        if not path_within_limits(parsed):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, subject))
        if kind == "file":
            entry_kind: Literal["file", "directory"] = "file"
        else:
            entry_kind = "directory"
        entries.append(
            LifecycleSourceEntry(
                path=parsed,
                kind=entry_kind,
                mode=PosixMode(mode),
                sha256=raw_digest,
            )
        )
    return Ok(tuple(entries))


def _decode_provenance(
    value: StrictJsonValue,
) -> Result[ProvenanceRecord, ManifestError]:
    match _expect_closed_mapping(
        value,
        "provenance",
        frozenset({"generation_path", "maintenance", "source_baseline"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(provenance):
            pass
    generation = provenance.get("generation_path")
    if not isinstance(generation, str):
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "generation_path")
        )
    try:
        generation_path = GenerationPath(generation)
    except ValueError:
        return Err(
            _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "generation_path")
        )
    match _expect_closed_mapping(
        provenance.get("maintenance"),
        "provenance.maintenance",
        frozenset({"status", "retained_paths"}),
    ):
        case Err(error):
            return Err(error)
        case Ok(maintenance):
            pass
    status_value = maintenance.get("status")
    match status_value:
        case "clean":
            status: Literal["clean", "retained"] = "clean"
        case "retained":
            status = "retained"
        case _:
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION, "maintenance.status"
                )
            )
    match _decode_retained_paths(maintenance.get("retained_paths")):
        case Err(error):
            return Err(error)
        case Ok(retained_paths):
            pass
    match _expect_mapping(
        provenance.get("source_baseline"), "provenance.source_baseline"
    ):
        case Err(error):
            return Err(error)
        case Ok(baseline):
            pass
    raw_fingerprint = baseline.get("fingerprint")
    if (
        not isinstance(raw_fingerprint, str)
        or SHA256.fullmatch(raw_fingerprint) is None
    ):
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, "provenance.source_baseline"
            )
        )
    match _decode_source_entries(
        baseline.get("entries"), "provenance.source_baseline.entries"
    ):
        case Err(error):
            return Err(error)
        case Ok(entries):
            pass
    match baseline.get("kind"):
        case "github":
            snapshot_commit = baseline.get("snapshot_commit")
            if (
                not isinstance(snapshot_commit, str)
                or COMMIT_SHA.fullmatch(snapshot_commit) is None
            ):
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "provenance.source_baseline"
                    )
                )
            source_baseline: SourceBaseline = GitHubSourceBaseline(
                kind="github",
                fingerprint=raw_fingerprint,
                entries=entries,
                snapshot_commit=snapshot_commit,
            )
        case "copier":
            if "snapshot_commit" in baseline:
                return Err(
                    _manifest_error(
                        ManifestErrorKind.SCHEMA_VIOLATION, "provenance.source_baseline"
                    )
                )
            source_baseline = CopierSourceBaseline(
                kind="copier", fingerprint=raw_fingerprint, entries=entries
            )
        case _:
            return Err(
                _manifest_error(
                    ManifestErrorKind.SCHEMA_VIOLATION, "provenance.source_baseline"
                )
            )
    baseline_keys = (
        frozenset({"kind", "fingerprint", "entries", "snapshot_commit"})
        if baseline.get("kind") == "github"
        else frozenset({"kind", "fingerprint", "entries"})
    )
    if set(baseline) != set(baseline_keys):
        return Err(
            _manifest_error(
                ManifestErrorKind.SCHEMA_VIOLATION, "provenance.source_baseline"
            )
        )
    return Ok(
        ProvenanceRecord(
            generation_path=generation_path,
            maintenance=MaintenanceRecord(status=status, retained_paths=retained_paths),
            source_baseline=source_baseline,
        )
    )


def _decode_managed(value: StrictJsonValue) -> Result[ManagedInventory, ManifestError]:
    if not isinstance(value, list):
        return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "managed"))
    entries: list[ManagedInventoryEntry] = []
    for raw_entry in value:
        match _expect_closed_mapping(
            raw_entry, "managed", frozenset({"path", "kind", "mode", "sha256"})
        ):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        path = entry.get("path")
        kind = entry.get("kind")
        mode = entry.get("mode")
        raw_digest = entry.get("sha256")
        if (
            not isinstance(path, str)
            or kind not in ("text", "binary")
            or not isinstance(mode, int)
            or mode not in INSTALL_MODES
            or not isinstance(raw_digest, str)
            or SHA256.fullmatch(raw_digest) is None
        ):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "managed"))
        match parse_path(path):
            case Err(_):
                return Err(
                    _manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "managed")
                )
            case Ok(parsed):
                pass
        if not path_within_limits(parsed):
            return Err(_manifest_error(ManifestErrorKind.SCHEMA_VIOLATION, "managed"))
        if kind == "text":
            entry_kind: Literal["text", "binary"] = "text"
        else:
            entry_kind = "binary"
        entries.append(
            ManagedInventoryEntry(
                path=parsed,
                kind=entry_kind,
                mode=PosixMode(mode),
                sha256=raw_digest,
            )
        )
    return Ok(tuple(entries))
