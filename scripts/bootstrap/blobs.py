"""Bounded immutable content-addressed byte storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from scripts.bootstrap.errors import InputError, InputErrorKind
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits


@dataclass(frozen=True, slots=True, order=True)
class ContentId:
    value: str

    @classmethod
    def from_bytes(cls, content: bytes) -> ContentId:
        return cls(hashlib.sha256(content).hexdigest())


@dataclass(frozen=True, slots=True)
class BlobRecord:
    content_id: ContentId
    content: bytes


@dataclass(frozen=True, slots=True)
class VerifiedBlobStore:
    """A persistent store: every write returns a new store and never mutates the old one."""

    limits: ResourceLimits
    records: tuple[BlobRecord, ...]
    unique_bytes: int
    _index: dict[str, bytes] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def empty(cls, limits: ResourceLimits = DEFAULT_LIMITS) -> VerifiedBlobStore:
        return cls(limits=limits, records=(), unique_bytes=0)

    @property
    def blob_count(self) -> int:
        return len(self.records)

    def get(self, content_id: ContentId) -> bytes | None:
        return self._index.get(content_id.value)

    def intern(
        self, content: bytes
    ) -> Result[tuple[ContentId, VerifiedBlobStore], InputError]:
        owned = bytes(content)
        if len(owned) > self.limits.max_file_bytes:
            return Err(InputError(InputErrorKind.INPUT_LIMIT_EXCEEDED, "file_bytes"))
        content_id = ContentId.from_bytes(owned)
        if content_id.value in self._index:
            return Ok((content_id, self))
        if self.unique_bytes + len(owned) > self.limits.max_unique_bytes:
            return Err(InputError(InputErrorKind.INPUT_LIMIT_EXCEEDED, "unique_bytes"))
        record = BlobRecord(content_id=content_id, content=owned)
        return Ok(
            (
                content_id,
                VerifiedBlobStore(
                    limits=self.limits,
                    records=(*self.records, record),
                    unique_bytes=self.unique_bytes + len(owned),
                    _index={**self._index, content_id.value: owned},
                ),
            )
        )
