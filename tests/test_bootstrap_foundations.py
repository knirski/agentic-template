from __future__ import annotations

import dataclasses
import unittest
from typing import cast

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
    SignalNumber,
    TransactionError,
    TransactionErrorKind,
    TransactionPrimitive,
    TransitionError,
    TransitionErrorKind,
    UsageError,
    UsageErrorKind,
    sanitize_errno,
)
from scripts.bootstrap.result import Err, Ok, Result, accumulate
from scripts.bootstrap.values import (
    DEFAULT_LIMITS,
    LimitKind,
    ResourceLimits,
    check_limit,
    freeze,
)


class ResultTests(unittest.TestCase):
    def test_result_maps_and_binds_without_raising_expected_errors(self) -> None:
        self.assertEqual(Ok(2).map(lambda value: value + 1), Ok(3))
        self.assertEqual(Ok(2).bind(lambda value: Ok(value * 2)), Ok(4))
        self.assertEqual(Err("bad").map(lambda value: value), Err("bad"))

    def test_accumulate_preserves_all_independent_errors(self) -> None:
        result = accumulate((Err("first"), Ok(2), Err("last")))
        self.assertEqual(result, Err(("first", "last")))

    @given(st.lists(st.integers(), max_size=20))
    def test_accumulate_preserves_arbitrary_success_order(
        self, values: list[int]
    ) -> None:
        result = cast(
            Result[tuple[int, ...], tuple[str, ...]],
            accumulate(tuple(Ok(value) for value in values)),
        )
        self.assertEqual(result, Ok(tuple(values)))

    @given(
        st.recursive(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(min_value=-(2**53 - 1), max_value=2**53 - 1),
                st.text(max_size=16, alphabet="abcdefghijklmnopqrstuvwxyz0123456789 "),
            ),
            lambda children: st.one_of(
                st.lists(children, max_size=8),
                st.dictionaries(
                    st.text(
                        max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
                    ),
                    children,
                    max_size=8,
                ),
            ),
            max_leaves=30,
        )
    )
    def test_canonical_json_round_trips_arbitrary_strict_values(
        self, value: object
    ) -> None:
        self.assertEqual(decode_json(canonical_json(value)), value)


class ValuesTests(unittest.TestCase):
    def test_freeze_deeply_removes_mutability(self) -> None:
        frozen = freeze({"nested": [1, {"value": "x"}]})
        self.assertEqual(frozen, (("nested", (1, (("value", "x"),))),))
        self.assertIsInstance(frozen, tuple)
        with self.assertRaises(TypeError):
            frozen[0] = ("changed", ())  # pyright: ignore[reportIndexIssue]  frozen tuple rejects __setitem__ at runtime

    def test_limits_are_frozen_and_have_the_v1_values(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(DEFAULT_LIMITS))
        self.assertTrue(dataclasses.is_dataclass(ResourceLimits))
        self.assertEqual(DEFAULT_LIMITS.max_paths, 4096)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            DEFAULT_LIMITS.max_paths = 1  # pyright: ignore[reportAttributeAccessIssue]  frozen dataclass rejects attribute set at runtime
        self.assertEqual(LimitKind.PATHS.value, "paths")

    def test_every_resource_limit_accepts_exact_and_rejects_one_over(self) -> None:
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
            self.assertIsInstance(check_limit(kind, limit, limits), Ok)
            over = check_limit(kind, limit + 1, limits)
            self.assertIsInstance(over, Err)
            if isinstance(over, Err):
                self.assertEqual(over.error.observed, limit + 1)

    def test_signal_number_accepts_only_process_signal_range(self) -> None:
        self.assertEqual(SignalNumber.from_int(1), Ok(SignalNumber(1)))
        self.assertEqual(SignalNumber.from_int(255), Ok(SignalNumber(255)))
        self.assertIsInstance(SignalNumber.from_int(0), Err)
        self.assertIsInstance(SignalNumber.from_int(256), Err)


