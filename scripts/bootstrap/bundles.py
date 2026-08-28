"""Pure input-boundary decoding for bootstrap answer bundles."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.contributions import render_generation
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
from scripts.bootstrap.observation import (
    LifecycleSourceFile,
    collect_template_source_entries_with_content,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.planner import (
    CleanMaintenance,
    CollisionAction,
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
    ManagedFile,
    ManagedRender,
    ProfileInfo,
    ProjectInfo,
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


def _read_bundle_relative_file(
    root: str, relative: str, subject: str
) -> Result[bytes, InputError]:
    """Read one bundle file below a no-follow directory descriptor."""

    parent_fds: list[int] = []
    file_fd = -1
    try:
        current = os.open(
            os.path.abspath(root),
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        parent_fds.append(current)
        components = tuple(os.fsencode(part) for part in relative.split("/"))
        for component in components[:-1]:
            current = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            parent_fds.append(current)
        file_fd = os.open(
            components[-1],
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=current,
        )
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return Err(InputError(InputErrorKind.WRONG_KIND, subject))
            with os.fdopen(file_fd, "rb") as handle:
                file_fd = -1
                content = handle.read(DEFAULT_LIMITS.max_file_bytes + 1)
        finally:
            if file_fd >= 0:
                os.close(file_fd)
    except FileNotFoundError:
        return Err(InputError(InputErrorKind.MISSING_INPUT, subject))
    except OSError:
        return Err(InputError(InputErrorKind.WRONG_KIND, subject))
    finally:
        for fd in reversed(parent_fds):
            os.close(fd)
    if len(content) > DEFAULT_LIMITS.max_file_bytes:
        return Err(InputError(InputErrorKind.INPUT_LIMIT_EXCEEDED, subject))
    return Ok(content)


def _read_bundle_file(path: str, subject: str) -> Result[bytes, InputError]:
    absolute = os.path.abspath(path)
    return _read_bundle_relative_file(
        os.path.dirname(absolute), os.path.basename(absolute), subject
    )


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
    match _read_bundle_relative_file(root, relative.value, relative.value):
        case Err(error):
            return Err(error)
        case Ok(content):
            pass
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


def _lifecycle_install_set(
    pairs: tuple[LifecycleSourceFile, ...],
) -> Result[ManagedRender, CommandError]:
    """Build the adoption lifecycle install set from collected template source.

    The set is every declared lifecycle source file plus a regular-file
    ``CLAUDE.md`` carrying the template AGENTS.md bytes; directory entries and
    reserved seed/managed paths never reach this boundary.
    """
    files: list[ManagedFile] = []
    agents_content: bytes | None = None
    for pair in pairs:
        entry = pair.entry
        content = pair.content
        if content is None:
            continue
        if entry.path.value == "CLAUDE.md":
            return Err(
                ContractError(
                    ContractErrorKind.INVALID_TEMPLATE,
                    "lifecycle path CLAUDE.md is not installable",
                )
            )
        try:
            _ = content.decode("utf-8")
            kind: Literal["text", "binary"] = "text"
        except UnicodeDecodeError:
            kind = "binary"
        files.append(
            ManagedFile(path=entry.path, kind=kind, mode=entry.mode, content=content)
        )
        if entry.path.value == "AGENTS.md":
            agents_content = content
    if agents_content is None:
        return Err(
            ContractError(
                ContractErrorKind.INVALID_TEMPLATE,
                "lifecycle install set missing AGENTS.md",
            )
        )
    files.append(
        ManagedFile(
            path=RepoPath("CLAUDE.md"),
            kind="text",
            mode=PosixMode.FILE,
            content=agents_content,
        )
    )
    return Ok(tuple(sorted(files, key=lambda file: file.path.value.encode("utf-8"))))


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
    collisions: Mapping[str, CollisionAction] | None = None,
    lifecycle: ManagedRender | None = None,
) -> Result[tuple[OperationPlan, MechanicalReadinessResult], CommandError]:
    """Compile the complete initial plan for one generation path."""

    blobs = VerifiedBlobStore.empty(limits)
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
    match render_generation(
        generation_path=generation,
        core=core_definition(),
        definitions=capability_definitions(),
        effective=resolved.effective,
        settings=resolved.settings,
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
        maintenance=maintenance_info,
        slots=answers.slots,
        blobs=blobs,
    ):
        case Err(error):
            return Err(
                ContractError(
                    ContractErrorKind.RENDER_CONTRACT_VIOLATION,
                    f"{error.kind.value}:{error.reason or ''}:{error.subject}",
                )
            )
        case Ok(managed):
            pass
    match collect_template_source_entries_with_content(
        template_root,
        managed_paths={file.path for file in managed},
        limits=limits,
    ):
        case Err(error):
            return Err(error)
        case Ok(pairs):
            pass
    source_entries = tuple(pair.entry for pair in pairs)
    # The adoption declare policy is always in force: an absent map declares
    # nothing, so every collision still refuses the plan.
    if collisions is None and generation is GenerationPath.ADOPTED:
        collisions = {}
    if lifecycle is None and generation is GenerationPath.ADOPTED:
        match _lifecycle_install_set(pairs):
            case Err(error):
                return Err(error)
            case Ok(install_set):
                lifecycle = install_set
    match compile_initial_plan(
        generation=generation,
        target_identity=target_identity,
        answers=answers,
        additions=ManifestAdditions(),
        seed_once=seed_once,
        managed=managed,
        blobs=blobs,
        source_entries=source_entries,
        snapshot_commit=snapshot_commit,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=snapshot,
        limits=limits,
        collisions=collisions,
        lifecycle=lifecycle if lifecycle is not None else (),
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


def compile_adoption_install(
    *,
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
    """Compile the complete adoption plan for one manifest-free working tree.

    Adoption records ``GenerationPath.ADOPTED`` provenance and applies the
    conflict policy declared in the bundle's answer document: every planned
    output meeting observed content must be declared ``keep-existing`` or
    ``replace`` before anything is installed.
    """
    collisions: dict[str, CollisionAction] = (
        {}
        if decoded.bundle.collisions is None
        else dict(decoded.bundle.collisions.root)
    )
    return compile_initial_install(
        generation=GenerationPath.ADOPTED,
        decoded=decoded,
        resolved=resolved,
        scaffold=scaffold,
        template_root=template_root,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=snapshot,
        target_identity=target_identity,
        snapshot_commit=snapshot_commit,
        limits=limits,
        collisions=collisions,
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
