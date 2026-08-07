"""Closed expected-error families for the bootstrap functional core."""

from __future__ import annotations

import errno
from dataclasses import dataclass
from enum import StrEnum


class UsageErrorKind(StrEnum):
    UNKNOWN_COMMAND = "unknown_command"
    UNKNOWN_OPTION = "unknown_option"
    MISSING_OPTION = "missing_option"
    CONFLICTING_OPTIONS = "conflicting_options"
    INVALID_VALUE = "invalid_value"


class InputErrorKind(StrEnum):
    MISSING_INPUT = "missing_input"
    WRONG_KIND = "wrong_kind"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_JSON = "invalid_json"
    SCHEMA_VIOLATION = "schema_violation"
    DIGEST_MISMATCH = "digest_mismatch"
    MARKER_COLLISION = "marker_collision"
    UNSAFE_RELATIVE_PATH = "unsafe_relative_path"
    INPUT_LIMIT_EXCEEDED = "input_limit_exceeded"


class ObservationErrorKind(StrEnum):
    PATH_MISSING = "path_missing"
    PERMISSION_DENIED = "permission_denied"
    SYMLINK_ENCOUNTERED = "symlink_encountered"
    HARDLINK_ENCOUNTERED = "hardlink_encountered"
    UNSUPPORTED_FILESYSTEM = "unsupported_filesystem"
    GIT_UNAVAILABLE = "git_unavailable"
    GIT_COMMAND_FAILED = "git_command_failed"
    CONCURRENT_TARGET_CHANGE = "concurrent_target_change"
    PROCESS_LAUNCH_FAILED = "process_launch_failed"
    PROCESS_SIGNALLED = "process_signalled"
    OBSERVATION_LIMIT_EXCEEDED = "observation_limit_exceeded"


class ContractErrorKind(StrEnum):
    INVALID_TEMPLATE = "invalid_template"
    INVALID_MANIFEST = "invalid_manifest"
    INCOMPATIBLE_CATALOG = "incompatible_catalog"
    RENDER_CONTRACT_VIOLATION = "render_contract_violation"
    CLEANUP_CONTRACT_INVALID = "cleanup_contract_invalid"
    SOURCE_CONTRACT_INVALID = "source_contract_invalid"
    INVALID_OPERATION_PLAN = "invalid_operation_plan"
    PLAN_LIMIT_EXCEEDED = "plan_limit_exceeded"


class TransitionErrorKind(StrEnum):
    OPERATION_UNAVAILABLE = "operation_unavailable"
    INPUT_CHANGED = "input_changed"
    MANAGED_DRIFT = "managed_drift"
    TEMPLATE_CHANGED = "template_changed"
    COPIER_CONFLICTS = "copier_conflicts"
    UNSUPPORTED_TARGET = "unsupported_target"
    RECOVERY_REQUIRED = "recovery_required"
    LOCK_HELD = "lock_held"
    OUTPUT_LOCATION_OCCUPIED = "output_location_occupied"
    RECOVERY_TARGET_MISMATCH = "recovery_target_mismatch"
    RECOVERY_THIRD_STATE = "recovery_third_state"


class TransactionPrimitive(StrEnum):
    CREATE_STAGE = "create_stage"
    CREATE_BACKUP = "create_backup"
    READ_BACKUP = "read_backup"
    WRITE_FILE = "write_file"
    SET_MODE = "set_mode"
    CREATE_DIRECTORY = "create_directory"
    REMOVE_FILE = "remove_file"
    REMOVE_DIRECTORY = "remove_directory"
    REPLACE_PATH = "replace_path"
    CLEANUP_STATE = "cleanup_state"


class ErrnoClass(StrEnum):
    PERMISSION = "permission"
    READ_ONLY = "read_only"
    NO_SPACE = "no_space"
    QUOTA = "quota"
    MISSING = "missing"
    EXISTS = "exists"
    NOT_DIRECTORY = "not_directory"
    IS_DIRECTORY = "is_directory"
    CROSS_DEVICE = "cross_device"
    UNSUPPORTED = "unsupported"
    INTERRUPTED = "interrupted"
    SHORT_WRITE = "short_write"
    OTHER_SANITIZED_ERRNO = "other_sanitized_errno"


class ProcessErrorKind(StrEnum):
    EXECUTABLE_NOT_FOUND = "executable_not_found"
    EXECUTE_PERMISSION_DENIED = "execute_permission_denied"
    INVALID_EXECUTABLE = "invalid_executable"
    PROCESS_RESOURCE_UNAVAILABLE = "process_resource_unavailable"
    UNSUPPORTED_PROCESS_OPERATION = "unsupported_process_operation"
    OTHER_SANITIZED_LAUNCH_ERROR = "other_sanitized_launch_error"


class InternalCode(StrEnum):
    UNCLASSIFIED_EXCEPTION = "unclassified_exception"
    IMPOSSIBLE_STATE = "impossible_state"


@dataclass(frozen=True, slots=True)
class ProcessError:
    kind: ProcessErrorKind


@dataclass(frozen=True, slots=True)
class UsageError:
    kind: UsageErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class InputError:
    kind: InputErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ObservationError:
    kind: ObservationErrorKind
    subject: str = ""
    process: ProcessError | None = None
    signal: int | None = None


@dataclass(frozen=True, slots=True)
class ContractError:
    kind: ContractErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class TransitionError:
    kind: TransitionErrorKind
    subject: str = ""


@dataclass(frozen=True, slots=True)
class TransactionError:
    primitive: TransactionPrimitive
    errno_class: ErrnoClass
    subject: str = ""


@dataclass(frozen=True, slots=True)
class InternalFailure:
    code: InternalCode = InternalCode.UNCLASSIFIED_EXCEPTION


type CommandError = (
    UsageError
    | InputError
    | ObservationError
    | ContractError
    | TransitionError
    | TransactionError
    | InternalFailure
)


def sanitize_process_error(error: BaseException) -> ProcessError:
    """Map process-launch exceptions to the finite process error vocabulary."""

    if isinstance(error, FileNotFoundError):
        kind = ProcessErrorKind.EXECUTABLE_NOT_FOUND
    elif isinstance(error, PermissionError):
        kind = ProcessErrorKind.EXECUTE_PERMISSION_DENIED
    elif isinstance(error, (NotImplementedError, ValueError)):
        kind = ProcessErrorKind.UNSUPPORTED_PROCESS_OPERATION
    else:
        kind = ProcessErrorKind.OTHER_SANITIZED_LAUNCH_ERROR
    return ProcessError(kind)


def sanitize_errno(error: OSError) -> ErrnoClass:
    """Map OS details to the finite errno vocabulary without retaining the exception."""

    mapping = {
        errno.EACCES: ErrnoClass.PERMISSION,
        errno.EROFS: ErrnoClass.READ_ONLY,
        errno.ENOSPC: ErrnoClass.NO_SPACE,
        errno.EDQUOT: ErrnoClass.QUOTA,
        errno.ENOENT: ErrnoClass.MISSING,
        errno.EEXIST: ErrnoClass.EXISTS,
        errno.ENOTDIR: ErrnoClass.NOT_DIRECTORY,
        errno.EISDIR: ErrnoClass.IS_DIRECTORY,
        errno.EXDEV: ErrnoClass.CROSS_DEVICE,
        errno.ENOTSUP: ErrnoClass.UNSUPPORTED,
        errno.EINTR: ErrnoClass.INTERRUPTED,
    }
    return mapping.get(error.errno, ErrnoClass.OTHER_SANITIZED_ERRNO)
