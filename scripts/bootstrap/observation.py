"""Effect adapters for stable observations and target-protection facts.

The filesystem/Git shell supplies a complete pass.  This module only compares its
semantic records, which keeps retry policy deterministic and testable.  The
staged decoders below classify one ``ProjectObservationPass`` into the closed
``SystemState``: observation failures are never smuggled into a partially
populated facts record.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import assert_never
from urllib.parse import urlsplit

from scripts.bootstrap.errors import ObservationError, ObservationErrorKind
from scripts.bootstrap.identity import PosixMode, TargetIdentity, content_identity
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.journal import StateRootSnapshot
from scripts.bootstrap.manifest import (
    CandidateManifest,
    ManagedInventoryEntry,
    decode_manifest,
)
from scripts.bootstrap.paths import RepoPath, sorted_paths
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import (
    COPIER_ANSWERS_PATH,
    SEED_ONCE_PATHS,
    recognize_generation,
)
from scripts.bootstrap.source_baseline import (
    GitHubSourceBaseline,
    LifecycleSourceEntry,
)
from scripts.bootstrap.state import (
    CanonicalTemplateSource,
    CleanupObservation,
    ClosureError,
    CopierCondition,
    CopierConflicted,
    CopierExistingProject,
    CopierSourceChanged,
    CopierSourceSame,
    EmptyManifestFree,
    ExistingProject,
    ExistingProjectState,
    IncompatibleExistingProject,
    InvalidJournal,
    InvalidManifest,
    JournalAtDifferentTarget,
    JournalObservation,
    JournalPending,
    JournalTargetMismatch,
    ManagedDrift,
    ManagedObservation,
    ManagedVerified,
    NoJournal,
    OrdinaryProject,
    OrphanTransactionState,
    PathDelta,
    PopulatedManifestFree,
    ProjectAvailable,
    ProjectObservation,
    ProtectedTargetAvailable,
    RecognizedScaffold,
    RecordedProjectState,
    RecoveryEvidenceInvalid,
    SnapshotCondition,
    SnapshotExistingProject,
    SnapshotRepair,
    SnapshotSourceChanged,
    SnapshotSourceSame,
    SnapshotSourceUnrecoverable,
    SourceDelta,
    StaleJournalWrite,
    StalePendingWrite,
    StateRootInvalid,
    SupportedWorktree,
    SystemState,
    TargetEnvironment,
    TargetProtection,
    TargetSnapshot,
    TargetUnavailable,
    TopologyError,
    UnsafeExistingProject,
    UnsupportedGitTarget,
    UnsupportedManifestFree,
    ValidatedJournal,
    WorktreeContext,
)

_CANONICAL_REMOTE = "github.com/knirski/agentic-template"
_SCP_REMOTE = re.compile(r"^(?:[^@]+@)?(?P<host>[^:/]+):(?P<path>.+)$")


@dataclass(frozen=True, slots=True)
class StableRawProjectObservation:
    """The semantic identity and bounded bytes captured by one full pass."""

    semantic_identity: object
    payload: bytes


@dataclass(frozen=True, slots=True)
class CapturedFile:
    """One bounded observed regular file: exact bytes and POSIX mode."""

    path: RepoPath
    content: bytes
    mode: PosixMode


@dataclass(frozen=True, slots=True)
class CapturedDirectory:
    """One observed directory: exact POSIX mode."""

    path: RepoPath
    mode: PosixMode


@dataclass(frozen=True, slots=True)
class ProjectObservationPass:
    """One complete bounded capture of everything classification consumes."""

    target: TargetIdentity
    remotes: tuple[str, ...]
    state_root: StateRootSnapshot
    files: tuple[CapturedFile, ...]
    directories: tuple[CapturedDirectory, ...]

    def __post_init__(self) -> None:
        if sorted_paths(entry.path for entry in self.files) != tuple(
            entry.path for entry in self.files
        ):
            raise TypeError("captured files must be sorted by path")
        if sorted_paths(entry.path for entry in self.directories) != tuple(
            entry.path for entry in self.directories
        ):
            raise TypeError("captured directories must be sorted by path")


def collect_coherent_observation(
    collect_pass: Callable[[], StableRawProjectObservation],
    *,
    max_attempts: int = 3,
) -> Result[StableRawProjectObservation, ObservationError]:
    """Return two identical complete passes, retrying boundedly on concurrent change."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for _ in range(max_attempts):
        first = collect_pass()
        second = collect_pass()
        if first == second:
            return Ok(second)
    return Err(
        ObservationError(
            ObservationErrorKind.CONCURRENT_TARGET_CHANGE,
            "target changed during three observation attempts",
        )
    )


