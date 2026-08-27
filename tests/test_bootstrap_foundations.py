from __future__ import annotations

import dataclasses

from hypothesis import given
from hypothesis import strategies as st

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.diagnostics import (
    ActionRequired,
    ContractFailure,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticSeverity,
    InvalidRequest,
    NoAutomaticAction,
    RecoveryFailure,
    Succeeded,
    command_error_diagnostic,
    limit_diagnostic,
    outcome_for_error,
)
from scripts.bootstrap.diagnostics import (
    InternalFailure as DiagnosticInternalFailure,
)
from scripts.bootstrap.errors import (
    ContractError,
    ContractErrorKind,
    ErrnoClass,
    InputError,
    InputErrorKind,
    InternalCode,
    InternalFailure,
    ObservationError,
    ObservationErrorKind,
    ProcessError,
    ProcessErrorKind,
    SignalNumber,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
    UsageError,
    UsageErrorKind,
    sanitize_errno,
    sanitize_process_error,
)
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.values import (
    DEFAULT_LIMITS,
    LimitKind,
    ResourceLimits,
    check_limit,
)


@given(
    st.recursive(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-(2**53 - 1), max_value=2**53 - 1),
            st.floats(
                allow_nan=False,
                allow_infinity=False,
                min_value=-(2**53 - 1),
                max_value=2**53 - 1,
            ),
            st.text(max_size=16, alphabet="abcdefghijklmnopqrstuvwxyz0123456789 "),
        ),
        lambda children: st.one_of(
            st.lists(children, max_size=8),
            st.dictionaries(
                st.text(max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
                children,
                max_size=8,
            ),
        ),
        max_leaves=30,
    )
)
def test_canonical_json_round_trips_arbitrary_strict_values(value: object) -> None:
    assert decode_json(canonical_json(value)) == value


def test_sanitize_process_error_maps_launch_failures() -> None:
    assert sanitize_process_error(FileNotFoundError()) == ProcessError(
        ProcessErrorKind.EXECUTABLE_NOT_FOUND
    )
    assert sanitize_process_error(PermissionError()) == ProcessError(
        ProcessErrorKind.EXECUTE_PERMISSION_DENIED
    )
    assert sanitize_process_error(ValueError("unsupported")) == ProcessError(
        ProcessErrorKind.UNSUPPORTED_PROCESS_OPERATION
    )
    assert sanitize_process_error(RuntimeError("other")) == ProcessError(
        ProcessErrorKind.OTHER_SANITIZED_LAUNCH_ERROR
    )


