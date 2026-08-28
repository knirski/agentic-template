from __future__ import annotations

import tempfile
from pathlib import Path
from typing import cast

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from scripts.bootstrap.blobs import BlobRecord, ContentId, VerifiedBlobStore
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.values import ResourceLimits


class BlobStoreStateMachine(RuleBasedStateMachine):
    limits: ResourceLimits = ResourceLimits(max_file_bytes=4, max_unique_bytes=8)
    store: VerifiedBlobStore

    def __init__(self) -> None:
        super().__init__()
        self.store = VerifiedBlobStore.empty(self.limits)
        self.expected: dict[ContentId, bytes] = {}
        self.snapshots: list[tuple[tuple[BlobRecord, ...], int]] = []

    @rule(content=st.binary(max_size=5))
    def intern_content(self, content: bytes) -> None:
        before = self.store
        self.snapshots.append((before.records, before.unique_bytes))
        content_id = ContentId.from_bytes(content)
        result = before.intern(content)

        if content_id in self.expected:
            assert isinstance(result, Ok)
            returned_id, returned_store = result.value
            assert returned_id == content_id
            assert returned_store == before
            assert content_id in self.expected
            return

        if len(content) > self.limits.max_file_bytes or (
            self.store.unique_bytes + len(content) > self.limits.max_unique_bytes
        ):
            assert isinstance(result, Err)
            assert self.store == before
            return

        assert isinstance(result, Ok)
        returned_id, returned_store = result.value
        assert returned_id == content_id
        assert returned_store is not before
        self.store = returned_store
        self.expected[content_id] = content

    @rule()
    def intern_empty_content(self) -> None:
        self.intern_content(b"")

    @invariant()
    def store_matches_model(self) -> None:
        assert self.store.blob_count == len(self.expected)
        assert self.store.unique_bytes == sum(
            len(content) for content in self.expected.values()
        )
        assert len({record.content_id for record in self.store.records}) == len(
            self.store.records
        )
        for record in self.store.records:
            assert record.content_id == ContentId.from_bytes(record.content)
            assert self.expected[record.content_id] == record.content
            assert self.store.get(record.content_id) == record.content

    @invariant()
    def prior_snapshots_remain_unchanged(self) -> None:
        for records, unique_bytes in self.snapshots:
            assert all(
                record.content_id == ContentId.from_bytes(record.content)
                for record in records
            )
            assert unique_bytes == sum(len(record.content) for record in records)


TestBlobStoreStateMachine: type = BlobStoreStateMachine.TestCase  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]


# --- AdoptionCrashStateMachine ------------------------------------------------