def _remote_parts(remote: str) -> tuple[str, str] | None:
    match = None if "://" in remote else _SCP_REMOTE.fullmatch(remote)
    if match is not None:
        return match.group("host"), match.group("path")
    parsed = urlsplit(remote)
    if parsed.scheme not in {"https", "ssh", "http"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in {None, 22, 80, 443}:
        return None
    return parsed.hostname, parsed.path


def normalize_remote(remote: str) -> str | None:
    """Normalize supported HTTPS/SSH/scp Git remotes to ``host/owner/repo``."""

    parts = _remote_parts(remote.strip())
    if parts is None:
        return None
    host, path = parts
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path or "/" not in path or "\x00" in path:
        return None
    return f"{host.lower()}/{path.lower()}"


def target_protection_for_remotes(remotes: Iterable[str]) -> TargetProtection:
    """Recognize the canonical template source without authenticating the repository."""

    for remote in remotes:
        if normalize_remote(remote) == _CANONICAL_REMOTE:
            return CanonicalTemplateSource(_CANONICAL_REMOTE)
    return OrdinaryProject()


def build_system_state(
    *,
    environment: TargetEnvironment,
    journal: JournalObservation,
    project: ProjectObservation | None,
    state_root: RepoPath,
) -> SystemState:
    """Assemble one closed ``SystemState`` from staged observation facts.

    ``project`` is required exactly when the journal observation is
    ``NoJournal``; any other pairing is an impossible state raised at runtime,
    because policy never receives a partially populated record.
    """

    match environment:
        case UnsupportedGitTarget():
            return TargetUnavailable(environment)
        case SupportedWorktree() as supported:
            pass
    context = WorktreeContext(
        target=supported.context.target,
        state_root=state_root,
        protection=supported.context.protection,
    )
    match journal:
        case NoJournal():
            if project is None:
                raise TypeError("a no-journal observation requires project facts")
            if isinstance(context.protection, CanonicalTemplateSource):
                return ProtectedTargetAvailable(context, project)
            return ProjectAvailable(context, project)
        case StaleJournalWrite(pending=pending):
            return StalePendingWrite(context, pending)
        case ValidatedJournal() as valid:
            return JournalPending(context, valid)
        case JournalTargetMismatch(journal=valid, target=target) as mismatch:
            del mismatch
            return JournalAtDifferentTarget(context, valid, target)
        case (
            InvalidJournal() | RecoveryEvidenceInvalid() | OrphanTransactionState()
        ) as evidence:
            return StateRootInvalid(context, evidence)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        journal
    )


def classify_project_observation(
    *,
    copier_answers: bytes | None,
    manifest: bytes | None,
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
    scaffold: Mapping[RepoPath, bytes],
    cleanup: CleanupObservation,
    snapshot_commit_reachable: Callable[[], bool],
    path_bytes_at_commit: Callable[[RepoPath], bytes | None],
) -> ProjectObservation:
    """Decode one captured pass into a closed ``ProjectObservation``.

    A present manifest decodes to ``InvalidManifest`` or an existing-project
    classification; an absent manifest runs the total two-way generation-path
    recognizer.  Every snapshot field names exactly the observed
    non-administrative paths in canonical order.
    """

    entries = _observed_entries(files, directories)
    if manifest is not None:
        match decode_manifest(manifest):
            case Err(error):
                return InvalidManifest(
                    error.kind.value + (f":{error.subject}" if error.subject else ""),
                    entries,
                )
            case Ok(decoded):
                pass
        return ExistingProject(
            classify_existing_project(
                manifest=decoded,
                copier_answers_present=copier_answers is not None,
                files=files,
                directories=directories,
                snapshot_commit_reachable=snapshot_commit_reachable,
                path_bytes_at_commit=path_bytes_at_commit,
            )
        )
    seed_once = {
        path: files[path].content if path in files else None for path in SEED_ONCE_PATHS
    }
    generation = recognize_generation(
        copier_answers=copier_answers,
        seed_once=seed_once,
        scaffold=dict(scaffold),
    )
    shape = EmptyManifestFree() if not entries else PopulatedManifestFree(entries)
    if generation is not None:
        return RecognizedScaffold(generation, cleanup, shape, entries)
    return UnsupportedManifestFree(shape, entries)


