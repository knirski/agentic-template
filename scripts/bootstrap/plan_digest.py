"""Byte-erased plan receipts and their tagged plan digest binding.

``build_receipt`` erases every byte from an ``OperationPlan``: the non-reversible target
binding replaces the target identity, and planned files reference content ids instead of
bytes.  The receipt is canonical JSON, so the same inputs always produce the same receipt
and the same digest.  No receipt contains adopter, legal, generated, or backup bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, assert_never

from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.identity import (
    FileContentIdentity,
    FileState,
    PosixMode,
    directory_tree_hash,
    tagged_digest,
)
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
    GateSpecification,
    MaterializedTree,
    OperationPlan,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    PlannedFilePresent,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
)
from scripts.bootstrap.readiness import Finding, SubjectPath
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.values import DEFAULT_LIMITS
from scripts.bootstrap.vocabulary import COMMIT_SHA, SHA256

_FILE_OPERATION_KINDS = frozenset({"create_file", "replace_file", "delete_file"})
_DIRECTORY_OPERATION_KINDS = frozenset({"create_tree", "remove_empty_directory"})
_GENERATION_PATHS = frozenset({"github", "copier"})
_READINESS_RULES = frozenset({"initial-equality", "no-worse-blocking"})
_OPERATIONS = frozenset({"initial", "add", "restore", "reconcile"})
_SEVERITIES = frozenset({"blocking", "informational"})

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


def _file_state_document(state: FileState) -> dict[str, object] | None:
    if not state.present or state.identity is None or state.mode is None:
        return None
    return {
        "kind": state.identity.kind,
        "mode": state.mode.value,
        "normalized_sha256": state.identity.normalized_sha256,
        "raw_sha256": state.identity.raw_sha256,
        "size": state.identity.size,
    }


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
        case _:  # pragma: no cover
            return assert_never(operation)  # pragma: no cover
    planned: dict[str, object] | None = (
        _planned_file_document(operation.planned_new)
        if isinstance(operation.planned_new, PlannedFilePresent)
        else None
    )
    return {
        "kind": kind,
        "path": operation.path.value,
        "expected_old": _file_state_document(operation.expected_old),
        "planned_new": planned,
    }


def _tree_entry_document(
    entry: PlannedDirectoryEntry | PlannedFileEntry,
) -> dict[str, object]:
    if isinstance(entry, PlannedDirectoryEntry):
        return {"kind": "directory", "path": entry.path.value, "mode": entry.mode.value}
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
        case _:  # pragma: no cover
            return assert_never(operation)  # pragma: no cover


def _finding_document(finding: Finding) -> dict[str, object]:
    subject_at = (
        finding.subject_at.value
        if isinstance(finding.subject_at, SubjectPath)
        else "repository"
    )
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
        if isinstance(
            operation,
            (CreateFileOperation, ReplaceFileOperation, DeleteFileOperation),
        ):
            operations.append(_file_operation_document(operation))
        else:
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
    """Strictly decode a canonical receipt and reject any shape outside the closed contract."""
    if len(data) > DEFAULT_LIMITS.max_file_bytes:
        return Err(_receipt_error("size"))
    try:
        value = decode_json(data)
    except ValueError, RecursionError:
        return Err(ReceiptError(ReceiptErrorKind.INVALID_JSON))
    if not isinstance(value, dict):
        return Err(_receipt_error("document"))
    if set(value) != {
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
    }:
        return Err(_receipt_error("document"))
    if value.get("plan_schema") != 1:
        return Err(_receipt_error("plan_schema"))
    if value.get("operation_kind") != "initial":
        return Err(_receipt_error("operation_kind"))
    target_binding = value.get("target_binding")
    if not isinstance(target_binding, str) or SHA256.fullmatch(target_binding) is None:
        return Err(_receipt_error("target_binding"))
    generation = value.get("generation_path")
    if generation not in _GENERATION_PATHS:
        return Err(_receipt_error("generation_path"))
    match _decode_baseline(
        value.get("source_before"), required=False, generation=generation
    ):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    match _decode_baseline(
        value.get("source_after"), required=True, generation=generation
    ):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    manifest_before = value.get("manifest_before")
    if manifest_before is not None and not _is_digest(manifest_before):
        return Err(_receipt_error("manifest_before"))
    manifest_after = value.get("manifest_after")
    if not _is_digest(manifest_after):
        return Err(_receipt_error("manifest_after"))
    match _decode_gate(value.get("gate_specification")):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    operations = value.get("operations")
    if not isinstance(operations, list):
        return Err(_receipt_error("operations"))
    for operation in operations:
        match _decode_operation(operation):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
    return Ok(value)


def _decode_path(value: object, subject: str) -> Result[RepoPath, ReceiptError]:
    if not isinstance(value, str):
        return Err(_receipt_error(subject))
    match parse_path(value):
        case Err(_):
            return Err(_receipt_error(subject))
        case Ok(path):
            pass
    if not path_within_limits(path):
        return Err(_receipt_error(subject))
    return Ok(path)


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _decode_identity(
    value: object, subject: str
) -> Result[FileContentIdentity, ReceiptError]:
    if not isinstance(value, dict) or set(value) not in (
        {"kind", "mode", "normalized_sha256", "raw_sha256", "size"},
        {"kind", "mode", "normalized_sha256", "raw_sha256", "size", "content_id"},
    ):
        return Err(_receipt_error(subject))
    kind = value.get("kind")
    mode = value.get("mode")
    size = value.get("size")
    match kind:
        case "text":
            file_kind: Literal["text", "binary"] = "text"
        case "binary":
            file_kind = "binary"
        case _:
            return Err(_receipt_error(subject))
    if (
        not isinstance(mode, int)
        or mode not in INSTALL_MODES
        or not _is_digest(value.get("normalized_sha256"))
        or not _is_digest(value.get("raw_sha256"))
        or not isinstance(size, int)
        or size < 0
    ):
        return Err(_receipt_error(subject))
    content_id = value.get("content_id")
    if content_id is not None and not _is_digest(content_id):
        return Err(_receipt_error(subject))
    return Ok(
        FileContentIdentity(
            kind=file_kind,
            normalized_sha256=value["normalized_sha256"],
            raw_sha256=value["raw_sha256"],
            size=size,
        )
    )


def _decode_observed_state(
    value: object, subject: str
) -> Result[FileState, ReceiptError]:
    """Decode an observed pre-state file: the full POSIX mode domain is legal."""
    if value is None:
        return Ok(FileState(None, None))
    if not isinstance(value, dict) or set(value) != {
        "kind",
        "mode",
        "normalized_sha256",
        "raw_sha256",
        "size",
    }:
        return Err(_receipt_error(subject))
    kind = value.get("kind")
    mode = value.get("mode")
    size = value.get("size")
    match kind:
        case "text":
            file_kind: Literal["text", "binary"] = "text"
        case "binary":
            file_kind = "binary"
        case _:
            return Err(_receipt_error(subject))
    if (
        not isinstance(mode, int)
        or not 0 <= mode <= 0o7777
        or not _is_digest(value.get("normalized_sha256"))
        or not _is_digest(value.get("raw_sha256"))
        or not isinstance(size, int)
        or size < 0
    ):
        return Err(_receipt_error(subject))
    return Ok(
        FileState(
            identity=FileContentIdentity(
                kind=file_kind,
                normalized_sha256=value["normalized_sha256"],
                raw_sha256=value["raw_sha256"],
                size=size,
            ),
            mode=PosixMode(mode),
        )
    )


def _decode_operation(value: object) -> Result[None, ReceiptError]:
    if not isinstance(value, dict):
        return Err(_receipt_error("operation"))
    kind = value.get("kind")
    if kind in _FILE_OPERATION_KINDS:
        if set(value) != {"kind", "path", "expected_old", "planned_new"}:
            return Err(_receipt_error("operation"))
        path = value.get("path")
        match _decode_path(path, "operation.path"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        match _decode_observed_state(
            value.get("expected_old"), "operation.expected_old"
        ):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        planned_new = value.get("planned_new")
        if kind == "delete_file":
            if planned_new is not None:
                return Err(_receipt_error("operation.planned_new"))
            return Ok(None)
        if not isinstance(planned_new, dict):
            return Err(_receipt_error("operation.planned_new"))
        match _decode_identity(planned_new, "operation.planned_new"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        content_id = planned_new.get("content_id")
        if not _is_digest(content_id):
            return Err(_receipt_error("operation.planned_new"))
        return Ok(None)
    if kind in _DIRECTORY_OPERATION_KINDS:
        if kind == "create_tree":
            if set(value) != {"kind", "root", "expected_old", "planned_new"}:
                return Err(_receipt_error("operation"))
            root = value.get("root")
            match _decode_path(root, "operation.root"):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass
            if value.get("expected_old") is not None:
                return Err(_receipt_error("operation.expected_old"))
            planned_new = value.get("planned_new")
            if not isinstance(planned_new, dict) or set(planned_new) != {
                "root_mode",
                "raw_tree_sha256",
                "entries",
            }:
                return Err(_receipt_error("operation.planned_new"))
            root_mode = planned_new.get("root_mode")
            raw_tree_sha256 = planned_new.get("raw_tree_sha256")
            entries = planned_new.get("entries")
            if (
                not isinstance(root_mode, int)
                or root_mode != PosixMode.DIRECTORY
                or not _is_digest(raw_tree_sha256)
                or not isinstance(entries, list)
            ):
                return Err(_receipt_error("operation.planned_new"))
            for entry in entries:
                match _decode_tree_entry(entry):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
            return Ok(None)
        if set(value) != {"kind", "path", "expected_old", "planned_new"}:
            return Err(_receipt_error("operation"))
        path = value.get("path")
        match _decode_path(path, "operation.path"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        expected_old = value.get("expected_old")
        if (
            not isinstance(expected_old, dict)
            or set(expected_old) != {"mode", "raw_tree_sha256"}
            or not isinstance(expected_old.get("mode"), int)
            or not 0 <= expected_old.get("mode") <= 0o7777
            or not _is_digest(expected_old.get("raw_tree_sha256"))
            or value.get("planned_new") is not None
        ):
            return Err(_receipt_error("operation.expected_old"))
        return Ok(None)
    return Err(_receipt_error("operation.kind"))


def _decode_tree_entry(value: object) -> Result[None, ReceiptError]:
    if not isinstance(value, dict) or "kind" not in value:
        return Err(_receipt_error("operation.entries"))
    kind = value.get("kind")
    if kind == "directory":
        if set(value) != {"kind", "path", "mode"}:
            return Err(_receipt_error("operation.entries"))
        match _decode_path(value.get("path"), "operation.entries"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        mode = value.get("mode")
        if not isinstance(mode, int) or mode != PosixMode.DIRECTORY:
            return Err(_receipt_error("operation.entries"))
        return Ok(None)
    if kind == "file":
        if set(value) != {
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
        match _decode_path(value.get("path"), "operation.entries"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        file_kind = value.get("file_kind")
        if file_kind not in ("text", "binary"):
            return Err(_receipt_error("operation.entries"))
        match _decode_identity(
            {
                "kind": file_kind,
                "mode": value["mode"],
                "normalized_sha256": value["normalized_sha256"],
                "raw_sha256": value["raw_sha256"],
                "size": value["size"],
                "content_id": value["content_id"],
            },
            "operation.entries",
        ):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        return Ok(None)
    return Err(_receipt_error("operation.entries"))


def _decode_gate(value: object) -> Result[None, ReceiptError]:
    if not isinstance(value, dict) or set(value) != {
        "operation",
        "artifact_verification",
        "template_contract",
        "readiness_rule",
        "expected_placeholder",
    }:
        return Err(_receipt_error("gate_specification"))
    operation = value.get("operation")
    artifact_verification = value.get("artifact_verification")
    template_contract = value.get("template_contract")
    readiness_rule = value.get("readiness_rule")
    expected_placeholder = value.get("expected_placeholder")
    if (
        operation not in _OPERATIONS
        or not isinstance(artifact_verification, bool)
        or not isinstance(template_contract, bool)
        or readiness_rule not in _READINESS_RULES
        or not isinstance(expected_placeholder, list)
    ):
        return Err(_receipt_error("gate_specification"))
    for finding in expected_placeholder:
        if not isinstance(finding, dict) or set(finding) != {
            "code",
            "subject_at",
            "subject",
            "rule",
            "severity",
        }:
            return Err(_receipt_error("gate_specification.expected_placeholder"))
        subject_at = finding.get("subject_at")
        if subject_at != "repository":
            match _decode_path(subject_at, "gate_specification.expected_placeholder"):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass
        if finding.get("severity") not in _SEVERITIES or not all(
            isinstance(finding.get(key), str) for key in ("code", "subject", "rule")
        ):
            return Err(_receipt_error("gate_specification.expected_placeholder"))
    return Ok(None)


def _decode_baseline(
    value: object, *, required: bool, generation: str
) -> Result[None, ReceiptError]:
    if value is None:
        if required:
            return Err(_receipt_error("source_after"))
        return Ok(None)
    if not isinstance(value, dict):
        return Err(_receipt_error("source_baseline"))
    kind = value.get("kind")
    fingerprint = value.get("fingerprint")
    entries = value.get("entries")
    if kind not in ("github", "copier") or not _is_digest(fingerprint):
        return Err(_receipt_error("source_baseline"))
    if kind != generation:
        return Err(_receipt_error("source_baseline"))
    expected_keys = (
        {"kind", "fingerprint", "entries", "snapshot_commit"}
        if kind == "github"
        else {"kind", "fingerprint", "entries"}
    )
    if set(value) != expected_keys:
        return Err(_receipt_error("source_baseline"))
    if kind == "github":
        snapshot_commit = value.get("snapshot_commit")
        if (
            not isinstance(snapshot_commit, str)
            or COMMIT_SHA.fullmatch(snapshot_commit) is None
        ):
            return Err(_receipt_error("source_baseline"))
    if not isinstance(entries, list):
        return Err(_receipt_error("source_baseline.entries"))
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "kind",
            "mode",
            "sha256",
        }:
            return Err(_receipt_error("source_baseline.entries"))
        match _decode_path(entry.get("path"), "source_baseline.entries"):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        kind = entry.get("kind")
        mode = entry.get("mode")
        if (
            kind not in ("file", "directory")
            or not isinstance(mode, int)
            or mode not in INSTALL_MODES
            or not _is_digest(entry.get("sha256"))
        ):
            return Err(_receipt_error("source_baseline.entries"))
    return Ok(None)
