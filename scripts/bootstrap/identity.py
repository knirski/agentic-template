"""Tagged content, file, directory, and bootstrap binding identities."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import ClassVar, Final, Literal, TypedDict

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.paths import RepoPath, normalize_text, path_byte_key


class PosixMode(int):
    """A validated ordinary POSIX mode, including file-type-independent bits."""

    FILE: ClassVar[PosixMode]
    EXECUTABLE: ClassVar[PosixMode]
    DIRECTORY: ClassVar[PosixMode]

    def __new__(cls, value: int) -> PosixMode:
        if isinstance(value, bool) or not 0 <= value <= 0o7777:
            raise ValueError("POSIX mode must be between 0 and 0o7777")
        return int.__new__(cls, value)

    @property
    def value(self) -> int:
        return int(self)


PosixMode.FILE = PosixMode(0o644)
PosixMode.EXECUTABLE = PosixMode(0o755)
PosixMode.DIRECTORY = PosixMode(0o755)

InstallFileMode: Final = frozenset({PosixMode.FILE, PosixMode.EXECUTABLE})
InstallDirectoryMode: Final = frozenset({PosixMode.DIRECTORY})


@dataclass(frozen=True, slots=True)
class FileContentIdentity:
    kind: Literal["text", "binary"]
    normalized_sha256: str
    raw_sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class FileState:
    identity: FileContentIdentity | None
    mode: PosixMode | None

    @property
    def present(self) -> bool:
        return self.identity is not None


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: RepoPath
    content: bytes
    mode: PosixMode


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    path: RepoPath
    mode: PosixMode


type TreeEntry = FileEntry | DirectoryEntry


class DirectoryTreePayload(TypedDict):
    kind: Literal["directory"]
    path: str
    mode: int


class FileTreePayload(TypedDict):
    kind: Literal["file"]
    path: str
    mode: int
    sha256: str


type TreePayload = DirectoryTreePayload | FileTreePayload


@dataclass(frozen=True, slots=True)
class DirectoryState:
    root_mode: PosixMode
    entries: tuple[TreeEntry, ...]


@dataclass(frozen=True, slots=True)
class TargetIdentity:
    root_os_bytes: bytes
    device: int
    inode: int
    digest: str


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    digest: str


@dataclass(frozen=True, slots=True)
class ManifestIdentity:
    payload: bytes
    digest: str


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tagged_digest(kind: bytes, payload: bytes) -> str:
    encoded = b"rygor/1/" + len(kind).to_bytes(8, "big") + kind + payload
    return sha256_hex(encoded)


def content_identity(data: bytes, *, text: bool) -> FileContentIdentity:
    normalized = normalize_text(data) if text else data
    return FileContentIdentity(
        kind="text" if text else "binary",
        normalized_sha256=sha256_hex(normalized),
        raw_sha256=sha256_hex(data),
        size=len(data),
    )


def file_state_identity(
    data: bytes | None,
    *,
    text: bool,
    mode: PosixMode | None = None,
) -> FileState:
    if data is None:
        if mode is not None:
            raise ValueError("an absent file cannot have a mode")
        return FileState(identity=None, mode=None)
    if mode is None:
        raise ValueError("a present file must have a mode")
    return FileState(identity=content_identity(data, text=text), mode=mode)


def old_file_parts(state: FileState) -> tuple[str, PosixMode] | None:
    """Return the raw digest and mode of a present file state, else ``None``."""

    if not state.present:
        return None
    identity = state.identity
    mode = state.mode
    if (
        identity is None or mode is None
    ):  # pragma: no cover — present states always carry both
        return None  # pragma: no cover — present states always carry both
    return identity.raw_sha256, mode


def file_state_document(state: FileState) -> dict[str, object] | None:
    """The canonical file-state document shared by hashes and plan receipts."""

    if not state.present or state.identity is None or state.mode is None:
        return None
    identity = state.identity
    return {
        "kind": identity.kind,
        "mode": state.mode.value,
        "normalized_sha256": identity.normalized_sha256,
        "raw_sha256": identity.raw_sha256,
        "size": identity.size,
    }


def file_state_hash(kind: bytes, state: FileState) -> str:
    if not state.present:
        return tagged_digest(kind + b"/absent", b"")
    document = file_state_document(state)
    if document is None:  # pragma: no cover - present files always carry an identity
        raise ValueError("a present file state must carry an identity")
    return tagged_digest(kind + b"/file", canonical_json(document))


def _entry_kind_name(entry: TreeEntry) -> str:
    match entry:
        case DirectoryEntry():
            return "directory"
        case FileEntry():
            return "file"


def _entry_payload(entry: TreeEntry) -> TreePayload:
    match entry:
        case DirectoryEntry():
            return {
                "kind": "directory",
                "path": entry.path.value,
                "mode": entry.mode.value,
            }
        case FileEntry():
            return {
                "kind": "file",
                "path": entry.path.value,
                "mode": entry.mode.value,
                "sha256": sha256_hex(entry.content),
            }


def directory_tree_hash(kind: bytes, state: DirectoryState | None) -> str:
    """Hash a directory's exact topology, entry kinds, bytes, and modes."""

    if state is None:
        return tagged_digest(kind + b"/absent", b"")
    sorted_entries = sorted(
        state.entries,
        key=lambda entry: (
            path_byte_key(entry.path),
            _entry_kind_name(entry),
        ),
    )
    seen_paths: set[str] = set()
    for entry in sorted_entries:
        if entry.path.value in seen_paths:
            raise ValueError(f"duplicate path in tree entries: {entry.path.value}")
        seen_paths.add(entry.path.value)
    encoded = b"\n".join(
        canonical_json(entry_payload)
        for entry_payload in [
            {"kind": "root", "mode": state.root_mode.value},
            *(_entry_payload(entry) for entry in sorted_entries),
        ]
    )
    return tagged_digest(kind + b"/directory", encoded)


def target_identity(root_os_bytes: bytes, *, device: int, inode: int) -> TargetIdentity:
    if not root_os_bytes:
        raise ValueError("target root identity cannot be empty")
    if device < 0 or inode < 0:
        raise ValueError("target device and inode must be non-negative")
    payload = (
        len(root_os_bytes).to_bytes(8, "big")
        + root_os_bytes
        + device.to_bytes(8, "big")
        + inode.to_bytes(8, "big")
    )
    return TargetIdentity(
        root_os_bytes=root_os_bytes,
        device=device,
        inode=inode,
        digest=tagged_digest(b"target-binding", payload),
    )


def source_identity(
    entries: tuple[tuple[RepoPath, bytes, PosixMode], ...],
) -> SourceIdentity:
    return SourceIdentity(digest=tree_hash(b"source", entries))


def manifest_identity(value: object) -> ManifestIdentity:
    payload = canonical_json(value)
    return ManifestIdentity(payload=payload, digest=tagged_digest(b"manifest", payload))


def tree_hash(
    kind: bytes,
    entries: tuple[tuple[RepoPath, bytes, PosixMode], ...],
) -> str:
    sorted_entries = sorted(entries, key=lambda item: path_byte_key(item[0]))
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