class AdoptionCrashStateMachine(RuleBasedStateMachine):
    """T6: interleaved install, crash, recover, and git-clean over one real
    adoption target driven through the real transaction machine.

    The model tracks one phase per example.  ``pristine`` trees match the
    captured pre-state exactly; ``installed`` trees match a reference install
    of the same bundle exactly; ``mutating`` and ``sealed`` crashes keep the
    journal on disk until ``recover`` resolves them.  The declared
    keep-existing path is byte-for-byte untouched in every phase.
    """

    _tmp: tempfile.TemporaryDirectory[str]
    target: Path
    bundle_path: Path
    pre_state: dict[str, tuple[bytes, int]]
    expected_installed: dict[str, tuple[bytes, int]]
    n_ops: int
    model_phase: str

    def __init__(self) -> None:
        super().__init__()
        from tests.adoption_e2e import (
            adoption_bundle,
            adoption_target,
            capture_tree,
            cli_exit_code,
            run_cli,
        )

        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.target = adoption_target(base / "targets")
        self.bundle_path = adoption_bundle(
            base / "bundle",
            base / "hook-runs",
            collisions={"README.md": "keep-existing"},
        )
        self.pre_state = capture_tree(self.target)
        # A reference install of the same bundle on an identical twin fixes
        # the expected installed closure without guessing the plan shape.
        reference = adoption_target(base / "reference")
        installed = run_cli(
            ["adopt", "--bundle", str(self.bundle_path), "--target", str(reference)]
        )
        assert cli_exit_code(installed) == 0
        self.expected_installed = capture_tree(reference)
        # Planning never mutates; it only fixes the operation count so crash
        # rules can target every apply index deterministically.
        receipt = base / "receipt.json"
        planned = run_cli(
            [
                "plan",
                "adopt",
                "--bundle",
                str(self.bundle_path),
                "--target",
                str(self.target),
                "--out",
                str(receipt),
            ]
        )
        assert cli_exit_code(planned) == 0
        import json

        document = cast(
            "dict[str, object]", json.loads(receipt.read_text(encoding="utf-8"))
        )
        self.n_ops = len(cast("list[object]", document["operations"]))
        self.model_phase = "pristine"

    def teardown(self) -> None:  # pyright: ignore[reportImplicitOverride]  hypothesis lifecycle hook
        self._tmp.cleanup()

    def _adopt_argv(self) -> list[str]:
        return [
            "adopt",
            "--bundle",
            str(self.bundle_path),
            "--target",
            str(self.target),
        ]

    @rule()
    def install(self) -> None:
        from tests.adoption_e2e import cli_exit_code, run_cli

        if self.model_phase != "pristine":
            return
        result = run_cli(self._adopt_argv())
        assert cli_exit_code(result) == 0
        self.model_phase = "installed"

    @rule(k=st.integers(min_value=1, max_value=64))
    def crash_install(self, k: int) -> None:
        from tests.adoption_e2e import (
            TransactionCrash,
            crashing_transaction,
            run_cli,
        )

        if self.model_phase != "pristine":
            return
        point = min(k, self.n_ops)
        with (
            crashing_transaction(apply_at=point) as fired,
            pytest.raises(TransactionCrash),
        ):
            _ = run_cli(self._adopt_argv())
        assert fired["apply"] is True
        self.model_phase = "mutating"

    @rule()
    def crash_sealed_cleanup(self) -> None:
        from tests.adoption_e2e import (
            TransactionCrash,
            crashing_transaction,
            run_cli,
        )

        if self.model_phase != "pristine":
            return
        with (
            crashing_transaction(seal_clean=True) as fired,
            pytest.raises(TransactionCrash),
        ):
            _ = run_cli(self._adopt_argv())
        assert fired["clean"] is True
        self.model_phase = "sealed"

    @rule()
    def recover(self) -> None:
        from tests.adoption_e2e import cli_exit_code, run_cli

        if self.model_phase not in ("mutating", "sealed"):
            return
        first = run_cli(["recover", "--target", str(self.target)])
        assert cli_exit_code(first) == 0
        # Recovery is idempotent: a second pass is a no-op success.
        second = run_cli(["recover", "--target", str(self.target)])
        assert cli_exit_code(second) == 0
        self.model_phase = "installed" if self.model_phase == "sealed" else "pristine"

    @rule()
    def git_clean(self) -> None:
        from tests.fixtures import run

        # git clean -fdx is only survivable before the candidate exists: the
        # tracked pre-state and the .git/rygor evidence survive, while the
        # untracked installed files of an installed/sealed tree would not.
        if self.model_phase not in ("pristine", "mutating"):
            return
        cleaned = run(["git", "clean", "-fdx"], cwd=self.target)
        assert cleaned.returncode == 0

    @invariant()
    def keep_existing_path_is_untouched(self) -> None:
        from tests.adoption_e2e import capture_tree

        tree = capture_tree(self.target)
        assert tree.get("README.md") == self.pre_state["README.md"]
        assert tree.get("notes.txt") == self.pre_state["notes.txt"]

    @invariant()
    def tree_matches_phase(self) -> None:
        from tests.adoption_e2e import capture_tree

        tree = capture_tree(self.target)
        journal = self.target / ".git/rygor/journal.json"
        match self.model_phase:
            case "pristine":
                assert tree == self.pre_state
                assert not journal.exists()
            case "installed":
                assert tree == self.expected_installed
                assert not journal.exists()
            case "mutating" | "sealed":
                assert journal.exists()
            case other:  # pragma: no cover  # the phase set is closed
                raise AssertionError(f"unknown phase: {other}")


TestAdoptionCrashStateMachine: type = (  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    AdoptionCrashStateMachine.TestCase
)
TestAdoptionCrashStateMachine.settings = settings(
    max_examples=6, stateful_step_count=10, deadline=None
)
