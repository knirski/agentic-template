from __future__ import annotations

import unittest
from typing import cast

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


TestBlobStoreStateMachine = cast(
    type[unittest.TestCase], BlobStoreStateMachine.TestCase
)
