"""Pure initial-install compiler: the complete OperationPlan, ExpectedTarget, and gate binding.

``compile_initial_plan`` places every seed-once, legal, managed, manifest, cleanup, and
directory effect into one complete, deterministically ordered ``OperationPlan``;
``apply_plan`` overlays the plan on the observed target to obtain the byte-exposing
``ExpectedTarget``; ``evaluate_expected`` runs the frozen bootstrap slot rules and the
template contract over that target.  The plan never stores adopter or legal prose: planned
files carry content ids into the plan's verified blob store, and the byte-erased receipt is
derived in ``plan_digest``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, assert_never

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticSeverity,
    NoAutomaticAction,
)
from scripts.bootstrap.identity import (
    DirectoryEntry,
    DirectoryState,
    FileContentIdentity,
    FileEntry,
    FileState,
    InstallFileMode,
    ManifestIdentity,
    PosixMode,
    TargetIdentity,
    content_identity,
    directory_tree_hash,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    MaintenanceRecord,
    ManifestAdditions,
    ManifestAnswers,
    ProvenanceRecord,
    build_candidate_manifest,
    encode_manifest,
    manifest_checksum,
    manifest_document,
    path_within_limits,
)
from scripts.bootstrap.ownership import validate_cleanup_contract
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.readiness import Finding, MechanicalReadinessResult, SubjectPath
from scripts.bootstrap.render import (
    ManagedRender,
    SlotContent,
    derive_managed_inventory,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.source_baseline import (
    LifecycleSourceEntry,
    SourceBaseline,
    derive_source_baseline,
)
from scripts.bootstrap.state import CleanupContract
from scripts.bootstrap.template_contract import required_contract_failures
from scripts.bootstrap.values import (
    DEFAULT_LIMITS,
    LimitKind,
    ResourceLimits,
    check_limit,
)
from scripts.bootstrap.vocabulary import LICENSING_MODES, PATH_BEARING_LICENSING_MODES

PLAN_SCHEMA_VERSION = 1
PLAN_OPERATION_KIND: Literal["initial"] = "initial"
MAINTENANCE_INVENTORY_PATH = RepoPath(".agentic-template/maintenance-artifacts.json")


class CompileErrorKind(StrEnum):
    INVALID_TARGET = "invalid_target"
    PATH_COLLISION = "path_collision"
    MISSING_BLOB = "missing_blob"
    CLEANUP_DISAGREEMENT = "cleanup_disagreement"
    INVALID_MAINTENANCE = "invalid_maintenance"
    INVALID_SOURCE_BASELINE = "invalid_source_baseline"
    INVALID_MANIFEST = "invalid_manifest"
    PLAN_LIMIT_EXCEEDED = "plan_limit_exceeded"


@dataclass(frozen=True, slots=True)
class CompileError:
    kind: CompileErrorKind
    subject: str = ""


class PlanInvariantErrorKind(StrEnum):
    UNMATCHED_PRECONDITION = "unmatched_precondition"
    MISSING_BLOB = "missing_blob"
    DUPLICATE_PATH = "duplicate_path"


@dataclass(frozen=True, slots=True)
class PlanInvariantError:
    kind: PlanInvariantErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class SeedOnceInput:
    """A byte-addressed adopter seed-once or legal output for the initial install."""

    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    content_id: ContentId


@dataclass(frozen=True, slots=True)
class CleanMaintenance:
    pass


@dataclass(frozen=True, slots=True)
class RetainMaintenance:
    paths: tuple[RepoPath, ...]


type MaintenanceDecision = CleanMaintenance | RetainMaintenance


@dataclass(frozen=True, slots=True)
class ObservedFileEntry:
    path: RepoPath
    state: FileState
    content: bytes


@dataclass(frozen=True, slots=True)
class ObservedDirectoryEntry:
    path: RepoPath
    state: DirectoryState


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    """Immutable observation of exactly the paths the initial plan depends on."""

    files: tuple[ObservedFileEntry, ...] = ()
    directories: tuple[ObservedDirectoryEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedFilePresent:
    identity: FileContentIdentity
    mode: PosixMode
    content_id: ContentId


@dataclass(frozen=True, slots=True)
class FileAbsent:
    pass


type PlannedFileState = FileAbsent | PlannedFilePresent


@dataclass(frozen=True, slots=True)
class CreateFileOperation:
    path: RepoPath
    expected_old: FileState
    planned_new: PlannedFilePresent


@dataclass(frozen=True, slots=True)
class ReplaceFileOperation:
    path: RepoPath
    expected_old: FileState
    planned_new: PlannedFilePresent


@dataclass(frozen=True, slots=True)
class DeleteFileOperation:
    path: RepoPath
    expected_old: FileState
    planned_new: FileAbsent


type FileOperation = CreateFileOperation | ReplaceFileOperation | DeleteFileOperation


@dataclass(frozen=True, slots=True)
class PlannedDirectoryEntry:
    path: RepoPath
    mode: PosixMode


@dataclass(frozen=True, slots=True)
class PlannedFileEntry:
    path: RepoPath
    identity: FileContentIdentity
    mode: PosixMode
    content_id: ContentId


PlannedTreeEntry = PlannedDirectoryEntry | PlannedFileEntry


@dataclass(frozen=True, slots=True)
class MaterializedTree:
    root: RepoPath
    root_mode: PosixMode
    entries: tuple[PlannedTreeEntry, ...]
    raw_tree_sha256: str


@dataclass(frozen=True, slots=True)
class CreateTreeOperation:
    root: RepoPath
    expected_old: DirectoryState | None
    planned_new: MaterializedTree


@dataclass(frozen=True, slots=True)
class DirectoryAbsent:
    pass


@dataclass(frozen=True, slots=True)
class RemoveEmptyDirectoryOperation:
    path: RepoPath
    expected_old: DirectoryState
    planned_new: DirectoryAbsent


type DirectoryOperation = CreateTreeOperation | RemoveEmptyDirectoryOperation


class ReadinessRule(StrEnum):
    INITIAL_EQUALITY = "initial-equality"
    NO_WORSE_BLOCKING = "no-worse-blocking"


@dataclass(frozen=True, slots=True)
class GateSpecification:
    operation: Literal["initial", "add", "restore", "reconcile"]
    artifact_verification: bool
    template_contract: bool
    readiness_rule: ReadinessRule
    expected_placeholder: tuple[Finding, ...]


@dataclass(frozen=True, slots=True)
class OperationPlan:
    plan_schema: int
    operation_kind: Literal["initial"]
    target_identity: TargetIdentity
    generation_path: GenerationPath
    source_before: SourceBaseline | None
    source_after: SourceBaseline
    manifest_before: ManifestIdentity | None
    manifest_after: ManifestIdentity
    ordered_operations: tuple[FileOperation | DirectoryOperation, ...]
    blob_store: VerifiedBlobStore
    gate_specification: GateSpecification


@dataclass(frozen=True, slots=True)
class ExpectedFile:
    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    content: bytes


@dataclass(frozen=True, slots=True)
class ExpectedTarget:
    """Pure overlay of the plan on the target; exposes bytes to validators, never persisted."""

    files: tuple[ExpectedFile, ...]
    directories: tuple[DirectoryEntry, ...]


@dataclass(frozen=True, slots=True)
class ExpectedGatePass:
    readiness: MechanicalReadinessResult


@dataclass(frozen=True, slots=True)
class ExpectedGateRefusal:
    failures: tuple[Diagnostic, ...]


type ExpectedValidation = ExpectedGatePass | ExpectedGateRefusal


@dataclass(frozen=True, slots=True)
class SlotPlaceholderRule:
    slot: str
    path: RepoPath
    marker: bytes
    detection: Literal["text", "raw"]
    code: str
    message: str
    next_action: str


SLOT_PLACEHOLDER_RULES: tuple[SlotPlaceholderRule, ...] = (
    SlotPlaceholderRule(
        slot="readme",
        path=RepoPath("README.md"),
        marker=b"<!-- agentic-template:placeholder:readme -->",
        detection="text",
        code="READINESS_README_MARKER",
        message="template replacement marker remains",
        next_action="replace the marked README with project description",
    ),
    SlotPlaceholderRule(
        slot="prd",
        path=RepoPath("docs/prd.md"),
        marker=b"<!-- agentic-template:placeholder:prd -->",
        detection="text",
        code="READINESS_PRD_MARKER",
        message="template replacement marker remains",
        next_action="replace the marked PRD with product requirements",
    ),
    SlotPlaceholderRule(
        slot="security_policy",
        path=RepoPath("SECURITY.md"),
        marker=b"<!-- agentic-template:placeholder:security -->",
        detection="text",
        code="READINESS_SECURITY_MARKER",
        message="template replacement marker remains",
        next_action="replace the marked security policy with project policy",
    ),
    SlotPlaceholderRule(
        slot="contributing",
        path=RepoPath("CONTRIBUTING.md"),
        marker=b"<!-- agentic-template:placeholder:contributing -->",
        detection="text",
        code="READINESS_CONTRIBUTING_MARKER",
        message="template replacement marker remains",
        next_action="replace the marked contributing guide with project guidance",
    ),
    SlotPlaceholderRule(
        slot="validation_hook",
        path=RepoPath("scripts/validate-project"),
        marker=b"agentic-template:unconfigured:validate-project",
        detection="raw",
        code="READINESS_HOOK_SENTINEL",
        message="unconfigured hook sentinel remains",
        next_action="replace the stub with project validation commands",
    ),
)


def _compile_error(kind: CompileErrorKind, subject: str = "") -> CompileError:
    return CompileError(kind, subject)


def _invariant_error(
    kind: PlanInvariantErrorKind, subject: str = ""
) -> PlanInvariantError:
    return PlanInvariantError(kind, subject)


def _sorted_paths(paths: tuple[RepoPath, ...]) -> tuple[RepoPath, ...]:
    return tuple(sorted(paths, key=lambda path: path.value.encode("utf-8")))


def _parent_paths(path: RepoPath) -> tuple[RepoPath, ...]:
    parts = path.value.split("/")
    return tuple(RepoPath("/".join(parts[:index])) for index in range(1, len(parts)))


def legal_output_paths(mode: str) -> tuple[RepoPath, ...] | None:
    """Return the legal/provenance seed-once paths the licensing mode requires."""
    if mode not in LICENSING_MODES:
        return None
    paths = (RepoPath("LICENSE"), RepoPath("NOTICE.md"))
    if mode in PATH_BEARING_LICENSING_MODES:
        return (*paths, RepoPath("LICENSES/Apache-2.0.txt"))
    return paths


def _placeholder_finding(rule: SlotPlaceholderRule) -> Finding:
    return Finding(
        code=rule.code,
        subject_at=SubjectPath(rule.path.value),
        subject=rule.path.value,
        rule=rule.code,
        severity="blocking",
        message=rule.message,
        next_action=rule.next_action,
    )


def predicted_placeholder_findings(
    slots: Mapping[str, SlotContent],
) -> tuple[Finding, ...]:
    """Return the blocking findings every declared scaffold slot must produce after install."""
    findings: list[Finding] = []
    for rule in SLOT_PLACEHOLDER_RULES:
        content = slots.get(rule.slot)
        if content is not None and content.mode == "scaffold":
            findings.append(_placeholder_finding(rule))
    return tuple(sorted(findings, key=lambda finding: finding.identity()))


def _resolve_planned(
    content_id: ContentId,
    kind: Literal["text", "binary"],
    mode: PosixMode,
    blobs: VerifiedBlobStore,
) -> Result[PlannedFilePresent, CompileError]:
    content = blobs.get(content_id)
    if content is None:
        return Err(_compile_error(CompileErrorKind.MISSING_BLOB, content_id.value))
    return Ok(
        PlannedFilePresent(
            identity=content_identity(content, text=kind == "text"),
            mode=mode,
            content_id=content_id,
        )
    )


def _intern_output(
    content: bytes,
    store: VerifiedBlobStore,
) -> Result[tuple[ContentId, VerifiedBlobStore], CompileError]:
    match store.intern(content):
        case Ok((content_id, updated)):
            return Ok((content_id, updated))
        case Err(error):
            return Err(
                _compile_error(CompileErrorKind.PLAN_LIMIT_EXCEEDED, error.subject)
            )


def _validate_snapshot(snapshot: TargetSnapshot) -> Result[None, CompileError]:
    seen: set[str] = set()
    lowered: set[str] = set()
    for entry in (*snapshot.files, *snapshot.directories):
        if not isinstance(parse_path(entry.path.value), Ok):
            return Err(
                _compile_error(CompileErrorKind.INVALID_TARGET, entry.path.value)
            )
        if entry.path.value in seen or entry.path.value.lower() in lowered:
            return Err(
                _compile_error(CompileErrorKind.INVALID_TARGET, entry.path.value)
            )
        seen.add(entry.path.value)
        lowered.add(entry.path.value.lower())
    if _sorted_paths(tuple(entry.path for entry in snapshot.files)) != tuple(
        entry.path for entry in snapshot.files
    ):
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "files"))
    if _sorted_paths(tuple(entry.path for entry in snapshot.directories)) != tuple(
        entry.path for entry in snapshot.directories
    ):
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "directories"))
    return Ok(None)


def _validate_seed_inputs(
    seed_once: tuple[SeedOnceInput, ...],
    blobs: VerifiedBlobStore,
    limits: ResourceLimits,
) -> Result[None, CompileError]:
    if _sorted_paths(tuple(seed.path for seed in seed_once)) != tuple(
        seed.path for seed in seed_once
    ):
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "seed_once"))
    seen: set[str] = set()
    lowered: set[str] = set()
    for seed in seed_once:
        if (
            seed.path.value in seen
            or seed.path.value.lower() in lowered
            or not path_within_limits(seed.path, limits)
        ):
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, seed.path.value))
        seen.add(seed.path.value)
        lowered.add(seed.path.value.lower())
        if (
            seed.kind not in ("text", "binary")
            or seed.mode not in InstallFileMode
            or not isinstance(parse_path(seed.path.value), Ok)
        ):
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, seed.path.value))
        content = blobs.get(seed.content_id)
        if content is None:
            return Err(_compile_error(CompileErrorKind.MISSING_BLOB, seed.path.value))
        if seed.kind == "text":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_TARGET, seed.path.value)
                )
    return Ok(None)


def _validate_managed(
    managed: ManagedRender,
    limits: ResourceLimits,
) -> Result[None, CompileError]:
    seen: set[str] = set()
    lowered: set[str] = set()
    for file in managed:
        if (
            file.path.value in seen
            or file.path.value.lower() in lowered
            or not path_within_limits(file.path, limits)
        ):
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, file.path.value))
        seen.add(file.path.value)
        lowered.add(file.path.value.lower())
        if (
            file.kind not in ("text", "binary")
            or file.mode not in InstallFileMode
            or not isinstance(parse_path(file.path.value), Ok)
        ):
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, file.path.value))
        if file.kind == "text":
            try:
                file.content.decode("utf-8")
            except UnicodeDecodeError:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_TARGET, file.path.value)
                )
    if _sorted_paths(tuple(file.path for file in managed)) != tuple(
        file.path for file in managed
    ):
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "managed"))
    return Ok(None)


def _validate_slot_coverage(
    answers: ManifestAnswers,
    seed_once: tuple[SeedOnceInput, ...],
    blobs: VerifiedBlobStore,
) -> Result[None, CompileError]:
    """Require the declared slots to match the seed inputs and their marker contract."""
    rule_slots = {rule.slot: rule for rule in SLOT_PLACEHOLDER_RULES}
    if set(answers.slots) != set(rule_slots):
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "slots"))
    legal_paths = legal_output_paths(answers.licensing.mode)
    if legal_paths is None:
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, "licensing.mode"))
    declared_paths = {rule.path for rule in SLOT_PLACEHOLDER_RULES} | set(legal_paths)
    seed_paths = {seed.path for seed in seed_once}
    if seed_paths != declared_paths:
        subject = sorted(
            seed_paths ^ declared_paths, key=lambda path: path.value.encode("utf-8")
        )[0].value
        return Err(_compile_error(CompileErrorKind.INVALID_TARGET, subject))
    by_path = {seed.path.value: seed for seed in seed_once}
    for rule in SLOT_PLACEHOLDER_RULES:
        content = answers.slots[rule.slot]
        planned = blobs.get(by_path[rule.path.value].content_id)
        if planned is None:
            return Err(_compile_error(CompileErrorKind.MISSING_BLOB, rule.path.value))
        found = rule.marker in planned
        if (content.mode == "scaffold") != found:
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, rule.path.value))
    return Ok(None)


@dataclass(frozen=True, slots=True)
class _PlannedOutput:
    path: RepoPath
    kind: Literal["text", "binary"]
    mode: PosixMode
    content_id: ContentId


def _maintenance_record(
    maintenance: MaintenanceDecision,
    cleanup: CleanupContract | None,
) -> Result[MaintenanceRecord, CompileError]:
    match maintenance:
        case CleanMaintenance():
            return Ok(MaintenanceRecord(status="clean", retained_paths=()))
        case RetainMaintenance(paths=paths):
            if cleanup is None:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_MAINTENANCE, "retain")
                )
            declared = _sorted_paths(cleanup.cleanup_paths)
            if _sorted_paths(paths) != declared:
                return Err(
                    _compile_error(
                        CompileErrorKind.INVALID_MAINTENANCE, "retained_paths"
                    )
                )
            return Ok(MaintenanceRecord(status="retained", retained_paths=declared))
    return assert_never(maintenance)  # pragma: no cover


def _build_tree(
    root: RepoPath,
    outputs: tuple[_PlannedOutput, ...],
    blobs: VerifiedBlobStore,
    observed_files: Mapping[str, ObservedFileEntry],
    observed_dirs: Mapping[str, ObservedDirectoryEntry],
) -> Result[MaterializedTree, CompileError]:
    entries: list[PlannedTreeEntry] = []
    directories: set[str] = set()
    for output in outputs:
        match _resolve_planned(output.content_id, output.kind, output.mode, blobs):
            case Err(error):
                return Err(error)
            case Ok(planned):
                pass
        entries.append(
            PlannedFileEntry(
                path=output.path,
                identity=planned.identity,
                mode=planned.mode,
                content_id=output.content_id,
            )
        )
        for parent in _parent_paths(output.path):
            if (
                parent.value != root.value
                and parent.value.startswith(root.value + "/")
                and parent.value not in directories
                and parent.value not in observed_files
                and parent.value not in observed_dirs
            ):
                directories.add(parent.value)
                entries.append(PlannedDirectoryEntry(parent, PosixMode.DIRECTORY))
    sorted_entries = tuple(
        sorted(entries, key=lambda entry: entry.path.value.encode("utf-8"))
    )
    byte_entries: list[FileEntry | DirectoryEntry] = []
    for entry in sorted_entries:
        if isinstance(entry, PlannedDirectoryEntry):
            byte_entries.append(DirectoryEntry(entry.path, entry.mode))
        else:
            content = blobs.get(entry.content_id)
            if content is None:
                return Err(
                    _compile_error(CompileErrorKind.MISSING_BLOB, entry.path.value)
                )
            byte_entries.append(FileEntry(entry.path, content, entry.mode))
    raw_tree_sha256 = directory_tree_hash(
        b"plan/tree", DirectoryState(PosixMode.DIRECTORY, tuple(byte_entries))
    )
    return Ok(
        MaterializedTree(
            root=root,
            root_mode=PosixMode.DIRECTORY,
            entries=sorted_entries,
            raw_tree_sha256=raw_tree_sha256,
        )
    )


def _classify_outputs(
    outputs: tuple[_PlannedOutput, ...],
    observed_files: Mapping[str, ObservedFileEntry],
    observed_dirs: Mapping[str, ObservedDirectoryEntry],
    blobs: VerifiedBlobStore,
    *,
    refuse_present_old: bool,
) -> Result[tuple[FileOperation, ...], CompileError]:
    operations: list[FileOperation] = []
    for output in outputs:
        if output.path.value in observed_dirs:
            return Err(
                _compile_error(CompileErrorKind.INVALID_TARGET, output.path.value)
            )
        match _resolve_planned(output.content_id, output.kind, output.mode, blobs):
            case Err(error):
                return Err(error)
            case Ok(planned):
                pass
        observed = observed_files.get(output.path.value)
        if observed is None:
            operation: FileOperation = CreateFileOperation(
                path=output.path,
                expected_old=FileState(None, None),
                planned_new=planned,
            )
        else:
            if refuse_present_old:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_TARGET, output.path.value)
                )
            operation = ReplaceFileOperation(
                path=output.path,
                expected_old=observed.state,
                planned_new=planned,
            )
        operations.append(operation)
    return Ok(tuple(operations))


def _build_trees(
    outputs: tuple[_PlannedOutput, ...],
    observed_files: Mapping[str, ObservedFileEntry],
    observed_dirs: Mapping[str, ObservedDirectoryEntry],
    blobs: VerifiedBlobStore,
) -> Result[tuple[tuple[CreateTreeOperation, ...], set[str]], CompileError]:
    """Group outputs under wholly new hierarchies; each path is covered by exactly one tree."""
    grouped: dict[str, list[_PlannedOutput]] = {}
    covered: set[str] = set()
    for output in outputs:
        chain: list[RepoPath] = []
        for parent in _parent_paths(output.path):
            if parent.value in observed_files:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_TARGET, output.path.value)
                )
            if parent.value in observed_dirs:
                # Drop every ancestor at or above an observed directory: only
                # absent parents below the nearest existing ancestor may root a tree.
                chain = []
                continue
            chain.append(parent)
        if chain:
            # One wholly new hierarchy is staged as one tree: the grouping root is
            # the highest absent directory, adjacent to the nearest existing ancestor.
            grouped.setdefault(chain[0].value, []).append(output)
            covered.add(output.path.value)
    trees: list[CreateTreeOperation] = []
    for root_value in sorted(grouped):
        root = RepoPath(root_value)
        if root.value in observed_dirs or root.value in observed_files:
            return Err(_compile_error(CompileErrorKind.INVALID_TARGET, root.value))
        match _build_tree(
            root, tuple(grouped[root_value]), blobs, observed_files, observed_dirs
        ):
            case Err(error):
                return Err(error)
            case Ok(tree):
                trees.append(
                    CreateTreeOperation(root=root, expected_old=None, planned_new=tree)
                )
    return Ok((tuple(trees), covered))


def _cleanup_operations(
    cleanup: CleanupContract,
    observed_files: Mapping[str, ObservedFileEntry],
    observed_dirs: Mapping[str, ObservedDirectoryEntry],
) -> Result[
    tuple[tuple[DeleteFileOperation, ...], tuple[RemoveEmptyDirectoryOperation, ...]],
    CompileError,
]:
    observed_cleanup = _sorted_paths(
        tuple(
            path
            for path in cleanup.cleanup_paths
            if path.value in observed_files or path.value in observed_dirs
        )
    )
    match validate_cleanup_contract(cleanup, observed_cleanup):
        case Err(mismatch):
            subject = ",".join(path.value for path in mismatch.paths)
            return Err(_compile_error(CompileErrorKind.CLEANUP_DISAGREEMENT, subject))
        case Ok(_):
            pass
    file_deletes: list[DeleteFileOperation] = []
    dir_removes: list[RemoveEmptyDirectoryOperation] = []
    cleanup_values = sorted(
        (path.value for path in cleanup.cleanup_paths),
        key=lambda value: value.encode("utf-8"),
    )
    if MAINTENANCE_INVENTORY_PATH.value in cleanup_values:
        return Err(
            _compile_error(
                CompileErrorKind.CLEANUP_DISAGREEMENT, MAINTENANCE_INVENTORY_PATH.value
            )
        )
    cleanup_set = set(cleanup_values)
    for value in cleanup_values:
        for parent in _parent_paths(RepoPath(value)):
            if parent.value in cleanup_set:
                return Err(
                    _compile_error(CompileErrorKind.CLEANUP_DISAGREEMENT, parent.value)
                )
    for path in cleanup.cleanup_paths:
        observed_file = observed_files.get(path.value)
        if observed_file is not None:
            if not observed_file.state.present:
                return Err(
                    _compile_error(CompileErrorKind.CLEANUP_DISAGREEMENT, path.value)
                )
            file_deletes.append(
                DeleteFileOperation(
                    path=path,
                    expected_old=observed_file.state,
                    planned_new=FileAbsent(),
                )
            )
            continue
        observed_dir = observed_dirs.get(path.value)
        if observed_dir is None:
            return Err(
                _compile_error(CompileErrorKind.CLEANUP_DISAGREEMENT, path.value)
            )
        prefix = path.value + "/"
        descendants = tuple(
            sorted(
                (
                    *observed_files.values(),
                    *observed_dirs.values(),
                ),
                key=lambda entry: entry.path.value.encode("utf-8"),
            )
        )
        for entry in descendants:
            if entry.path.value.startswith(prefix) and isinstance(
                entry, ObservedFileEntry
            ):
                file_deletes.append(
                    DeleteFileOperation(
                        path=entry.path,
                        expected_old=entry.state,
                        planned_new=FileAbsent(),
                    )
                )
        for entry in descendants:
            if entry.path.value.startswith(prefix) and isinstance(
                entry, ObservedDirectoryEntry
            ):
                dir_removes.append(
                    RemoveEmptyDirectoryOperation(
                        path=entry.path,
                        expected_old=DirectoryState(entry.state.root_mode, ()),
                        planned_new=DirectoryAbsent(),
                    )
                )
        dir_removes.append(
            RemoveEmptyDirectoryOperation(
                path=path,
                expected_old=DirectoryState(observed_dir.state.root_mode, ()),
                planned_new=DirectoryAbsent(),
            )
        )
    file_deletes.sort(key=lambda operation: operation.path.value.encode("utf-8"))
    return Ok((tuple(file_deletes), tuple(dir_removes)))


def _inventory_deletion(
    observed_files: Mapping[str, ObservedFileEntry],
) -> Result[DeleteFileOperation, CompileError]:
    entry = observed_files.get(MAINTENANCE_INVENTORY_PATH.value)
    if entry is None or not entry.state.present:
        return Err(
            _compile_error(
                CompileErrorKind.CLEANUP_DISAGREEMENT, MAINTENANCE_INVENTORY_PATH.value
            )
        )
    return Ok(
        DeleteFileOperation(
            path=MAINTENANCE_INVENTORY_PATH,
            expected_old=entry.state,
            planned_new=FileAbsent(),
        )
    )


def _validate_no_nested_outputs(
    outputs: tuple[_PlannedOutput, ...],
) -> Result[None, CompileError]:
    """Reject a planned output that is an ancestor of another planned output."""
    values = sorted(
        (output.path.value for output in outputs),
        key=lambda value: value.encode("utf-8"),
    )
    value_set = set(values)
    for value in values:
        for parent in _parent_paths(RepoPath(value)):
            if parent.value in value_set:
                return Err(
                    _compile_error(CompileErrorKind.INVALID_TARGET, parent.value)
                )
    return Ok(None)


def compile_initial_plan(
    *,
    generation: GenerationPath,
    target_identity: TargetIdentity,
    answers: ManifestAnswers,
    additions: ManifestAdditions,
    seed_once: tuple[SeedOnceInput, ...],
    managed: ManagedRender,
    blobs: VerifiedBlobStore,
    source_entries: tuple[LifecycleSourceEntry, ...],
    snapshot_commit: str | None,
    maintenance: MaintenanceDecision,
    cleanup: CleanupContract | None,
    snapshot: TargetSnapshot,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[OperationPlan, CompileError]:
    """Compile the complete initial plan; any error stops the flow before a mutation."""
    match _validate_snapshot(snapshot):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_seed_inputs(seed_once, blobs, limits):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_managed(managed, limits):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _validate_slot_coverage(answers, seed_once, blobs):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass

    seed_values = {seed.path.value for seed in seed_once}
    managed_values = {file.path.value for file in managed}
    collisions = (seed_values & managed_values) | (
        {MANIFEST_PATH.value} & (seed_values | managed_values)
    )
    if collisions:
        return Err(
            _compile_error(CompileErrorKind.PATH_COLLISION, sorted(collisions)[0])
        )
    if cleanup is not None:
        declared = {path.value for path in cleanup.cleanup_paths}
        collisions = declared & (seed_values | managed_values | {MANIFEST_PATH.value})
        if collisions:
            return Err(
                _compile_error(CompileErrorKind.PATH_COLLISION, sorted(collisions)[0])
            )
        for path in cleanup.cleanup_paths:
            if not path_within_limits(path, limits):
                return Err(
                    _compile_error(CompileErrorKind.CLEANUP_DISAGREEMENT, path.value)
                )

    match derive_source_baseline(
        generation, source_entries, snapshot_commit=snapshot_commit
    ):
        case Err(error):
            return Err(
                _compile_error(CompileErrorKind.INVALID_SOURCE_BASELINE, error.subject)
            )
        case Ok(source_after):
            pass

    match _maintenance_record(maintenance, cleanup):
        case Err(error):
            return Err(error)
        case Ok(maintenance_record):
            pass

    provenance = ProvenanceRecord(generation, maintenance_record, source_after)
    match build_candidate_manifest(
        answers=answers,
        additions=additions,
        provenance=provenance,
        managed=derive_managed_inventory(managed),
    ):
        case Err(error):
            return Err(_compile_error(CompileErrorKind.INVALID_MANIFEST, error.subject))
        case Ok(candidate):
            pass
    document = manifest_document(candidate)
    manifest_bytes = encode_manifest(candidate)
    manifest_after = ManifestIdentity(
        payload=manifest_bytes, digest=manifest_checksum(document)
    )

    store = VerifiedBlobStore.empty(limits)
    seed_outputs: list[_PlannedOutput] = []
    for seed in seed_once:
        content = blobs.get(seed.content_id)
        if content is None:
            return Err(_compile_error(CompileErrorKind.MISSING_BLOB, seed.path.value))
        match _intern_output(content, store):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        seed_outputs.append(_PlannedOutput(seed.path, seed.kind, seed.mode, content_id))
    managed_outputs: list[_PlannedOutput] = []
    for file in managed:
        match _intern_output(file.content, store):
            case Err(error):
                return Err(error)
            case Ok((content_id, updated)):
                store = updated
        managed_outputs.append(
            _PlannedOutput(file.path, file.kind, file.mode, content_id)
        )
    match _intern_output(manifest_bytes, store):
        case Err(error):
            return Err(error)
        case Ok((manifest_content_id, updated)):
            store = updated
    manifest_outputs = (
        _PlannedOutput(MANIFEST_PATH, "text", PosixMode.FILE, manifest_content_id),
    )

    all_outputs = tuple((*seed_outputs, *managed_outputs, *manifest_outputs))
    match _validate_no_nested_outputs(all_outputs):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass

    observed_files = {entry.path.value: entry for entry in snapshot.files}
    observed_dirs = {entry.path.value: entry for entry in snapshot.directories}

    match _build_trees(all_outputs, observed_files, observed_dirs, store):
        case Err(error):
            return Err(error)
        case Ok((tree_ops, covered_paths)):
            pass
    match _classify_outputs(
        tuple(
            output for output in seed_outputs if output.path.value not in covered_paths
        ),
        observed_files,
        observed_dirs,
        store,
        refuse_present_old=False,
    ):
        case Err(error):
            return Err(error)
        case Ok(seed_plain):
            pass
    match _classify_outputs(
        tuple(
            output
            for output in managed_outputs
            if output.path.value not in covered_paths
        ),
        observed_files,
        observed_dirs,
        store,
        refuse_present_old=False,
    ):
        case Err(error):
            return Err(error)
        case Ok(managed_plain):
            pass
    match _classify_outputs(
        tuple(
            output
            for output in manifest_outputs
            if output.path.value not in covered_paths
        ),
        observed_files,
        observed_dirs,
        store,
        refuse_present_old=True,
    ):
        case Err(error):
            return Err(error)
        case Ok(manifest_plain):
            pass

    cleanup_files: tuple[DeleteFileOperation, ...] = ()
    cleanup_dirs: tuple[RemoveEmptyDirectoryOperation, ...] = ()
    inventory_ops: tuple[DeleteFileOperation, ...] = ()
    match maintenance:
        case CleanMaintenance():
            if cleanup is not None:
                match _cleanup_operations(cleanup, observed_files, observed_dirs):
                    case Err(error):
                        return Err(error)
                    case Ok((files, directories)):
                        cleanup_files, cleanup_dirs = files, directories
                match _inventory_deletion(observed_files):
                    case Err(error):
                        return Err(error)
                    case Ok(operation):
                        inventory_ops = (operation,)
        case RetainMaintenance():
            pass
        case _:
            return assert_never(maintenance)  # pragma: no cover

    cleanup_dirs_ordered = tuple(
        sorted(
            cleanup_dirs,
            key=lambda operation: (
                -(len(operation.path.value.split("/"))),
                operation.path.value.encode("utf-8"),
            ),
        )
    )
    ordered_operations = (
        *seed_plain,
        *managed_plain,
        *manifest_plain,
        *tree_ops,
        *cleanup_files,
        *cleanup_dirs_ordered,
        *inventory_ops,
    )
    planned_paths: set[RepoPath] = set()
    for operation in ordered_operations:
        if isinstance(operation, CreateTreeOperation):
            planned_paths.add(operation.root)
            planned_paths.update(entry.path for entry in operation.planned_new.entries)
        else:
            planned_paths.add(operation.path)
    match check_limit(LimitKind.PATHS, len(planned_paths), limits):
        case Err(violation):
            return Err(
                _compile_error(
                    CompileErrorKind.PLAN_LIMIT_EXCEEDED, violation.kind.value
                )
            )
        case Ok(_):
            pass
    match check_limit(LimitKind.OPERATIONS, len(ordered_operations), limits):
        case Err(violation):
            return Err(
                _compile_error(
                    CompileErrorKind.PLAN_LIMIT_EXCEEDED, violation.kind.value
                )
            )
        case Ok(_):
            pass

    return Ok(
        OperationPlan(
            plan_schema=PLAN_SCHEMA_VERSION,
            operation_kind=PLAN_OPERATION_KIND,
            target_identity=target_identity,
            generation_path=generation,
            source_before=None,
            source_after=source_after,
            manifest_before=None,
            manifest_after=manifest_after,
            ordered_operations=ordered_operations,
            blob_store=store,
            gate_specification=GateSpecification(
                operation="initial",
                artifact_verification=True,
                template_contract=True,
                readiness_rule=ReadinessRule.INITIAL_EQUALITY,
                expected_placeholder=predicted_placeholder_findings(answers.slots),
            ),
        )
    )


def _expected_kind(identity: FileContentIdentity) -> Literal["text", "binary"]:
    match identity.kind:
        case "text":
            return "text"
        case "binary":
            return "binary"
        case _:
            return assert_never(identity.kind)  # pragma: no cover


def _apply_file_write(
    operation: CreateFileOperation | ReplaceFileOperation,
    observed_states: Mapping[str, FileState],
    observed_dir_states: Mapping[str, DirectoryState],
    directories: Mapping[str, DirectoryEntry],
    files: dict[str, ExpectedFile],
    blobs: VerifiedBlobStore,
    written: set[str],
) -> Result[None, PlanInvariantError]:
    if (
        operation.path.value in written
        or observed_states.get(operation.path.value, FileState(None, None))
        != operation.expected_old
        or operation.path.value in observed_dir_states
        or operation.path.value in directories
    ):
        return Err(
            _invariant_error(
                PlanInvariantErrorKind.UNMATCHED_PRECONDITION, operation.path.value
            )
        )
    content = blobs.get(operation.planned_new.content_id)
    if content is None:
        return Err(
            _invariant_error(PlanInvariantErrorKind.MISSING_BLOB, operation.path.value)
        )
    files[operation.path.value] = ExpectedFile(
        path=operation.path,
        kind=_expected_kind(operation.planned_new.identity),
        mode=operation.planned_new.mode,
        content=content,
    )
    written.add(operation.path.value)
    return Ok(None)


def apply_plan(
    target: TargetSnapshot,
    plan: OperationPlan,
) -> Result[ExpectedTarget, PlanInvariantError]:
    """Overlay the plan on the observed target; the result is never persisted."""
    observed_states = {entry.path.value: entry.state for entry in target.files}
    observed_dir_states = {
        entry.path.value: entry.state for entry in target.directories
    }
    files: dict[str, ExpectedFile] = {}
    for entry in target.files:
        if entry.state.identity is None or entry.state.mode is None:
            continue
        files[entry.path.value] = ExpectedFile(
            path=entry.path,
            kind=_expected_kind(entry.state.identity),
            mode=entry.state.mode,
            content=entry.content,
        )
    directories: dict[str, DirectoryEntry] = {
        entry.path.value: DirectoryEntry(entry.path, entry.state.root_mode)
        for entry in target.directories
    }
    written: set[str] = set()
    for operation in plan.ordered_operations:
        match operation:
            case CreateFileOperation() as create:
                match _apply_file_write(
                    create,
                    observed_states,
                    observed_dir_states,
                    directories,
                    files,
                    plan.blob_store,
                    written,
                ):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
            case ReplaceFileOperation() as replace:
                match _apply_file_write(
                    replace,
                    observed_states,
                    observed_dir_states,
                    directories,
                    files,
                    plan.blob_store,
                    written,
                ):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
            case DeleteFileOperation() as delete:
                if (
                    delete.path.value in written
                    or delete.path.value not in files
                    or observed_states.get(delete.path.value) != delete.expected_old
                    or delete.path.value in observed_dir_states
                    or delete.path.value in directories
                ):
                    return Err(
                        _invariant_error(
                            PlanInvariantErrorKind.UNMATCHED_PRECONDITION,
                            delete.path.value,
                        )
                    )
                files.pop(delete.path.value)
                written.add(delete.path.value)
            case CreateTreeOperation() as tree:
                if (
                    tree.root.value in written
                    or tree.root.value in observed_dir_states
                    or tree.root.value in directories
                    or tree.root.value in observed_states
                    or tree.root.value in files
                ):
                    return Err(
                        _invariant_error(
                            PlanInvariantErrorKind.UNMATCHED_PRECONDITION,
                            tree.root.value,
                        )
                    )
                directories[tree.root.value] = DirectoryEntry(
                    tree.root, tree.planned_new.root_mode
                )
                for entry in tree.planned_new.entries:
                    if isinstance(entry, PlannedDirectoryEntry):
                        if entry.path.value in directories or entry.path.value in files:
                            return Err(
                                _invariant_error(
                                    PlanInvariantErrorKind.DUPLICATE_PATH,
                                    entry.path.value,
                                )
                            )
                        directories[entry.path.value] = DirectoryEntry(
                            entry.path, entry.mode
                        )
                    else:
                        if entry.path.value in files or entry.path.value in directories:
                            return Err(
                                _invariant_error(
                                    PlanInvariantErrorKind.DUPLICATE_PATH,
                                    entry.path.value,
                                )
                            )
                        content = plan.blob_store.get(entry.content_id)
                        if content is None:
                            return Err(
                                _invariant_error(
                                    PlanInvariantErrorKind.MISSING_BLOB,
                                    entry.path.value,
                                )
                            )
                        files[entry.path.value] = ExpectedFile(
                            path=entry.path,
                            kind=_expected_kind(entry.identity),
                            mode=entry.mode,
                            content=content,
                        )
                written.add(tree.root.value)
                written.update(entry.path.value for entry in tree.planned_new.entries)
            case RemoveEmptyDirectoryOperation() as remove:
                prefix = remove.path.value + "/"
                if (
                    remove.path.value in written
                    or remove.path.value not in directories
                    or remove.expected_old.root_mode
                    != directories[remove.path.value].mode
                    or any(path.startswith(prefix) for path in files)
                    or any(path.startswith(prefix) for path in directories)
                ):
                    return Err(
                        _invariant_error(
                            PlanInvariantErrorKind.UNMATCHED_PRECONDITION,
                            remove.path.value,
                        )
                    )
                directories.pop(remove.path.value)
                written.add(remove.path.value)
    return Ok(
        ExpectedTarget(
            files=tuple(
                sorted(files.values(), key=lambda file: file.path.value.encode("utf-8"))
            ),
            directories=tuple(
                sorted(
                    directories.values(),
                    key=lambda entry: entry.path.value.encode("utf-8"),
                )
            ),
        )
    )


def evaluate_slot_readiness(expected: ExpectedTarget) -> MechanicalReadinessResult:
    """Evaluate the frozen bootstrap slot rules over the expected project bytes."""
    by_path = {file.path.value: file for file in expected.files}
    findings: list[Finding] = []
    for rule in SLOT_PLACEHOLDER_RULES:
        file = by_path.get(rule.path.value)
        if file is None:
            continue
        if rule.detection == "text":
            try:
                text = file.content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            found = rule.marker.decode("ascii") in text
        else:
            found = rule.marker in file.content
        if found:
            findings.append(_placeholder_finding(rule))
    return MechanicalReadinessResult(1, tuple(findings))


def evaluate_expected_contract(expected: ExpectedTarget) -> tuple[str, ...]:
    """Evaluate the frozen template contract over the expected project paths and skills."""
    present_files = tuple(sorted(file.path.value for file in expected.files))
    skill_texts: list[tuple[str, str]] = []
    for file in expected.files:
        path = file.path.value
        if path.startswith(".agents/skills/") and path.endswith("/SKILL.md"):
            try:
                text = file.content.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            skill_texts.append((path, text))
    return required_contract_failures(present_files, tuple(skill_texts))


def _contract_diagnostic(failure: str) -> Diagnostic:
    return Diagnostic(
        code="TEMPLATE_CONTRACT_ERROR",
        category=DiagnosticCategory.CONTRACT,
        severity=DiagnosticSeverity.ERROR,
        subject="template contract",
        summary="Template-contract evaluation failed",
        details=failure,
        next_action=NoAutomaticAction("restore the template contract"),
    )


def evaluate_expected(expected: ExpectedTarget) -> ExpectedValidation:
    """Evaluate template-contract and readiness policy over the expected target."""
    failures = evaluate_expected_contract(expected)
    if failures:
        return ExpectedGateRefusal(
            tuple(_contract_diagnostic(failure) for failure in failures)
        )
    return ExpectedGatePass(evaluate_slot_readiness(expected))