class BlobStoreTests(unittest.TestCase):
    def test_equal_content_is_interned_once_and_ids_are_sha256(self) -> None:
        store = VerifiedBlobStore.empty()
        first = store.intern(b"hello")
        if not isinstance(first, Ok):
            self.fail(first.error)
        content_id, store = first.value
        second = store.intern(b"hello")
        if not isinstance(second, Ok):
            self.fail(second.error)
        same_id, final_store = second.value
        self.assertEqual(content_id, same_id)
        self.assertEqual(final_store.unique_bytes, 5)
        self.assertEqual(final_store.blob_count, 1)
        self.assertEqual(content_id, ContentId.from_bytes(b"hello"))

    def test_single_file_and_unique_byte_limits_fail_exactly_one_over(self) -> None:
        limits = ResourceLimits(max_file_bytes=4, max_unique_bytes=6)
        store = VerifiedBlobStore.empty(limits)
        self.assertIsInstance(store.intern(b"1234"), Ok)
        self.assertIsInstance(store.intern(b"12345"), Err)
        store = VerifiedBlobStore.empty(limits)
        first = store.intern(b"1234")
        if not isinstance(first, Ok):
            self.fail(first.error)
        _, store = first.value
        second = store.intern(b"56")
        if not isinstance(second, Ok):
            self.fail(second.error)
        _, store = second.value
        self.assertIsInstance(store.intern(b"7"), Err)


class DiagnosticTests(unittest.TestCase):
    def test_every_current_error_family_maps_to_a_stable_diagnostic(self) -> None:
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
            self.assertIsInstance(diagnostic, Diagnostic)
            self.assertTrue(diagnostic.code.startswith("BOOTSTRAP_"))
            self.assertIsInstance(diagnostic.next_action, NoAutomaticAction)

    def test_outcomes_are_frozen_typed_values(self) -> None:
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
        self.assertEqual(succeeded.exit_code, 0)
        self.assertEqual(action_required.exit_code, 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            diagnostic.code = "changed"  # pyright: ignore[reportAttributeAccessIssue]  frozen dataclass rejects attribute set at runtime

    def test_error_outcomes_preserve_each_error_family(self) -> None:
        cases = (
            (UsageError(UsageErrorKind.UNKNOWN_COMMAND), InvalidRequest),
            (InputError(InputErrorKind.WRONG_KIND), InvalidRequest),
            (ObservationError(ObservationErrorKind.PATH_MISSING), ActionRequired),
            (ContractError(ContractErrorKind.INVALID_TEMPLATE), ContractFailure),
            (
                TransitionError(TransitionErrorKind.OPERATION_UNAVAILABLE),
                ActionRequired,
            ),
            (TransactionError(TransactionErrorKind.INVALID_JOURNAL), RecoveryFailure),
            (InternalFailure(InternalCode.IMPOSSIBLE_STATE), DiagnosticInternalFailure),
        )
        for error, expected in cases:
            self.assertIsInstance(outcome_for_error(error), expected)

    def test_diagnostic_sanitizes_non_string_subjects(self) -> None:
        diagnostic = command_error_diagnostic(
            UsageError(UsageErrorKind.UNKNOWN_COMMAND, 42)  # pyright: ignore[reportArgumentType]  intentional non-string subject negative test
        )
        self.assertEqual(diagnostic.subject, "")

    def test_sanitize_errno_without_errno_uses_sanitized_class(self) -> None:
        # An OSError raised from a bare message has errno=None; the closed
        # vocabulary must still receive the sanitized fallback instead of
        # leaking a raw errno or failing to classify.
        self.assertEqual(
            sanitize_errno(OSError("no errno attached")),
            ErrnoClass.OTHER_SANITIZED_ERRNO,
        )

    def test_limit_diagnostic_reports_observed_and_configured_limits(self) -> None:
        diagnostic = limit_diagnostic("paths", 11, 10)
        self.assertEqual(diagnostic.code, "BOOTSTRAP_INPUT_LIMIT_PATHS")
        self.assertIn("Observed 11", diagnostic.details)


if __name__ == "__main__":
    _ = unittest.main()