def test_limits_are_frozen_and_have_the_v1_values() -> None:
    assert dataclasses.is_dataclass(DEFAULT_LIMITS)
    assert dataclasses.is_dataclass(ResourceLimits)
    assert DEFAULT_LIMITS.max_paths == 4096
    try:
        DEFAULT_LIMITS.max_paths = 1  # pyright: ignore[reportAttributeAccessIssue]  frozen dataclass rejects attribute set at runtime
        raise AssertionError("expected FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        pass
    assert LimitKind.PATHS.value == "paths"


def test_every_resource_limit_accepts_exact_and_rejects_one_over() -> None:
    limits = ResourceLimits(
        max_paths=2,
        max_operations=3,
        max_file_bytes=4,
        max_unique_bytes=5,
        max_diagnostics=6,
        max_path_bytes=7,
        max_component_bytes=8,
        max_components=9,
    )
    for kind, limit in (
        (LimitKind.PATHS, 2),
        (LimitKind.OPERATIONS, 3),
        (LimitKind.FILE_BYTES, 4),
        (LimitKind.UNIQUE_BYTES, 5),
        (LimitKind.DIAGNOSTICS, 6),
        (LimitKind.PATH_BYTES, 7),
        (LimitKind.COMPONENT_BYTES, 8),
        (LimitKind.COMPONENTS, 9),
    ):
        assert isinstance(check_limit(kind, limit, limits), Ok)
        over = check_limit(kind, limit + 1, limits)
        assert isinstance(over, Err)
        assert over.error.observed == limit + 1


def test_signal_number_accepts_only_process_signal_range() -> None:
    assert SignalNumber.from_int(1) == Ok(SignalNumber(1))
    assert SignalNumber.from_int(255) == Ok(SignalNumber(255))
    assert isinstance(SignalNumber.from_int(0), Err)
    assert isinstance(SignalNumber.from_int(256), Err)


def test_equal_content_is_interned_once_and_ids_are_sha256() -> None:
    store = VerifiedBlobStore.empty()
    first = store.intern(b"hello")
    if not isinstance(first, Ok):
        raise AssertionError(first.error)
    content_id, store = first.value
    second = store.intern(b"hello")
    if not isinstance(second, Ok):
        raise AssertionError(second.error)
    same_id, final_store = second.value
    assert content_id == same_id
    assert final_store.unique_bytes == 5
    assert final_store.blob_count == 1
    assert content_id == ContentId.from_bytes(b"hello")


def test_single_file_and_unique_byte_limits_fail_exactly_one_over() -> None:
    limits = ResourceLimits(max_file_bytes=4, max_unique_bytes=6)
    store = VerifiedBlobStore.empty(limits)
    assert isinstance(store.intern(b"1234"), Ok)
    assert isinstance(store.intern(b"12345"), Err)
    store = VerifiedBlobStore.empty(limits)
    first = store.intern(b"1234")
    if not isinstance(first, Ok):
        raise AssertionError(first.error)
    _, store = first.value
    second = store.intern(b"56")
    if not isinstance(second, Ok):
        raise AssertionError(second.error)
    _, store = second.value
    assert isinstance(store.intern(b"7"), Err)


def test_every_current_error_family_maps_to_a_stable_diagnostic() -> None:
    errors = [
        *(UsageError(kind, "wat") for kind in UsageErrorKind),
        *(InputError(kind, "input") for kind in InputErrorKind),
        *(ObservationError(kind, "target") for kind in ObservationErrorKind),
        *(ContractError(kind, "template") for kind in ContractErrorKind),
        *(TransitionError(kind, "project") for kind in TransitionErrorKind),
        *(
            TransactionError.primitive_failed(
                primitive, ErrnoClass.OTHER_SANITIZED_ERRNO
            )
            for primitive in TransactionPrimitive
        ),
        *(
            TransactionError(kind)
            for kind in TransactionErrorKind
            if kind is not TransactionErrorKind.PRIMITIVE_FAILED
        ),
        InternalFailure(InternalCode.UNCLASSIFIED_EXCEPTION),
    ]
    for error in errors:
        diagnostic = command_error_diagnostic(error)
        assert isinstance(diagnostic, Diagnostic)
        assert diagnostic.code.startswith("BOOTSTRAP_")
        assert isinstance(diagnostic.next_action, NoAutomaticAction)


def test_outcomes_are_frozen_typed_values() -> None:
    diagnostic = Diagnostic(
        code="BOOTSTRAP_INPUT_TEST",
        category=DiagnosticCategory.INPUT,
        severity=DiagnosticSeverity.ERROR,
        subject="bundle.json",
        summary="Invalid input",
        details="The input is invalid.",
        next_action=NoAutomaticAction("provide valid input"),
    )
    succeeded = Succeeded(diagnostics=())
    action_required = ActionRequired(diagnostics=(diagnostic,))
    assert succeeded.exit_code == 0
    assert action_required.exit_code == 1
    try:
        diagnostic.code = "changed"  # pyright: ignore[reportAttributeAccessIssue]  frozen dataclass rejects attribute set at runtime
        raise AssertionError("expected FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        pass


def test_error_outcomes_preserve_each_error_family() -> None:
    cases = (
        (UsageError(UsageErrorKind.UNKNOWN_COMMAND), InvalidRequest),
        (InputError(InputErrorKind.WRONG_KIND), InvalidRequest),
        # An observation that prevents trustworthy decoding is a contract
        # failure (design: ``ContractFailure``), never an advisory refusal.
        (ObservationError(ObservationErrorKind.PATH_MISSING), ContractFailure),
        (ContractError(ContractErrorKind.INVALID_TEMPLATE), ContractFailure),
        (
            TransitionError(TransitionErrorKind.OPERATION_UNAVAILABLE),
            ActionRequired,
        ),
        (TransactionError(TransactionErrorKind.INVALID_JOURNAL), RecoveryFailure),
        (InternalFailure(InternalCode.IMPOSSIBLE_STATE), DiagnosticInternalFailure),
    )
    for error, expected in cases:
        assert isinstance(outcome_for_error(error), expected)


def test_diagnostic_sanitizes_non_string_subjects() -> None:
    diagnostic = command_error_diagnostic(
        UsageError(UsageErrorKind.UNKNOWN_COMMAND, 42)  # pyright: ignore[reportArgumentType]  intentional non-string subject negative test
    )
    assert diagnostic.subject == ""


def test_sanitize_errno_without_errno_uses_sanitized_class() -> None:
    # An OSError raised from a bare message has errno=None; the closed
    # vocabulary must still receive the sanitized fallback instead of
    # leaking a raw errno or failing to classify.
    assert (
        sanitize_errno(OSError("no errno attached")) == ErrnoClass.OTHER_SANITIZED_ERRNO
    )


def test_limit_diagnostic_reports_observed_and_configured_limits() -> None:
    diagnostic = limit_diagnostic("paths", 11, 10)
    assert diagnostic.code == "BOOTSTRAP_INPUT_LIMIT_PATHS"
    assert "Observed 11" in diagnostic.details
