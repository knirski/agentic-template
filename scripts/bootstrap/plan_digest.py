"""Byte-erased plan receipts and their tagged plan digest binding.

``build_receipt`` erases every byte from an ``OperationPlan``: the non-reversible target
binding replaces the target identity, and planned files reference content ids instead of
bytes.  The receipt is canonical JSON, so the same inputs always produce the same receipt
and the same digest.  No receipt contains adopter, legal, generated, or backup bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, assert_never, cast, get_args, get_type_hints

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.canonical_json import (
    canonical_json,
    decode_object,
)
from scripts.bootstrap.identity import (
    DirectoryState,
    FileContentIdentity,
    FileState,
    ManifestIdentity,
    PosixMode,
    TargetIdentity,
    directory_tree_hash,
    file_state_document,
    tagged_digest,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    INSTALL_MODES,
    baseline_document,
    path_within_limits,
)
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.planner import (
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    DirectoryAbsent,
    DirectoryOperation,
    FileAbsent,
    FileOperation,
    GateSpecification,
    MaterializedTree,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    PlannedFilePresent,
    ReadinessRule,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
)
from scripts.bootstrap.readiness import Finding, Repository, Severity, SubjectPath
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
    SourceBaseline,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits
from scripts.bootstrap.vocabulary import COMMIT_SHA, SHA256, is_sha256

_GENERATION_PATHS = frozenset(path.value for path in GenerationPath)
_READINESS_RULES = frozenset(rule.value for rule in ReadinessRule)
_OPERATIONS = frozenset(get_args(get_type_hints(GateSpecification)["operation"]))
_SEVERITIES = frozenset(
    get_args(Severity.__value__)  # pyright: ignore[reportAny] — PEP 695 alias value; the closed set is pinned by the receipt round-trip tests
)

type PlanReceipt = dict[str, object]


class ReceiptErrorKind(StrEnum):
    INVALID_JSON = "invalid_json"
    SCHEMA_VIOLATION = "schema_violation"


@dataclass(frozen=True, slots=True)
class ReceiptError:
    kind: ReceiptErrorKind
    subject: str = ""


def _receipt_error(subject: str = "") -> ReceiptError:
    return ReceiptError(ReceiptErrorKind.SCHEMA_VIOLATION, subject)


def _planned_file_document(planned: PlannedFilePresent) -> dict[str, object]:
    return {
        "kind": planned.identity.kind,
        "mode": planned.mode.value,
        "normalized_sha256": planned.identity.normalized_sha256,
        "raw_sha256": planned.identity.raw_sha256,
        "size": planned.identity.size,
        "content_id": planned.content_id.value,
    }


def _file_operation_document(
    operation: CreateFileOperation | ReplaceFileOperation | DeleteFileOperation,
) -> dict[str, object]:
    match operation:
        case CreateFileOperation():
            kind = "create_file"
        case ReplaceFileOperation():
            kind = "replace_file"
        case DeleteFileOperation():
            kind = "delete_file"
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            return assert_never(
                operation
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — unreachable only because recommended mode proves the match exhaustive
    match operation.planned_new:
        case PlannedFilePresent():
            planned: dict[str, object] | None = _planned_file_document(
                operation.planned_new
            )
        case FileAbsent():
            planned = None
    return {
        "kind": kind,
        "path": operation.path.value,
        "expected_old": file_state_document(operation.expected_old),
        "planned_new": planned,
    }


def _tree_entry_document(
    entry: PlannedDirectoryEntry | PlannedFileEntry,
) -> dict[str, object]:
    match entry:
        case PlannedDirectoryEntry():
            return {
                "kind": "directory",
                "path": entry.path.value,
                "mode": entry.mode.value,
            }
        case PlannedFileEntry():
            return {
                "kind": "file",
                "file_kind": entry.identity.kind,
                "path": entry.path.value,
                "mode": entry.mode.value,
                "normalized_sha256": entry.identity.normalized_sha256,
                "raw_sha256": entry.identity.raw_sha256,
                "size": entry.identity.size,
                "content_id": entry.content_id.value,
            }


def _tree_document(tree: MaterializedTree) -> dict[str, object]:
    return {
        "root_mode": tree.root_mode.value,
        "raw_tree_sha256": tree.raw_tree_sha256,
        "entries": [_tree_entry_document(entry) for entry in tree.entries],
    }


def _directory_operation_document(
    operation: CreateTreeOperation | RemoveEmptyDirectoryOperation,
) -> dict[str, object]:
    match operation:
        case CreateTreeOperation():
            return {
                "kind": "create_tree",
                "root": operation.root.value,
                "expected_old": None,
                "planned_new": _tree_document(operation.planned_new),
            }
        case RemoveEmptyDirectoryOperation():
            return {
                "kind": "remove_empty_directory",
                "path": operation.path.value,
                "expected_old": {
                    "mode": operation.expected_old.root_mode.value,
                    "raw_tree_sha256": directory_tree_hash(
                        b"plan/tree", operation.expected_old
                    ),
                },
                "planned_new": None,
            }
        case _:  # pragma: no cover  # pyright: ignore[reportUnnecessaryComparison] — the remainder is Never under recommended mode; kept for runtime defense
            return assert_never(
                operation
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — unreachable only because recommended mode proves the match exhaustive


def _finding_document(finding: Finding) -> dict[str, object]:
    match finding.subject_at:
        case SubjectPath():
            subject_at = finding.subject_at.value
        case Repository():
            subject_at = "repository"
    return {
        "code": finding.code,
        "subject_at": subject_at,
        "subject": finding.subject,
        "rule": finding.rule,
        "severity": finding.severity,
    }


def _gate_document(gate: GateSpecification) -> dict[str, object]:
    return {
        "operation": gate.operation,
        "artifact_verification": gate.artifact_verification,
        "template_contract": gate.template_contract,
        "readiness_rule": gate.readiness_rule.value,
        "expected_placeholder": [
            _finding_document(finding) for finding in gate.expected_placeholder
        ],
    }


def build_receipt(plan: OperationPlan) -> PlanReceipt:
    """Erase every byte from the plan, preserving identities, modes, and topology."""
    operations: list[dict[str, object]] = []
    for operation in plan.ordered_operations:
        match operation:
            case CreateFileOperation() | ReplaceFileOperation() | DeleteFileOperation():
                operations.append(_file_operation_document(operation))
            case CreateTreeOperation() | RemoveEmptyDirectoryOperation():
                operations.append(_directory_operation_document(operation))
    return {
        "plan_schema": plan.plan_schema,
        "operation_kind": plan.operation_kind,
        "target_binding": plan.target_identity.digest,
        "generation_path": plan.generation_path.value,
        "source_before": (
            baseline_document(plan.source_before)
            if plan.source_before is not None
            else None
        ),
        "source_after": baseline_document(plan.source_after),
        "manifest_before": (
            plan.manifest_before.digest if plan.manifest_before is not None else None
        ),
        "manifest_after": plan.manifest_after.digest,
        "gate_specification": _gate_document(plan.gate_specification),
        "operations": operations,
    }


def plan_receipt_digest(receipt: PlanReceipt) -> str:
    """Tag the canonical receipt bytes; the digest itself is never part of the receipt."""
    return tagged_digest(b"reconcile-plan", canonical_json(receipt))


def encode_receipt(receipt: PlanReceipt) -> bytes:
    """Serialize the receipt as canonical JSON; decoding must reproduce it exactly."""
    return canonical_json(receipt)


def decode_receipt(data: bytes) -> Result[PlanReceipt, ReceiptError]:
    """Strictly decode a canonical receipt and reject any shape outside the closed contract.

    The top-level fields are validated here; every nested document is
    validated by the same reconstructors ``reconstruct_plan`` uses, so the
    decode and reconstruction paths cannot drift.
    """

    def _reason(reason: str) -> ReceiptError:
        if reason == "json":
            return ReceiptError(ReceiptErrorKind.INVALID_JSON)
        return _receipt_error(reason)

    match decode_object(
        data,
        error=_reason,
        max_bytes=DEFAULT_LIMITS.max_file_bytes,
        allowed_keys=frozenset(
            {
                "plan_schema",
                "operation_kind",
                "target_binding",
                "generation_path",
                "source_before",
                "source_after",
                "manifest_before",
                "manifest_after",
                "gate_specification",
                "operations",
            }
        ),
    ):
        case Err(error):
            return Err(error)
        case Ok(value):
            pass
    if value.get("plan_schema") != 1:
        return Err(_receipt_error("plan_schema"))
    if value.get("operation_kind") != "initial":
        return Err(_receipt_error("operation_kind"))
    target_binding = value.get("target_binding")
    if not isinstance(target_binding, str) or SHA256.fullmatch(target_binding) is None:
        return Err(_receipt_error("target_binding"))
    generation_value = value.get("generation_path")
    if (
        not isinstance(generation_value, str)
        or generation_value not in _GENERATION_PATHS
    ):
        return Err(_receipt_error("generation_path"))
    generation = GenerationPath(generation_value)  # closed set checked above
    match _reconstruct_source_baseline(value.get("source_before"), generation):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _reconstruct_source_baseline(value.get("source_after"), generation):
        case Err(error):
            return Err(error)
        case Ok(None):
            return Err(_receipt_error("source_after"))
        case Ok(_):
            pass
    manifest_before = value.get("manifest_before")
    if manifest_before is not None and not is_sha256(manifest_before):
        return Err(_receipt_error("manifest_before"))
    manifest_after = value.get("manifest_after")
    if not is_sha256(manifest_after):
        return Err(_receipt_error("manifest_after"))
    match _reconstruct_gate(value.get("gate_specification")):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    operations = value.get("operations")
    if not isinstance(operations, list):
        return Err(_receipt_error("operations"))
    for operation in operations:
        match _reconstruct_operation(operation):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
    return Ok(cast(PlanReceipt, value))


def reconstruct_plan(
    receipt: PlanReceipt,
    *,
    target: TargetIdentity,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[OperationPlan, ReceiptError]:
    """Reconstruct the byte-erased receipt as a verification-only ``OperationPlan``.

    The receipt preserves every identity, mode, path, and topology the pure
    rollback and sealed-forward reducers consume; byte-carrying fields that are
    deliberately absent from a receipt (blob payloads, manifest payloads,
    finding prose) are replaced with closed stubs.  The returned plan is valid
    only for ``rollback_steps``, ``sealed_steps``, ``restored_verification``,
    and ``sealed_verification``; it must never be executed as a mutation.
    """

    if receipt.get("target_binding") != target.digest:
        return Err(_receipt_error("target_binding"))
    try:
        generation = GenerationPath(cast(str, receipt.get("generation_path")))
    except ValueError:
        return Err(_receipt_error("generation_path"))
    operations: list[FileOperation | DirectoryOperation] = []
    raw_operations = receipt.get("operations")
    if not isinstance(raw_operations, list):
        return Err(_receipt_error("operations"))
    for raw_operation in cast(list[object], raw_operations):
        match _reconstruct_operation(raw_operation, limits):
            case Err(error):
                return Err(error)
            case Ok(operation):
                operations.append(operation)
    match _reconstruct_source_baseline(
        receipt.get("source_before"), generation, limits
    ):
        case Err(error):
            return Err(error)
        case Ok(source_before):
            pass
    match _reconstruct_source_baseline(receipt.get("source_after"), generation, limits):
        case Err(error):
            return Err(error)
        case Ok(source_after):
            if source_after is None:
                return Err(_receipt_error("source_after"))
            pass
    manifest_after = receipt.get("manifest_after")
    if not is_sha256(manifest_after):
        return Err(_receipt_error("manifest_after"))
    manifest_before = receipt.get("manifest_before")
    if manifest_before is not None and not is_sha256(manifest_before):
        return Err(_receipt_error("manifest_before"))
    match _reconstruct_gate(receipt.get("gate_specification")):
        case Err(error):
            return Err(error)
        case Ok(gate):
            pass
    return Ok(
        OperationPlan(
            plan_schema=1,
            operation_kind="initial",
            target_identity=target,
            generation_path=generation,
            source_before=source_before,
            source_after=source_after,
            manifest_before=(
                ManifestIdentity(payload=b"", digest=manifest_before)
                if manifest_before is not None
                else None
            ),
            manifest_after=ManifestIdentity(payload=b"", digest=manifest_after),
            ordered_operations=tuple(operations),
            blob_store=VerifiedBlobStore.empty(limits),
            gate_specification=gate,
        )
    )


def _reconstruct_operation(
    value: object,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[FileOperation | DirectoryOperation, ReceiptError]:
    """Reconstruct one closed operation document into its typed constructor."""

    if not isinstance(value, dict):
        return Err(_receipt_error("operation"))
    document = cast(dict[str, object], value)
    match document.get("kind"):
        case "create_file" | "replace_file":
            if set(document) != {"kind", "path", "expected_old", "planned_new"}:
                return Err(_receipt_error("operation"))
            match _reconstruct_path(document.get("path"), "operation.path", limits):
                case Err(error):
                    return Err(error)
                case Ok(path):
                    pass
            match _reconstruct_observed_state(document.get("expected_old")):
                case Err(error):
                    return Err(error)
                case Ok(expected_old):
                    pass
            match _reconstruct_planned_new(document.get("planned_new")):
                case Err(error):
                    return Err(error)
                case Ok(planned_new):
                    pass
            if document.get("kind") == "create_file":
                return Ok(CreateFileOperation(path, expected_old, planned_new))
            return Ok(ReplaceFileOperation(path, expected_old, planned_new))
        case "delete_file":
            if set(document) != {"kind", "path", "expected_old", "planned_new"}:
                return Err(_receipt_error("operation"))
            match _reconstruct_path(document.get("path"), "operation.path", limits):
                case Err(error):
                    return Err(error)
                case Ok(path):
                    pass
            match _reconstruct_observed_state(document.get("expected_old")):
                case Err(error):
                    return Err(error)
                case Ok(expected_old):
                    pass
            if document.get("planned_new") is not None:
                return Err(_receipt_error("operation.planned_new"))
            return Ok(DeleteFileOperation(path, expected_old, FileAbsent()))
        case "create_tree":
            if set(document) != {"kind", "root", "expected_old", "planned_new"}:
                return Err(_receipt_error("operation"))
            match _reconstruct_path(document.get("root"), "operation.root", limits):
                case Err(error):
                    return Err(error)
                case Ok(root):
                    pass
            if document.get("expected_old") is not None:
                return Err(_receipt_error("operation.expected_old"))
            planned = document.get("planned_new")
            if not isinstance(planned, dict):
                return Err(_receipt_error("operation.planned_new"))
            match _reconstruct_tree(root, cast(dict[str, object], planned), limits):
                case Err(error):
                    return Err(error)
                case Ok(tree):
                    pass
            return Ok(CreateTreeOperation(root, None, tree))
        case "remove_empty_directory":
            if set(document) != {"kind", "path", "expected_old", "planned_new"}:
                return Err(_receipt_error("operation"))
            match _reconstruct_path(document.get("path"), "operation.path", limits):
                case Err(error):
                    return Err(error)
                case Ok(path):
                    pass
            expected = document.get("expected_old")
            if not isinstance(expected, dict):
                return Err(_receipt_error("operation.expected_old"))
            expected_document = cast(dict[str, object], expected)
            mode = expected_document.get("mode")
            digest = expected_document.get("raw_tree_sha256")
            if (
                set(expected_document) != {"mode", "raw_tree_sha256"}
                or type(mode) is not int
                or not 0 <= mode <= 0o7777
                or not is_sha256(digest)
                or document.get("planned_new") is not None
            ):
                return Err(_receipt_error("operation.expected_old"))
            return Ok(
                RemoveEmptyDirectoryOperation(
                    path,
                    DirectoryState(PosixMode(mode), ()),
                    DirectoryAbsent(),
                )
            )
        case _:
            return Err(_receipt_error("operation.kind"))


def _reconstruct_path(
    value: object, subject: str, limits: ResourceLimits = DEFAULT_LIMITS
) -> Result[RepoPath, ReceiptError]:
    if not isinstance(value, str):
        return Err(_receipt_error(subject))
    match parse_path(value):
        case Err(_):
            return Err(_receipt_error(subject))
        case Ok(path):
            pass
    if not path_within_limits(path, limits):
        return Err(_receipt_error(subject))
    return Ok(path)


def _reconstruct_observed_state(value: object) -> Result[FileState, ReceiptError]:
    if value is None:
        return Ok(FileState(None, None))
    if not isinstance(value, dict):
        return Err(_receipt_error("operation.expected_old"))
    document = cast(dict[str, object], value)
    if set(document) != {
        "kind",
        "mode",
        "normalized_sha256",
        "raw_sha256",
        "size",
    }:
        return Err(_receipt_error("operation.expected_old"))
    kind = document.get("kind")
    mode = document.get("mode")
    size = document.get("size")
    normalized = document.get("normalized_sha256")
    raw = document.get("raw_sha256")
    if (
        kind not in ("text", "binary")
        or type(mode) is not int
        or not 0 <= mode <= 0o7777
        or not is_sha256(normalized)
        or not is_sha256(raw)
        or not isinstance(size, int)
        or size < 0
    ):
        return Err(_receipt_error("operation.expected_old"))
    return Ok(
        FileState(
            identity=FileContentIdentity(
                kind=kind,
                normalized_sha256=normalized,
                raw_sha256=raw,
                size=size,
            ),
            mode=PosixMode(mode),
        )
    )


def _reconstruct_planned_new(value: object) -> Result[PlannedFilePresent, ReceiptError]:
    if not isinstance(value, dict):
        return Err(_receipt_error("operation.planned_new"))
    document = cast(dict[str, object], value)
    if set(document) not in (
        {"kind", "mode", "normalized_sha256", "raw_sha256", "size"},
        {"kind", "mode", "normalized_sha256", "raw_sha256", "size", "content_id"},
    ):
        return Err(_receipt_error("operation.planned_new"))
    kind = document.get("kind")
    mode = document.get("mode")
    size = document.get("size")
    normalized = document.get("normalized_sha256")
    raw = document.get("raw_sha256")
    content_id = document.get("content_id")
    if (
        kind not in ("text", "binary")
        or type(mode) is not int
        or mode not in INSTALL_MODES
        or not is_sha256(normalized)
        or not is_sha256(raw)
        or not isinstance(size, int)
        or size < 0
        or not is_sha256(content_id)
    ):
        return Err(_receipt_error("operation.planned_new"))
    return Ok(
        PlannedFilePresent(
            identity=FileContentIdentity(
                kind=kind,
                normalized_sha256=normalized,
                raw_sha256=raw,
                size=size,
            ),
            mode=PosixMode(mode),
            content_id=ContentId(content_id),
        )
    )


def _reconstruct_tree(
    root: RepoPath,
    document: dict[str, object],
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[MaterializedTree, ReceiptError]:
    if set(document) != {"root_mode", "raw_tree_sha256", "entries"}:
        return Err(_receipt_error("operation.planned_new"))
    root_mode = document.get("root_mode")
    raw_tree_sha256 = document.get("raw_tree_sha256")
    entries = document.get("entries")
    if (
        not isinstance(root_mode, int)
        or root_mode != PosixMode.DIRECTORY
        or not is_sha256(raw_tree_sha256)
        or not isinstance(entries, list)
    ):
        return Err(_receipt_error("operation.planned_new"))
    tree_entries: list[PlannedDirectoryEntry | PlannedFileEntry] = []
    seen_paths: set[str] = set()
    for entry in cast(list[object], entries):
        if not isinstance(entry, dict):
            return Err(_receipt_error("operation.planned_new"))
        entry_document = cast(dict[str, object], entry)
        match entry_document.get("kind"):
            case "directory":
                if set(entry_document) != {"kind", "path", "mode"}:
                    return Err(_receipt_error("operation.entries"))
                match _reconstruct_path(
                    entry_document.get("path"), "operation.entries", limits
                ):
                    case Err(error):
                        return Err(error)
                    case Ok(path):
                        pass
                if path.value in seen_paths:
                    return Err(_receipt_error("operation.entries"))
                seen_paths.add(path.value)
                mode = entry_document.get("mode")
                if type(mode) is not int or mode != PosixMode.DIRECTORY:
                    return Err(_receipt_error("operation.entries"))
                tree_entries.append(PlannedDirectoryEntry(path, PosixMode(mode)))
            case "file":
                if set(entry_document) != {
                    "kind",
                    "file_kind",
                    "path",
                    "mode",
                    "normalized_sha256",
                    "raw_sha256",
                    "size",
                    "content_id",
                }:
                    return Err(_receipt_error("operation.entries"))
                match _reconstruct_path(
                    entry_document.get("path"), "operation.entries", limits
                ):
                    case Err(error):
                        return Err(error)
                    case Ok(path):
                        pass
                if path.value in seen_paths:
                    return Err(_receipt_error("operation.entries"))
                seen_paths.add(path.value)
                file_kind = entry_document.get("file_kind")
                if file_kind not in ("text", "binary"):
                    return Err(_receipt_error("operation.entries"))
                match _reconstruct_planned_new(
                    {
                        "kind": file_kind,
                        "mode": entry_document.get("mode"),
                        "normalized_sha256": entry_document.get("normalized_sha256"),
                        "raw_sha256": entry_document.get("raw_sha256"),
                        "size": entry_document.get("size"),
                        "content_id": entry_document.get("content_id"),
                    }
                ):
                    case Err(error):
                        return Err(error)
                    case Ok(planned):
                        pass
                tree_entries.append(
                    PlannedFileEntry(
                        path=path,
                        identity=planned.identity,
                        mode=planned.mode,
                        content_id=planned.content_id,
                    )
                )
            case _:
                return Err(_receipt_error("operation.entries"))
    return Ok(
        MaterializedTree(
            root=root,
            root_mode=PosixMode.DIRECTORY,
            entries=tuple(tree_entries),
            raw_tree_sha256=raw_tree_sha256,
        )
    )


def _reconstruct_source_baseline(
    value: object,
    generation: GenerationPath,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[SourceBaseline | None, ReceiptError]:
    if value is None:
        return Ok(None)
    if not isinstance(value, dict):
        return Err(_receipt_error("source_baseline"))
    document = cast(dict[str, object], value)
    kind = document.get("kind")
    fingerprint = document.get("fingerprint")
    if kind not in ("github", "copier") or not is_sha256(fingerprint):
        return Err(_receipt_error("source_baseline"))
    if kind != generation.value:
        return Err(_receipt_error("source_baseline"))
    expected_keys = (
        {"kind", "fingerprint", "entries", "snapshot_commit"}
        if kind == "github"
        else {"kind", "fingerprint", "entries"}
    )
    if set(document) != expected_keys:
        return Err(_receipt_error("source_baseline"))
    if kind == "github":
        snapshot_commit = document.get("snapshot_commit")
        if (
            not isinstance(snapshot_commit, str)
            or COMMIT_SHA.fullmatch(snapshot_commit) is None
        ):
            return Err(_receipt_error("source_baseline"))
    entries_value = document.get("entries")
    if not isinstance(entries_value, list):
        return Err(_receipt_error("source_baseline.entries"))
    entries: list[LifecycleSourceEntry] = []
    for entry in cast(list[object], entries_value):
        if not isinstance(entry, dict):
            return Err(_receipt_error("source_baseline.entries"))
        entry_document = cast(dict[str, object], entry)
        if set(entry_document) != {"path", "kind", "mode", "sha256"}:
            return Err(_receipt_error("source_baseline.entries"))
        match _reconstruct_path(
            entry_document.get("path"), "source_baseline.entries", limits
        ):
            case Err(error):
                return Err(error)
            case Ok(path):
                pass
        entry_kind = entry_document.get("kind")
        mode = entry_document.get("mode")
        digest = entry_document.get("sha256")
        if (
            entry_kind not in ("file", "directory")
            or type(mode) is not int
            or mode not in INSTALL_MODES
            or not is_sha256(digest)
        ):
            return Err(_receipt_error("source_baseline.entries"))
        entries.append(
            LifecycleSourceEntry(
                path=path,
                kind=entry_kind,
                mode=PosixMode(mode),
                sha256=digest,
            )
        )
    if kind == "github":
        return Ok(
            GitHubSourceBaseline(
                kind="github",
                fingerprint=fingerprint,
                entries=tuple(entries),
                # the key-set and digest checks above guarantee a commit string
                snapshot_commit=cast(str, document.get("snapshot_commit")),
            )
        )
    return Ok(
        CopierSourceBaseline(
            kind="copier",
            fingerprint=fingerprint,
            entries=tuple(entries),
        )
    )


def _reconstruct_gate(value: object) -> Result[GateSpecification, ReceiptError]:
    if not isinstance(value, dict):
        return Err(_receipt_error("gate_specification"))
    document = cast(dict[str, object], value)
    if set(document) != {
        "operation",
        "artifact_verification",
        "template_contract",
        "readiness_rule",
        "expected_placeholder",
    }:
        return Err(_receipt_error("gate_specification"))
    operation = document.get("operation")
    artifact_verification = document.get("artifact_verification")
    template_contract = document.get("template_contract")
    readiness_rule = document.get("readiness_rule")
    expected = document.get("expected_placeholder")
    if (
        operation not in _OPERATIONS
        or not isinstance(artifact_verification, bool)
        or not isinstance(template_contract, bool)
        or readiness_rule not in _READINESS_RULES
        or not isinstance(expected, list)
    ):
        return Err(_receipt_error("gate_specification"))
    findings: list[Finding] = []
    for raw_finding in cast(list[object], expected):
        if not isinstance(raw_finding, dict):
            return Err(_receipt_error("gate_specification.expected_placeholder"))
        finding_document = cast(dict[str, object], raw_finding)
        if set(finding_document) != {
            "code",
            "subject_at",
            "subject",
            "rule",
            "severity",
        }:
            return Err(_receipt_error("gate_specification.expected_placeholder"))
        subject_at = finding_document.get("subject_at")
        if subject_at == "repository":
            location: SubjectPath | Repository = Repository()
        elif isinstance(subject_at, str):
            match _reconstruct_path(
                subject_at, "gate_specification.expected_placeholder"
            ):
                case Err(error):
                    return Err(error)
                case Ok(path):
                    location = SubjectPath(path.value)
        else:
            return Err(_receipt_error("gate_specification.expected_placeholder"))
        # Reconstructed findings are gate-shape stubs: the receipt deliberately
        # erases message prose, so verification never renders it.  The four
        # carrier fields are still validated so malformed receipt JSON cannot
        # construct an invalid ``Finding``.
        code = finding_document.get("code")
        subject = finding_document.get("subject")
        rule = finding_document.get("rule")
        severity = finding_document.get("severity")
        if (
            severity not in ("blocking", "informational")
            or not isinstance(code, str)
            or not isinstance(subject, str)
            or not isinstance(rule, str)
        ):
            return Err(_receipt_error("gate_specification.expected_placeholder"))
        findings.append(
            Finding(
                code=code,
                subject_at=location,
                subject=subject,
                rule=rule,
                severity=severity,
                message="",
                next_action="",
            )
        )
    return Ok(
        GateSpecification(
            operation=cast(
                Literal["initial", "add", "restore", "reconcile"], operation
            ),
            artifact_verification=artifact_verification,
            template_contract=template_contract,
            readiness_rule=ReadinessRule(cast(str, readiness_rule)),
            expected_placeholder=tuple(findings),
        )
    )
