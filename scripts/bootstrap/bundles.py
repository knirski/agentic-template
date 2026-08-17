"""Pure input-boundary decoding for bootstrap answer bundles."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
    template_bodies,
)
from scripts.bootstrap.contributions import (
    compose_contributions,
    compose_document_bodies,
)
from scripts.bootstrap.errors import (
    CommandError,
    ContractError,
    ContractErrorKind,
    InputError,
    InputErrorKind,
)
from scripts.bootstrap.identity import PosixMode, TargetIdentity, sha256_hex
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    LicensingRecord,
    ManifestAdditions,
    ManifestAnswers,
    ProfileSelection,
    ProjectFacts,
    SlotContent,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.planner import (
    CleanMaintenance,
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    ExpectedGatePass,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    RetainMaintenance,
    SeedOnceInput,
    TargetSnapshot,
    apply_plan,
    compile_initial_plan,
    evaluate_expected,
    legal_output_paths,
)
from scripts.bootstrap.readiness import MechanicalReadinessResult
from scripts.bootstrap.render import (
    LicensingInfo,
    MaintenanceInfo,
    ProfileInfo,
    ProjectInfo,
    RenderInput,
    render_managed,
)
from scripts.bootstrap.resolver import ResolvedBundle, resolve_bundle
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import SEED_ONCE_SLOTS
from scripts.bootstrap.schemas import BootstrapBundle, FileContent, ScaffoldContent
from scripts.bootstrap.state import CleanupContract
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits

HOOK_PATH = RepoPath("scripts/validate-project")
_BUNDLE_FILE = "bootstrap.json"


def decode_bundle(value: Mapping[str, object]) -> BootstrapBundle:
    """Decode a primitive mapping without reading or executing referenced content."""

    return BootstrapBundle.model_validate(value)


@dataclass(frozen=True, slots=True)
class DecodedBundle:
    """The strict decoded bootstrap bundle plus its bounded content bytes."""

    bundle: BootstrapBundle
    document: dict[str, object]
    content: dict[RepoPath, tuple[bytes, Literal["text", "binary"]]]
    bundle_digest: str


def _read_bundle_file(path: str, subject: str) -> Result[bytes, InputError]:
    try:
        with open(path, "rb") as handle:
            content = handle.read()
    except OSError:
        return Err(InputError(InputErrorKind.MISSING_INPUT, subject))
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return Err(InputError(InputErrorKind.INPUT_LIMIT_EXCEEDED, subject))
    return Ok(content)


def _bundle_json_path(bundle_path: str) -> str:
    return (
        os.path.join(bundle_path, _BUNDLE_FILE)
        if os.path.isdir(bundle_path)
        else bundle_path
    )


def _input_error_from_validation(error: Exception) -> InputError:
    return InputError(InputErrorKind.SCHEMA_VIOLATION, str(error)[:200])


def _read_content_slot(
    root: str,
    raw_path: str,
    *,
    text: bool,
) -> Result[tuple[bytes, Literal["text", "binary"]], InputError]:
    match parse_path(raw_path):
        case Err(_):
            return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, raw_path))
        case Ok(relative):
            pass
    absolute = os.path.normpath(os.path.join(root, relative.value))
    if not absolute.startswith(
        os.path.normpath(root) + os.sep
    ) and absolute != os.path.normpath(root):
        return Err(InputError(InputErrorKind.UNSAFE_RELATIVE_PATH, raw_path))
    match _read_bundle_file(absolute, relative.value):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        return Err(InputError(InputErrorKind.WRONG_KIND, relative.value))
    if text:
        try:
            _ = content.decode("utf-8")
        except UnicodeDecodeError:
            return Err(InputError(InputErrorKind.INVALID_ENCODING, relative.value))
    return Ok((content, "text" if text else "binary"))


def _declared_markers() -> tuple[tuple[RepoPath, bytes], ...]:
    from scripts.bootstrap.planner import SLOT_PLACEHOLDER_RULES

    return tuple((rule.path, rule.marker) for rule in SLOT_PLACEHOLDER_RULES)


def decode_bundle_input(
    bundle_path: str,
) -> Result[DecodedBundle, InputError]:
    """Strictly decode a bundle file and its referenced content, rejecting markers."""

    json_path = _bundle_json_path(bundle_path)
    match _read_bundle_file(json_path, json_path):
        case Err(error):
            return Err(error)
        case Ok(raw):
            pass
    try:
        value = decode_json(raw)
    except ValueError:
        return Err(InputError(InputErrorKind.INVALID_JSON, json_path))
    if not isinstance(value, dict):
        return Err(InputError(InputErrorKind.SCHEMA_VIOLATION, json_path))
    try:
        bundle = BootstrapBundle.model_validate(value)
    except Exception as error:
        return Err(_input_error_from_validation(error))
    root = os.path.dirname(os.path.abspath(json_path))
    content: dict[RepoPath, tuple[bytes, Literal["text", "binary"]]] = {}
    declared_paths: set[RepoPath] = set()
    for slot_path in SEED_ONCE_SLOTS.values():
        choice = cast(
            FileContent | ScaffoldContent,
            getattr(bundle.content, _slot_attr(slot_path)),
        )
        if isinstance(choice, ScaffoldContent):
            continue
        match _read_content_slot(root, choice.path, text=True):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        if RepoPath(choice.path) in declared_paths:
            return Err(InputError(InputErrorKind.MARKER_COLLISION, choice.path))
        declared_paths.add(RepoPath(choice.path))
        content[slot_path] = entry
    if bundle.licensing.path is not None:
        match _read_content_slot(root, bundle.licensing.path, text=True):
            case Err(error):
                return Err(error)
            case Ok(entry):
                pass
        license_path = RepoPath(bundle.licensing.path)
        if license_path in declared_paths:
            return Err(
                InputError(InputErrorKind.MARKER_COLLISION, bundle.licensing.path)
            )
        content[license_path] = entry
    for path, marker in _declared_markers():
        for slot_path, (file_bytes, _kind) in content.items():
            if path == HOOK_PATH:
                found = marker in file_bytes
            else:
                found = marker.decode("ascii") in file_bytes.decode("utf-8")
            if found:
                return Err(InputError(InputErrorKind.MARKER_COLLISION, slot_path.value))
    document = bundle.model_dump(mode="json")
    match resolve_bundle(bundle):
        case Err(failure):
            return Err(
                InputError(
                    InputErrorKind.SCHEMA_VIOLATION,
                    f"{failure.kind.value}:{failure.subject}",
                )
            )
        case Ok(_):
            pass
    return Ok(
        DecodedBundle(
            bundle=bundle,
            document=document,
            content=content,
            bundle_digest=sha256_hex(canonical_json(document)),
        )
    )


def _slot_attr(path: RepoPath) -> str:
    for slot_id, slot_path in SEED_ONCE_SLOTS.items():
        if slot_path == path:
            return slot_id
    raise KeyError(path.value)


def _read_template_file(template_root: str, relative: str) -> bytes | None:
    absolute = os.path.join(template_root, relative)
    try:
        with open(absolute, "rb") as handle:
            content = handle.read()
    except OSError:
        return None
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return None
    return content


def _seed_once_inputs(
    decoded: DecodedBundle,
    scaffold: dict[RepoPath, bytes],
    blobs: VerifiedBlobStore,
    _limits: ResourceLimits,
    template_root: str,
) -> Result[tuple[tuple[SeedOnceInput, ...], VerifiedBlobStore], CommandError]:
    seed_inputs: list[SeedOnceInput] = []
    store = blobs
    for path in sorted(SEED_ONCE_SLOTS.values(), key=lambda p: p.value.encode()):
        slot_id = _slot_attr(path)
        choice = cast(
            FileContent | ScaffoldContent, getattr(decoded.bundle.content, slot_id)
        )
        executable = path == HOOK_PATH
        if isinstance(choice, ScaffoldContent):
            content = scaffold.get(path)
            if content is None:
                return Err(
                    ContractError(
                        ContractErrorKind.INVALID_TEMPLATE,
                        f"scaffold content missing for {path.value}",
                    )
                )
        else:
            content = decoded.content[path][0]
        match store.intern(content):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        seed_inputs.append(
            SeedOnceInput(
                path=path,
                kind="binary" if executable else "text",
                mode=PosixMode.EXECUTABLE if executable else PosixMode.FILE,
                content_id=content_id,
            )
        )
    legal_paths = legal_output_paths(decoded.bundle.licensing.mode)
    if legal_paths is None:
        return Err(ContractError(ContractErrorKind.INVALID_TEMPLATE, "licensing.mode"))
    for path in legal_paths:
        if path.value == "LICENSE" and decoded.bundle.licensing.path is not None:
            content = decoded.content[path][0]
        else:
            content = _read_template_file(template_root, path.value)
            if content is None:
                return Err(
                    ContractError(
                        ContractErrorKind.INVALID_TEMPLATE,
                        f"retained legal content missing: {path.value}",
                    )
                )
        match store.intern(content):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        seed_inputs.append(
            SeedOnceInput(
                path=path, kind="text", mode=PosixMode.FILE, content_id=content_id
            )
        )
    seed_inputs.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    return Ok((tuple(seed_inputs), store))


def _manifest_answers(
    decoded: DecodedBundle, resolved: ResolvedBundle
) -> ManifestAnswers:
    slots: dict[str, SlotContent] = {}
    for slot_id, path in SEED_ONCE_SLOTS.items():
        choice = cast(
            FileContent | ScaffoldContent, getattr(decoded.bundle.content, slot_id)
        )
        if isinstance(choice, ScaffoldContent):
            slots[slot_id] = SlotContent(mode="scaffold", content_sha256=None)
        else:
            slots[slot_id] = SlotContent(
                mode="file", content_sha256=sha256_hex(decoded.content[path][0])
            )
    licensing = decoded.bundle.licensing
    return ManifestAnswers(
        project=ProjectFacts(
            name=decoded.bundle.project.name,
            default_branch=decoded.bundle.project.default_branch,
        ),
        profile=ProfileSelection(id=resolved.profile_id, requested=resolved.requested),
        settings=resolved.settings,
        licensing=LicensingRecord(
            mode=licensing.mode,
            content_sha256=(
                sha256_hex(decoded.content[RepoPath(licensing.path)][0])
                if licensing.path is not None
                else None
            ),
        ),
        slots=slots,
    )


def compile_initial_install(
    *,
    generation: GenerationPath,
    decoded: DecodedBundle,
    resolved: ResolvedBundle,
    scaffold: dict[RepoPath, bytes],
    template_root: str,
    maintenance: CleanMaintenance | RetainMaintenance,
    cleanup: CleanupContract | None,
    snapshot: TargetSnapshot,
    target_identity: TargetIdentity,
    snapshot_commit: str | None,
    limits: ResourceLimits,
) -> Result[tuple[OperationPlan, MechanicalReadinessResult], CommandError]:
    """Compile the complete initial plan for one generation path."""

    blobs = VerifiedBlobStore.empty(limits)
    for content in template_bodies().values():
        match blobs.intern(content):
            case Err(error):
                return Err(error)
            case Ok((_content_id, updated)):
                blobs = updated
    match _seed_once_inputs(decoded, scaffold, blobs, limits, template_root):
        case Err(error):
            return Err(error)
        case Ok((seed_once, updated)):
            blobs = updated
    answers = _manifest_answers(decoded, resolved)
    project = ProjectInfo(
        name=decoded.bundle.project.name,
        default_branch=decoded.bundle.project.default_branch,
    )
    licensing = decoded.bundle.licensing
    maintenance_info = MaintenanceInfo(
        status=("retained" if isinstance(maintenance, RetainMaintenance) else "clean"),
        retained_paths=(
            maintenance.paths if isinstance(maintenance, RetainMaintenance) else ()
        ),
    )
    profile = ProfileInfo(id=resolved.profile_id, frozen=resolved.requested)
    # The generated ci.yml and every selected capability workflow are compiled
    # per-profile managed output: adopters receive only their selected profile,
    # and drift in the managed CI is detected by the standard status/restore
    # machinery rather than by a conformance fixture.
    core = core_definition()
    definitions = capability_definitions()
    match compose_contributions(
        core,
        definitions,
        resolved.effective,
        resolved.settings,
        project,
        maintenance_info,
        blobs,
    ):
        case Err(error):
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    f"{error.kind.value}:{error.subject}",
                )
            )
        case Ok(contributions):
            pass
    match compose_document_bodies(
        core,
        definitions,
        resolved.effective,
        resolved.settings,
        project,
        maintenance_info,
        blobs,
    ):
        case Err(error):
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    f"{error.kind.value}:{error.subject}",
                )
            )
        case Ok(documents):
            pass
    render_input = RenderInput(
        render_input_version=1,
        generation_path=generation,
        project=project,
        licensing=LicensingInfo(
            mode=licensing.mode,
            content_sha256=(
                sha256_hex(decoded.content[RepoPath(licensing.path)][0])
                if licensing.path is not None
                else None
            ),
        ),
        profile=profile,
        additions=(),
        effective=resolved.effective,
        definitions=definitions,
        core=core,
        settings=resolved.settings,
        contributions=contributions,
        documents=dict(documents),
        maintenance=maintenance_info,
        slots=answers.slots,
    )
    match render_managed(render_input, blobs):
        case Err(error):
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    f"{error.kind.value}:{error.subject}",
                )
            )
        case Ok(managed):
            pass
    match compile_initial_plan(
        generation=generation,
        target_identity=target_identity,
        answers=answers,
        additions=ManifestAdditions(),
        seed_once=seed_once,
        managed=managed,
        blobs=blobs,
        source_entries=(),
        snapshot_commit=snapshot_commit,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=snapshot,
        limits=limits,
    ):
        case Err(error):
            kind = (
                ContractErrorKind.CLEANUP_CONTRACT_INVALID
                if error.kind.value == "cleanup_disagreement"
                else ContractErrorKind.INVALID_OPERATION_PLAN
            )
            return Err(ContractError(kind, error.subject))
        case Ok(plan):
            pass
    match apply_plan(snapshot, plan):
        case Err(error):
            return Err(
                ContractError(ContractErrorKind.INVALID_OPERATION_PLAN, error.subject)
            )
        case Ok(expected_target):
            pass
    match evaluate_expected(expected_target):
        case ExpectedGatePass(readiness):
            return Ok((plan, readiness))
        case _refusal:
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    "expected target fails the template contract",
                )
            )


def plan_snapshot_paths(plan: OperationPlan) -> tuple[set[RepoPath], set[RepoPath]]:
    """Return the file and directory paths the plan's preconditions reference."""

    file_paths: set[RepoPath] = set()
    dir_paths: set[RepoPath] = set()
    for operation in plan.ordered_operations:
        match operation:
            case (
                CreateFileOperation(path=path)
                | ReplaceFileOperation(path=path)
                | DeleteFileOperation(path=path)
            ):
                file_paths.add(path)
            case CreateTreeOperation(root=root, planned_new=tree):
                dir_paths.add(root)
                for entry in tree.entries:
                    match entry:
                        case PlannedFileEntry(path=path):
                            file_paths.add(path)
                        case PlannedDirectoryEntry(path=path):
                            dir_paths.add(path)
            case RemoveEmptyDirectoryOperation(path=path):
                dir_paths.add(path)
    return file_paths, dir_paths
