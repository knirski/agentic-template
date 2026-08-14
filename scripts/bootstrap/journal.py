"""Journal encoding, atomic persistence, and state-root classification.

``journal.json`` is the only authoritative record; ``journal.pending`` is the
transient atomic-write path and is never authoritative.  A leftover regular
no-follow pending file is never removed by status, planning, or an unrelated
mutation.  When no journal and no other transaction artifact exists a leftover
pending decodes as ``StaleJournalWrite``; any other state-root shape is
``OrphanTransactionState``.  Preparation identities record only the hash of
the ownership token; transaction IDs and tokens are lowercase 256-bit hex.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from scripts.bootstrap.canonical_json import (
    StrictJsonValue,
    canonical_json,
    decode_json,
)
from scripts.bootstrap.errors import (
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    sanitize_errno,
)
from scripts.bootstrap.fs_effects import (
    ChildEntry,
    ChildKind,
    classify_child,
    fsync_directory,
    fsync_file,
    list_directory_entries,
    map_observation_error,
    read_file_bounded,
    write_all,
)
from scripts.bootstrap.identity import (
    PosixMode,
    TargetIdentity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import PlanReceipt, decode_receipt
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import (
    InvalidJournal,
    JournalObservation,
    JournalTargetMismatch,
    NoJournal,
    OrphanTransactionState,
    PendingIdentity,
    StaleJournalWrite,
    ValidatedJournal,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, JournalPhase, ResourceLimits

JOURNAL_SCHEMA_VERSION = 1
_TRANSACTION_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ROOT_HEX = re.compile(r"(?:[0-9a-f]{2})+\Z")
_O_PENDING = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_O_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


class PreparationRole(StrEnum):
    STAGE = "stage"
    BACKUP = "backup"
    ROLLBACK = "rollback"


def _hex64(value: object) -> bool:
    return isinstance(value, str) and _TRANSACTION_HEX.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class JournalTarget:
    """The journaled target binding: identity fields plus the binding digest."""

    root_hex: str
    device: int
    inode: int
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.root_hex, str) or not _ROOT_HEX.fullmatch(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.root_hex
        ):
            raise TypeError("journal target root must be lowercase hex")
        root = bytes.fromhex(self.root_hex)
        if type(self.device) is not int or type(self.inode) is not int:
            raise TypeError("journal target device and inode must be integers")
        if self.device < 0 or self.inode < 0:
            raise TypeError("journal target device and inode must be non-negative")
        if self.device > 2**53 - 1 or self.inode > 2**53 - 1:
            raise TypeError("journal target device and inode exceed the JSON domain")
        if not _hex64(self.digest):
            raise TypeError("journal target digest must be 256-bit lowercase hex")
        expected = target_identity(root, device=self.device, inode=self.inode)
        if self.digest != expected.digest:
            raise TypeError("journal target digest does not match its binding")

    @classmethod
    def from_identity(cls, target: TargetIdentity) -> JournalTarget:
        return cls(
            root_hex=target.root_os_bytes.hex(),
            device=target.device,
            inode=target.inode,
            digest=target.digest,
        )

    def to_identity(self) -> TargetIdentity:
        return target_identity(
            bytes.fromhex(self.root_hex), device=self.device, inode=self.inode
        )


@dataclass(frozen=True, slots=True)
class PreparationIdentity:
    """The engine-owned identity of one reserved stage or backup location."""

    transaction_id: str
    operation_index: int
    role: PreparationRole
    ownership_token_sha256: str
    expected_kind: Literal["file", "directory"]
    expected_raw_sha256: str | None
    expected_mode: PosixMode

    def __post_init__(self) -> None:
        if not _hex64(self.transaction_id):
            raise TypeError("preparation transaction id must be 256-bit lowercase hex")
        if type(self.operation_index) is not int or self.operation_index < 0:
            raise TypeError("preparation operation index must be non-negative")
        if not isinstance(self.role, PreparationRole):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("preparation requires a closed role")
        if not _hex64(self.ownership_token_sha256):
            raise TypeError("preparation token hash must be 256-bit lowercase hex")
        if self.expected_kind not in ("file", "directory"):
            raise TypeError("preparation requires a closed expected kind")
        if self.expected_kind == "file":
            if not _hex64(self.expected_raw_sha256):
                raise TypeError("file preparation requires a raw digest")
        elif self.expected_raw_sha256 is not None:
            raise TypeError("directory preparation cannot carry a raw digest")
        if not isinstance(self.expected_mode, PosixMode):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("preparation requires an exact expected mode")


@dataclass(frozen=True, slots=True)
class JournalEnvelope:
    """The complete authoritative journal record for one transaction phase.

    ``receipt`` is the byte-erased plan receipt: it carries every identity,
    mode, path, and topology the recovery reducers need without any file
    bytes.  New journals always record it; a journal written before the
    receipt field existed decodes with ``receipt=None`` and phase recovery
    that requires the plan refuses with ``RecoveryEvidenceInvalid``.
    """

    operation: str
    target: JournalTarget
    phase: JournalPhase
    transaction_id: str
    preparations: tuple[PreparationIdentity, ...] = ()
    receipt: PlanReceipt | None = None
    schema_version: int = JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != JOURNAL_SCHEMA_VERSION
        ):
            raise TypeError("journal requires the current schema version")
        if (
            not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
                self.operation, str
            )
            or not self.operation
        ):
            raise TypeError("journal requires a non-empty operation")
        if not isinstance(self.target, JournalTarget):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("journal requires a target binding")
        if not isinstance(self.phase, JournalPhase):  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            raise TypeError("journal requires a closed phase")
        if not _hex64(self.transaction_id):
            raise TypeError("journal requires a 256-bit lowercase transaction id")
        if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
            self.preparations, tuple
        ) or any(
            not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check
                preparation, PreparationIdentity
            )
            for preparation in self.preparations
        ):
            raise TypeError("journal preparations must be preparation identities")
        if any(
            preparation.transaction_id != self.transaction_id
            for preparation in self.preparations
        ):
            raise TypeError("every preparation must belong to the journal transaction")
        if self.receipt is not None and not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]  deliberate runtime contract check on a hand-constructible record
            self.receipt, dict
        ):
            raise TypeError("journal receipt must be a plan receipt mapping")


def new_transaction_id() -> str:
    """Allocate an unpredictable lowercase 256-bit transaction id."""

    return os.urandom(32).hex()


def new_ownership_token() -> bytes:
    """Allocate an independent 256-bit ownership token; only its hash is journaled."""

    return os.urandom(32)


def derive_preparation_identity(
    transaction_id: str,
    operation_index: int,
    role: PreparationRole,
    ownership_token: bytes,
    *,
    expected_kind: Literal["file", "directory"],
    expected_raw_sha256: str | None,
    expected_mode: PosixMode,
) -> PreparationIdentity:
    """Derive the journaled identity of one reserved preparation location."""

    return PreparationIdentity(
        transaction_id=transaction_id,
        operation_index=operation_index,
        role=role,
        ownership_token_sha256=sha256_hex(ownership_token),
        expected_kind=expected_kind,
        expected_raw_sha256=expected_raw_sha256,
        expected_mode=expected_mode,
    )


def backup_relative_path(transaction_id: str, operation_index: int) -> RepoPath:
    """Derive the state-root-relative administrative backup location."""

    return RepoPath(f"transactions/{transaction_id}/backups/{operation_index}")


def encode_journal(envelope: JournalEnvelope) -> bytes:
    """Serialize the journal envelope as strict canonical JSON."""

    document: dict[str, object] = {
        "schema_version": envelope.schema_version,
        "operation": envelope.operation,
        "target": {
            "root": envelope.target.root_hex,
            "device": envelope.target.device,
            "inode": envelope.target.inode,
            "digest": envelope.target.digest,
        },
        "phase": envelope.phase.value,
        "transaction_id": envelope.transaction_id,
        "preparations": [
            {
                "transaction_id": preparation.transaction_id,
                "operation_index": preparation.operation_index,
                "role": preparation.role.value,
                "ownership_token_sha256": preparation.ownership_token_sha256,
                "expected_kind": preparation.expected_kind,
                "expected_raw_sha256": preparation.expected_raw_sha256,
                "expected_mode": preparation.expected_mode.value,
            }
            for preparation in envelope.preparations
        ],
    }
    if envelope.receipt is not None:
        document["receipt"] = envelope.receipt
    return canonical_json(document)


def _invalid[ValueT](reason: str) -> Result[ValueT, InvalidJournal]:
    return Err(InvalidJournal(reason))


def _decode_target(value: StrictJsonValue) -> Result[JournalTarget, InvalidJournal]:
    if not isinstance(value, dict):
        return _invalid("journal target must be an object")
    root = value.get("root")
    device = value.get("device")
    inode = value.get("inode")
    digest = value.get("digest")
    if not isinstance(root, str) or not root:
        return _invalid("journal target root must be non-empty hex")
    if type(device) is not int or type(inode) is not int:
        return _invalid("journal target device and inode must be integers")
    if device < 0 or inode < 0:
        return _invalid("journal target device and inode must be non-negative")
    if not isinstance(digest, str) or not _hex64(digest):
        return _invalid("journal target digest must be 256-bit lowercase hex")
    try:
        return Ok(
            JournalTarget(root_hex=root, device=device, inode=inode, digest=digest)
        )
    except TypeError as error:
        return _invalid(str(error))


def _decode_preparation(
    value: StrictJsonValue, transaction_id: str
) -> Result[PreparationIdentity, InvalidJournal]:
    if not isinstance(value, dict):
        return _invalid("journal preparation must be an object")
    role_value = value.get("role")
    if not isinstance(role_value, str):
        return _invalid("journal preparation requires a closed role")
    try:
        role = PreparationRole(role_value)
    except ValueError:
        return _invalid("journal preparation requires a closed role")
    declared_transaction = value.get("transaction_id")
    if declared_transaction != transaction_id:
        return _invalid("every preparation must belong to the journal transaction")
    token_hash = value.get("ownership_token_sha256")
    if not isinstance(token_hash, str) or not _hex64(token_hash):
        return _invalid("journal preparation token hash must be 256-bit lowercase hex")
    operation_index = value.get("operation_index")
    if type(operation_index) is not int or operation_index < 0:
        return _invalid("journal preparation requires a non-negative integer index")
    expected_kind = value.get("expected_kind")
    expected_raw_sha256 = value.get("expected_raw_sha256")
    match expected_kind:
        case "file":
            if not isinstance(expected_raw_sha256, str) or not _hex64(
                expected_raw_sha256
            ):
                return _invalid("file preparation requires a raw digest")
            raw_digest: str | None = expected_raw_sha256
        case "directory":
            if expected_raw_sha256 is not None:
                return _invalid("directory preparation cannot carry a raw digest")
            raw_digest = None
        case _:
            return _invalid("journal preparation requires a closed expected kind")
    expected_mode = value.get("expected_mode")
    if type(expected_mode) is not int:
        return _invalid("journal preparation requires an integer mode")
    try:
        mode = PosixMode(expected_mode)
    except ValueError:
        return _invalid("journal preparation mode is outside the POSIX domain")
    try:
        return Ok(
            PreparationIdentity(
                transaction_id=transaction_id,
                operation_index=operation_index,
                role=role,
                ownership_token_sha256=token_hash,
                expected_kind=expected_kind,
                expected_raw_sha256=raw_digest,
                expected_mode=mode,
            )
        )
    except TypeError as error:  # pragma: no cover  defensive — every preparation field is validated above, so the frozen constructor cannot fail
        return _invalid(f"journal preparation is invalid: {error}")


def decode_journal(data: bytes) -> Result[JournalEnvelope, InvalidJournal]:
    """Strictly decode and validate one authoritative journal record."""

    try:
        decoded = decode_json(data)
    except ValueError as error:
        return _invalid(str(error))
    if not isinstance(decoded, dict):
        return _invalid("journal must be a JSON object")
    if (
        type(decoded.get("schema_version")) is not int
        or decoded.get("schema_version") != JOURNAL_SCHEMA_VERSION
    ):
        return _invalid("journal requires the current schema version")
    operation = decoded.get("operation")
    if not isinstance(operation, str) or not operation:
        return _invalid("journal requires a non-empty operation")
    transaction_id = decoded.get("transaction_id")
    if not isinstance(transaction_id, str) or not _hex64(transaction_id):
        return _invalid("journal requires a 256-bit lowercase transaction id")
    phase_value = decoded.get("phase")
    if not isinstance(phase_value, str):
        return _invalid("journal requires a closed phase")
    try:
        phase = JournalPhase(phase_value)
    except ValueError:
        return _invalid("journal requires a closed phase")
    match _decode_target(decoded.get("target")):
        case Err(error):
            return Err(error)
        case Ok(target):
            pass
    preparations_value = decoded.get("preparations")
    if not isinstance(preparations_value, list):
        return _invalid("journal preparations must be a list")
    preparations: list[PreparationIdentity] = []
    for item in preparations_value:
        match _decode_preparation(item, transaction_id):
            case Err(error):
                return Err(error)
            case Ok(preparation):
                preparations.append(preparation)
    raw_receipt = decoded.get("receipt")
    receipt: PlanReceipt | None = None
    if raw_receipt is not None:
        if not isinstance(raw_receipt, dict):
            return _invalid("journal receipt must be a plan receipt mapping")
        try:
            receipt_bytes = canonical_json(raw_receipt)
        except ValueError:  # pragma: no cover  defensive — decode_json already rejected every value canonical_json rejects
            return _invalid("journal receipt must be strict JSON")
        match decode_receipt(receipt_bytes):
            case Err(error):
                return _invalid(f"journal receipt is invalid: {error.kind.value}")
            case Ok(validated):
                receipt = validated
    return Ok(
        JournalEnvelope(
            operation=operation,
            target=target,
            phase=phase,
            transaction_id=transaction_id,
            preparations=tuple(preparations),
            receipt=receipt,
        )
    )


def persist_journal(
    state_root_fd: int, envelope: JournalEnvelope
) -> Result[None, TransactionError]:
    """Atomically replace the authoritative journal through the pending path.

    The pending file is created exclusively without following symlinks, the
    payload is written and fsynced, the file is renamed over ``journal.json``,
    and the state root is fsynced.  A leftover pending file blocks persistence:
    only recovery may discard it.
    """

    data = encode_journal(envelope)
    try:
        fd = os.open("journal.pending", _O_PENDING, 0o600, dir_fd=state_root_fd)
    except FileExistsError:
        return Err(
            TransactionError(
                TransactionErrorKind.INVALID_STATE_ROOT,
                subject="journal.pending exists; only recover may discard it",
            )
        )
    except OSError as error:
        return Err(
            TransactionError.primitive_failed(
                TransactionPrimitive.WRITE_FILE,
                sanitize_errno(error),
                "journal.pending",
            )
        )
    try:
        match write_all(fd, data):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
        match fsync_file(fd):
            case Err(error):
                return Err(error)
            case Ok(_):
                pass
    finally:
        os.close(fd)
    try:
        os.replace(
            "journal.pending",
            "journal.json",
            src_dir_fd=state_root_fd,
            dst_dir_fd=state_root_fd,
        )
    except OSError as error:
        return Err(
            TransactionError(
                TransactionErrorKind.ATOMIC_REPLACE_FAILED,
                errno_class=sanitize_errno(error),
                subject="journal",
            )
        )
    match fsync_directory(state_root_fd):
        case Err(error):
            return Err(error)
        case Ok(_):
            return Ok(None)


@dataclass(frozen=True, slots=True)
class StateRootSnapshot:
    """One raw coherent pass over the state root and its authoritative records."""

    target: TargetIdentity
    entries: tuple[bytes, ...]
    journal: bytes | None
    journal_irregular: bool
    pending: bytes | None
    pending_irregular: bool


def _capture_child(
    state_root_fd: int, name: bytes, limits: ResourceLimits
) -> Result[tuple[bytes | None, bool], ObservationError | InternalFailure]:
    match classify_child(state_root_fd, name):
        case Err(error):
            return Err(error)
        case Ok(ChildEntry(kind=ChildKind.ABSENT)):
            return Ok((None, False))
        case Ok(ChildEntry(kind=ChildKind.REGULAR, nlink=nlink)) if nlink != 1:
            return Ok((None, True))
        case Ok(ChildEntry(kind=ChildKind.REGULAR)):
            try:
                fd = os.open(name, _O_READ, dir_fd=state_root_fd)
            except OSError as error:
                return Err(map_observation_error(error, os.fsdecode(name)))
            try:
                match read_file_bounded(fd, limits.max_file_bytes, os.fsdecode(name)):
                    case Err(error):
                        return Err(error)
                    case Ok(content):
                        return Ok((content, False))
            finally:
                os.close(fd)
        case Ok(_):
            return Ok((None, True))


def capture_state_root(
    state_root_fd: int,
    target: TargetIdentity,
    *,
    limits: ResourceLimits = DEFAULT_LIMITS,
) -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
    """Capture one raw state-root pass for coherent comparison and decoding."""

    match list_directory_entries(state_root_fd):
        case Err(error):
            return Err(error)
        case Ok(names):
            pass
    match _capture_child(state_root_fd, b"journal.json", limits):
        case Err(error):
            return Err(error)
        case Ok(journal):
            pass
    match _capture_child(state_root_fd, b"journal.pending", limits):
        case Err(error):
            return Err(error)
        case Ok(pending):
            pass
    journal_bytes, journal_irregular = journal
    pending_bytes, pending_irregular = pending
    return Ok(
        StateRootSnapshot(
            target=target,
            entries=names,
            journal=journal_bytes,
            journal_irregular=journal_irregular,
            pending=pending_bytes,
            pending_irregular=pending_irregular,
        )
    )


def classify_state_root(snapshot: StateRootSnapshot) -> JournalObservation:
    """Interpret one coherent state-root pass as a closed journal observation."""

    allowed = frozenset({b"lock", b"journal.json", b"journal.pending", b"transactions"})
    for entry in snapshot.entries:
        if entry not in allowed:
            return OrphanTransactionState(
                f"unexpected state-root entry: {os.fsdecode(entry)}"
            )
    if snapshot.journal_irregular:
        return InvalidJournal("journal.json is not a regular file")
    if snapshot.journal is not None:
        match decode_journal(snapshot.journal):
            case Err(error):
                return error
            case Ok(envelope):
                journal = ValidatedJournal(
                    operation=envelope.operation,
                    target=envelope.target.to_identity(),
                    phase=envelope.phase,
                )
                if journal.target == snapshot.target:
                    return journal
                return JournalTargetMismatch(journal=journal, target=snapshot.target)
    if b"transactions" in snapshot.entries:
        return OrphanTransactionState("transactions directory without a journal")
    if snapshot.pending_irregular:
        return OrphanTransactionState("journal.pending is not a regular file")
    if snapshot.pending is not None:
        return StaleJournalWrite(PendingIdentity(digest=sha256_hex(snapshot.pending)))
    return NoJournal()


type CaptureFn = Callable[
    [int, TargetIdentity],
    Result[StateRootSnapshot, ObservationError | InternalFailure],
]


def collect_state_root_observation(
    state_root_fd: int,
    target: TargetIdentity,
    *,
    max_attempts: int = 3,
    limits: ResourceLimits = DEFAULT_LIMITS,
    capture: CaptureFn | None = None,
) -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
    """Return the second of two identical bounded passes, retrying boundedly."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    capture_fn: CaptureFn = (
        capture
        if capture is not None
        else (lambda fd, current: capture_state_root(fd, current, limits=limits))
    )

    def pass_once() -> Result[StateRootSnapshot, ObservationError | InternalFailure]:
        return capture_fn(state_root_fd, target)

    for _ in range(max_attempts):
        match pass_once():
            case Err(error):
                return Err(error)
            case Ok(first):
                match pass_once():
                    case Err(error):
                        return Err(error)
                    case Ok(second):
                        if first == second:
                            return Ok(second)
    return Err(
        ObservationError(
            ObservationErrorKind.CONCURRENT_TARGET_CHANGE,
            "state root changed during three observation attempts",
        )
    )
