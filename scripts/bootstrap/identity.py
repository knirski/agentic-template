"""Tagged content, tree, and mode identities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.paths import RepoPath, normalize_text


class PosixMode(StrEnum):
    FILE = "100644"
    EXECUTABLE = "100755"


@dataclass(frozen=True, slots=True)
class FileContentIdentity:
    kind: str
    normalized_sha256: str
    raw_sha256: str
    size: int


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tagged_digest(kind: bytes, payload: bytes) -> str:
    return sha256_hex(b"agentic-template/1/" + kind + b"\n" + payload)


def content_identity(data: bytes, *, text: bool) -> FileContentIdentity:
    normalized = normalize_text(data) if text else data
    return FileContentIdentity(
        kind="text" if text else "binary",
        normalized_sha256=sha256_hex(normalized),
        raw_sha256=sha256_hex(data),
        size=len(data),
    )


def tree_hash(
    kind: bytes,
    entries: tuple[tuple[RepoPath, bytes, PosixMode], ...],
) -> str:
    sorted_entries = sorted(entries, key=lambda item: item[0].value.encode("utf-8"))
    seen_paths: set[str] = set()
    for path, _, _ in sorted_entries:
        if path.value in seen_paths:
            raise ValueError(f"duplicate path in tree entries: {path.value}")
        seen_paths.add(path.value)
    encoded = b"\n".join(
        canonical_json(
            {"path": path.value, "mode": mode.value, "sha256": sha256_hex(content)}
        )
        for path, content, mode in sorted_entries
    )
    return tagged_digest(kind, encoded)