def classify_existing_project(
    *,
    manifest: CandidateManifest,
    copier_answers_present: bool,
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
    snapshot_commit_reachable: Callable[[], bool],
    path_bytes_at_commit: Callable[[RepoPath], bytes | None],
) -> ExistingProjectState:
    """Classify one recorded project: topology, closure, then generation path."""

    from scripts.bootstrap.resolver import resolve_recorded_selection

    recorded = RecordedProjectState(
        generation=manifest.provenance.generation_path,
        source_fingerprint=manifest.provenance.source_baseline.fingerprint,
    )
    snapshot = TargetSnapshot(_observed_entries(files, directories))
    unsafe_paths: set[RepoPath] = set()
    for entry in manifest.managed:
        if entry.path in directories:
            unsafe_paths.add(entry.path)
    for entry in manifest.provenance.source_baseline.entries:
        shape_mismatch = (entry.kind == "file" and entry.path in directories) or (
            entry.kind == "directory" and entry.path in files
        )
        if shape_mismatch:
            unsafe_paths.add(entry.path)
    if unsafe_paths:
        return UnsafeExistingProject(
            recorded,
            TopologyError(
                sorted_paths(unsafe_paths),
            ),
            snapshot,
        )
    settings: dict[str, Mapping[str, str | bool]] = {
        **dict(manifest.answers.settings),
        **dict(manifest.additions.settings),
    }
    match resolve_recorded_selection(
        profile_id=manifest.answers.profile.id,
        requested=manifest.answers.profile.requested,
        additions=manifest.additions.requested,
        settings=settings,
    ):
        case Err(failure):
            return IncompatibleExistingProject(
                recorded,
                ClosureError(
                    failure.kind.value
                    + (f":{failure.subject}" if failure.subject else "")
                ),
                snapshot,
            )
        case Ok(_):
            pass
    managed = _managed_observation(manifest.managed, files)
    match manifest.provenance.generation_path:
        case GenerationPath.GITHUB:
            snapshot_condition = _snapshot_condition(
                manifest=manifest,
                managed=managed,
                files=files,
                directories=directories,
                commit_reachable=snapshot_commit_reachable,
                path_bytes_at_commit=path_bytes_at_commit,
            )
            return SnapshotExistingProject(recorded, snapshot_condition, snapshot)
        case GenerationPath.COPIER:
            if not copier_answers_present:
                condition: CopierCondition = CopierConflicted(
                    PathDelta((COPIER_ANSWERS_PATH,))
                )
            else:
                delta = _source_delta(
                    manifest.provenance.source_baseline.entries,
                    files,
                    directories,
                )
                condition = (
                    CopierSourceSame(managed)
                    if not delta.paths
                    else CopierSourceChanged(delta, managed)
                )
            return CopierExistingProject(recorded, condition, snapshot)
    return assert_never(  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        manifest.provenance.generation_path
    )


def _observed_entries(
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
) -> tuple[RepoPath, ...]:
    return tuple(
        sorted_paths((*files.keys(), *directories.keys())),
    )


def _managed_observation(
    managed: tuple[ManagedInventoryEntry, ...],
    files: Mapping[RepoPath, CapturedFile],
) -> ManagedObservation:
    drifted: list[RepoPath] = []
    for entry in managed:
        observed = files.get(entry.path)
        if observed is None:
            drifted.append(entry.path)
            continue
        identity = content_identity(observed.content, text=entry.kind == "text")
        if (
            entry.kind != identity.kind
            or entry.mode != observed.mode
            or entry.sha256 != identity.normalized_sha256
        ):
            drifted.append(entry.path)
    if drifted:
        return ManagedDrift(
            PathDelta(
                sorted_paths(drifted),
            )
        )
    return ManagedVerified()


def _source_delta(
    entries: tuple[LifecycleSourceEntry, ...],
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
) -> SourceDelta:
    """Name baseline entries whose observed presence, mode, or digest differs.

    File entries compare the raw digest of the observed bytes; directory entries
    compare presence and mode, because a directory's recorded tree digest cannot
    be re-derived from the bounded pass.  A path reported by several entries is
    named once.
    """

    changed: set[RepoPath] = set()
    for entry in entries:
        if entry.kind == "file":
            observed = files.get(entry.path)
            if (
                observed is None
                or content_identity(observed.content, text=False).raw_sha256
                != entry.sha256
            ):
                changed.add(entry.path)
        elif entry.kind == "directory":
            observed = directories.get(entry.path)
            if observed is None or observed.mode != entry.mode:
                changed.add(entry.path)
    return SourceDelta(sorted_paths(changed))


def _snapshot_condition(
    *,
    manifest: CandidateManifest,
    managed: ManagedObservation,
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
    commit_reachable: Callable[[], bool],
    path_bytes_at_commit: Callable[[RepoPath], bytes | None],
) -> SnapshotCondition:
    entries = manifest.provenance.source_baseline.entries
    delta = _source_delta(entries, files, directories)
    if not delta.paths:
        return SnapshotSourceSame(managed)
    if not commit_reachable():
        return SnapshotSourceUnrecoverable(
            delta, "recorded snapshot commit is not reachable", managed
        )
    for path in delta.paths:
        entry = next(item for item in entries if item.path == path)
        if entry.kind != "file":
            return SnapshotSourceUnrecoverable(
                delta,
                f"directory source repair is unavailable: {path.value}",
                managed,
            )
        at_commit = path_bytes_at_commit(path)
        if (
            at_commit is None
            or content_identity(at_commit, text=False).raw_sha256 != entry.sha256
        ):
            return SnapshotSourceUnrecoverable(
                delta, f"recorded content differs at commit: {path.value}", managed
            )
    baseline = manifest.provenance.source_baseline
    if not isinstance(baseline, GitHubSourceBaseline):  # pragma: no cover
        return SnapshotSourceUnrecoverable(  # pragma: no cover
            delta, "snapshot repair requires a GitHub source baseline", managed
        )
    return SnapshotSourceChanged(
        delta, SnapshotRepair(baseline.snapshot_commit, delta.paths), managed
    )
