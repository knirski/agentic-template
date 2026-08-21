"""Pure generation-path recognition and maintenance-cleanup classification.

The shell supplies bounded observations; this module owns the only two-way
decoders.  For an absent manifest, ``recognize_generation`` maps an exact
scaffold onto its generation path and every other shape onto ``None``, which
the shell reports as ``UnsupportedManifestFree``.  ``decode_source_ownership``
decodes the fingerprinted source-ownership declaration, and
``classify_cleanup`` decodes the snapshot maintenance inventory and classifies
its agreement with the declared snapshot-cleanup set and the observed paths as
``CleanupContractValid``, ``CleanupContractMismatch``, or
``NoSnapshotCleanup``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scripts.bootstrap.canonical_json import StrictJsonValue, decode_json
from scripts.bootstrap.fragments import PROJECT_VALIDATION_WORKFLOW
from scripts.bootstrap.identity import directory_tree_hash
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import MANIFEST_PATH
from scripts.bootstrap.paths import RepoPath, parse_path, sorted_paths
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import (
    CleanupContract,
    CleanupContractMismatch,
    CleanupContractValid,
    CleanupObservation,
    NoSnapshotCleanup,
)
from scripts.bootstrap.vocabulary import SHA256

CLEANUP_SCHEMA_VERSION = 1
SOURCE_OWNERSHIP_SCHEMA_VERSION = 1

# The six declared seed-once slots and their installed paths, fixed by the
# design's declared-placeholder-marker table.  Generation-path recognition
# requires all five marker-bearing slots to satisfy their per-path shape rule;
# the project-validation workflow is a fixed adopter-owned scaffold.
SEED_ONCE_SLOTS: dict[str, RepoPath] = {
    "readme": RepoPath("README.md"),
    "prd": RepoPath("docs/prd.md"),
    "security_policy": RepoPath("SECURITY.md"),
    "contributing": RepoPath("CONTRIBUTING.md"),
    "validation_hook": RepoPath("scripts/validate-project"),
    "project_validation": RepoPath(".github/workflows/project-validation.yml"),
}
PROJECT_VALIDATION_PATH = SEED_ONCE_SLOTS["project_validation"]
PROJECT_VALIDATION_SCAFFOLD = PROJECT_VALIDATION_WORKFLOW
SEED_ONCE_PATHS: tuple[RepoPath, ...] = tuple(
    sorted((path for path in SEED_ONCE_SLOTS.values()), key=lambda p: p.value.encode())
)
COPIER_ANSWERS_PATH = RepoPath(".copier-answers.yml")
MAINTENANCE_INVENTORY_PATH = RepoPath(".agentic-template/maintenance-artifacts.json")
SOURCE_OWNERSHIP_PATH = RepoPath(".agentic-template/source-ownership.json")
_OWNERSHIP_ADMIN_ROOTS = (".git", ".agentic-template")
_OWNERSHIP_RESERVED_PATHS = (
    *SEED_ONCE_PATHS,
    RepoPath("LICENSE"),
    RepoPath("NOTICE.md"),
    RepoPath("LICENSES/Apache-2.0.txt"),
)

# The directory-tree hash tag used for maintenance-inventory directory entries.
_CLEANUP_TREE_KIND = b"cleanup/tree"


@dataclass(frozen=True, slots=True)
class CleanupEntryObservation:
    """One bounded observation of a declared maintenance-inventory path."""

    path: RepoPath
    present: bool
    kind: Literal["file", "directory"] | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupInventory:
    """The decoded ephemeral maintenance inventory; it never lists itself."""

    entries: tuple[tuple[RepoPath, Literal["file", "directory"], str], ...]


@dataclass(frozen=True, slots=True)
class SourceOwnership:
    """The decoded fingerprinted source-ownership declaration.

    ``lifecycle_paths`` is the declared source-owned set delivered to a
    generated project.  ``snapshot_cleanup_paths`` is the finite source-only
    set excluded by Copier and removed or explicitly retained by initial
    snapshot apply; it must equal the maintenance inventory's path set.
    """

    lifecycle_paths: tuple[RepoPath, ...]
    snapshot_cleanup_paths: tuple[RepoPath, ...]


def recognize_generation(
    *,
    copier_answers: bytes | None,
    seed_once: dict[RepoPath, bytes | None],
    scaffold: dict[RepoPath, bytes],
) -> GenerationPath | None:
    """Recognize an exact scaffold for an absent manifest; every other shape is ``None``.

    Copier requires ``.copier-answers.yml`` present and every seed-once path
    absent or byte-identical to the template's scaffold content.  GitHub
    requires no Copier answers and every seed-once path present and
    byte-identical to the scaffold.  A template package that does not yet ship
    a seed-once path can never recognize a scaffold for it.  Copier may omit
    the project-validation workflow because bootstrap carries its fixed
    scaffold bytes.
    """

    if set(seed_once) != set(SEED_ONCE_PATHS):
        raise ValueError(
            "seed-once observations require exactly the declared slot paths"
        )
    if any(path not in scaffold for path in SEED_ONCE_PATHS):
        return None
    if copier_answers is not None:
        if all(
            observed is None or observed == scaffold[path]
            for path, observed in seed_once.items()
        ):
            return GenerationPath.COPIER
        return None
    if all(
        observed is not None and observed == scaffold[path]
        for path, observed in seed_once.items()
    ):
        return GenerationPath.GITHUB
    return None


def _decode_document(
    data: bytes,
    *,
    document_path: RepoPath,
    schema_version: int,
    keys: frozenset[str],
) -> Result[dict[str, StrictJsonValue], CleanupContractMismatch]:
    """Decode one strict declaration document: exact keys, exact schema version."""

    try:
        value = decode_json(data)
    except ValueError, RecursionError:
        return Err(CleanupContractMismatch((document_path,)))
    if not isinstance(value, dict) or set(value) != set(keys):
        return Err(CleanupContractMismatch((document_path,)))
    if value.get("schema_version") != schema_version:
        return Err(CleanupContractMismatch((document_path,)))
    return Ok(value)


def decode_cleanup_inventory(
    data: bytes,
) -> Result[CleanupInventory, CleanupContractMismatch]:
    """Strictly decode the maintenance inventory into sorted, disjoint entries."""

    match _decode_document(
        data,
        document_path=MAINTENANCE_INVENTORY_PATH,
        schema_version=CLEANUP_SCHEMA_VERSION,
        keys=frozenset({"schema_version", "entries"}),
    ):
        case Err(mismatch):
            return Err(mismatch)
        case Ok(value):
            pass
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        return Err(CleanupContractMismatch((MAINTENANCE_INVENTORY_PATH,)))
    entries: list[tuple[RepoPath, Literal["file", "directory"], str]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "path",
            "kind",
            "sha256",
        }:
            return Err(CleanupContractMismatch((MAINTENANCE_INVENTORY_PATH,)))
        path_value = raw_entry.get("path")
        kind = raw_entry.get("kind")
        digest = raw_entry.get("sha256")
        if (
            not isinstance(path_value, str)
            or kind not in ("file", "directory")
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
        ):
            return Err(CleanupContractMismatch((MAINTENANCE_INVENTORY_PATH,)))
        match parse_path(path_value):
            case Err(_):
                return Err(CleanupContractMismatch((MAINTENANCE_INVENTORY_PATH,)))
            case Ok(path):
                pass
        if path.value in seen or path in (MANIFEST_PATH, MAINTENANCE_INVENTORY_PATH):
            return Err(CleanupContractMismatch((MAINTENANCE_INVENTORY_PATH,)))
        seen.add(path.value)
        entries.append((path, kind, digest))
    entries.sort(key=lambda item: item[0].value.encode("utf-8"))
    return Ok(CleanupInventory(tuple(entries)))


def decode_source_ownership(
    data: bytes,
) -> Result[SourceOwnership, CleanupContractMismatch]:
    """Strictly decode and validate the source-ownership declaration.

    Lifecycle and cleanup ownership are separate namespaces.  They may not
    overlap or contain one another, and path ownership is case-distinct even
    on case-sensitive filesystems so that the same declaration has one meaning
    on every supported target.
    """

    match _decode_document(
        data,
        document_path=SOURCE_OWNERSHIP_PATH,
        schema_version=SOURCE_OWNERSHIP_SCHEMA_VERSION,
        keys=frozenset({"schema_version", "lifecycle_paths", "snapshot_cleanup_paths"}),
    ):
        case Err(mismatch):
            return Err(mismatch)
        case Ok(value):
            pass

    def decode_paths(field: str) -> Result[tuple[RepoPath, ...], None]:
        raw_paths = value.get(field)
        if not isinstance(raw_paths, list):
            return Err(None)
        paths: list[RepoPath] = []
        seen: set[str] = set()
        seen_casefolded: set[str] = set()
        for raw_path in raw_paths:
            if not isinstance(raw_path, str):
                return Err(None)
            match parse_path(raw_path):
                case Err(_):
                    return Err(None)
                case Ok(path):
                    pass
            if (
                path in _OWNERSHIP_RESERVED_PATHS
                or path
                in (
                    MANIFEST_PATH,
                    MAINTENANCE_INVENTORY_PATH,
                    SOURCE_OWNERSHIP_PATH,
                )
                or any(
                    path.value == root or path.value.startswith(root + "/")
                    for root in _OWNERSHIP_ADMIN_ROOTS
                )
            ):
                return Err(None)
            if path.value in seen or path.value.casefold() in seen_casefolded:
                return Err(None)
            seen.add(path.value)
            seen_casefolded.add(path.value.casefold())
            paths.append(path)
        return Ok(tuple(sorted(paths, key=lambda path: path.value.encode("utf-8"))))

    match decode_paths("lifecycle_paths"):
        case Err(_):
            return Err(CleanupContractMismatch((SOURCE_OWNERSHIP_PATH,)))
        case Ok(lifecycle_paths):
            pass
    match decode_paths("snapshot_cleanup_paths"):
        case Err(_):
            return Err(CleanupContractMismatch((SOURCE_OWNERSHIP_PATH,)))
        case Ok(snapshot_cleanup_paths):
            pass

    for paths in (lifecycle_paths, snapshot_cleanup_paths):
        for index, path in enumerate(paths):
            normalized = path.value.casefold()
            if any(
                other.value.casefold().startswith(normalized + "/")
                or normalized.startswith(other.value.casefold() + "/")
                for other in paths[index + 1 :]
            ):
                return Err(CleanupContractMismatch((SOURCE_OWNERSHIP_PATH,)))
    for lifecycle_path in lifecycle_paths:
        lifecycle_value = lifecycle_path.value.casefold()
        for cleanup_path in snapshot_cleanup_paths:
            if (
                lifecycle_value == cleanup_path.value.casefold()
                or lifecycle_value.startswith(cleanup_path.value.casefold() + "/")
                or cleanup_path.value.casefold().startswith(lifecycle_value + "/")
            ):
                return Err(CleanupContractMismatch((SOURCE_OWNERSHIP_PATH,)))
    return Ok(SourceOwnership(lifecycle_paths, snapshot_cleanup_paths))


def cleanup_directory_digest(
    root: RepoPath,
    *,
    files: tuple[tuple[RepoPath, bytes, int], ...],
    directories: tuple[tuple[RepoPath, int], ...],
) -> str:
    """Derive an observed directory-tree digest for inventory comparison.

    The shell computes this hash for every observed directory that a
    maintenance-inventory entry declares.  Files and nested directories under
    the root participate; the ``cleanup/tree`` tag keeps this identity
    disjoint from plan-tree identities.
    """

    from scripts.bootstrap.identity import (
        DirectoryEntry,
        DirectoryState,
        FileEntry,
        PosixMode,
    )

    entries: list[FileEntry | DirectoryEntry] = [
        *(FileEntry(path, content, PosixMode(mode)) for path, content, mode in files),
        *(
            DirectoryEntry(path, PosixMode(mode))
            for path, mode in directories
            if path != root
        ),
    ]
    entries.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    return directory_tree_hash(
        _CLEANUP_TREE_KIND, DirectoryState(PosixMode.DIRECTORY, tuple(entries))
    )


def classify_cleanup(
    *,
    inventory: bytes | None,
    observed: dict[RepoPath, CleanupEntryObservation],
    declared_cleanup_paths: tuple[RepoPath, ...],
) -> CleanupObservation:
    """Classify the snapshot maintenance inventory against its declared set and observed paths.

    An absent inventory is ``NoSnapshotCleanup``.  A decoded inventory must
    equal the source ownership's declared snapshot-cleanup path set and match
    every declared path's presence, kind, and digest exactly; any mismatch
    names the differing paths and deletes nothing.  The contract's lifecycle
    side is empty: v1 cleanup targets are disjoint from generated-lifecycle
    source by construction.
    """

    if inventory is None:
        return NoSnapshotCleanup()
    match decode_cleanup_inventory(inventory):
        case Err(mismatch):
            return mismatch
        case Ok(decoded):
            pass
    declared = sorted_paths(declared_cleanup_paths)
    inventory_paths = sorted_paths(tuple(path for path, _, _ in decoded.entries))
    if declared != inventory_paths:
        differing = sorted_paths(set(declared) ^ set(inventory_paths))
        return CleanupContractMismatch(differing)
    mismatched: list[RepoPath] = []
    for path, kind, digest in decoded.entries:
        entry = observed.get(path)
        if (
            entry is None
            or not entry.present
            or entry.kind != kind
            or entry.sha256 != digest
        ):
            mismatched.append(path)
    if mismatched:
        return CleanupContractMismatch(
            tuple(sorted(mismatched, key=lambda p: p.value.encode("utf-8")))
        )
    contract = CleanupContract(
        lifecycle_paths=(),
        cleanup_paths=tuple(path for path, _, _ in decoded.entries),
        fingerprint=_cleanup_fingerprint(inventory),
    )
    return CleanupContractValid(contract)


def _cleanup_fingerprint(inventory: bytes) -> str:
    from scripts.bootstrap.identity import tagged_digest

    return tagged_digest(b"cleanup-inventory", inventory)
