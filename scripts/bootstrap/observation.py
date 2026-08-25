"""Effect adapters for stable observations and target-protection facts.

The filesystem/Git shell supplies a complete pass.  This module only compares its
semantic records, which keeps retry policy deterministic and testable.  The
staged decoders below classify one ``ProjectObservationPass`` into the closed
``SystemState``: observation failures are never smuggled into a partially
populated facts record.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never, cast
from urllib.parse import urlsplit

from scripts.bootstrap.errors import (
    CommandError,
    ContractError,
    ContractErrorKind,
    InternalCode,
    ObservationError,
    ObservationErrorKind,
)
from scripts.bootstrap.errors import (
    InternalFailure as CoreInternalFailure,
)
from scripts.bootstrap.fs_effects import map_observation_error, walk_no_follow
from scripts.bootstrap.git_state import (
    ResolvedGitWorktree,
    resolve_git_worktree,
    run_git,
)
from scripts.bootstrap.identity import (
    PosixMode,
    TargetIdentity,
    content_identity,
    sha256_hex,
    tagged_digest,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.journal import (
    StateRootSnapshot,
    capture_state_root,
    classify_state_root,
)
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    CandidateManifest,
    ManagedInventoryEntry,
    decode_manifest,
)
from scripts.bootstrap.paths import RepoPath, parse_path, sorted_paths
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import (
    COPIER_ANSWERS_PATH,
    MAINTENANCE_INVENTORY_PATH,
    SCAFFOLD_SOURCE_PATHS,
    SEED_ONCE_PATHS,
    SOURCE_OWNERSHIP_PATH,
    CleanupEntryObservation,
    classify_cleanup,
    cleanup_directory_digest,
    decode_cleanup_inventory,
    decode_source_ownership,
    recognize_generation,
)
from scripts.bootstrap.source_baseline import (
    AdoptedSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
)
from scripts.bootstrap.state import (
    CanonicalTemplateSource,
    CleanupContract,
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
from scripts.bootstrap.state import UnsupportedGitTarget as GitUnsupportedTarget
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits

_CANONICAL_REMOTE = "github.com/knirski/rygor"
_SCP_REMOTE = re.compile(r"^(?:[^@]+@)?(?P<host>[^:/]+):(?P<path>.+)$")
_GENERATED_SOURCE_NAMES = frozenset(
    {
        ".coverage",
        ".direnv",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "result",
    }
)
# Repository-local integration aliases are deliberately outside the generated
# project contract.  They may contain symlinks, while all captured project
# paths remain regular, no-follow objects.
_NON_PROJECT_ROOTS = frozenset({".claude"})
_TRANSACTION_ARTIFACTS = frozenset(
    {
        ".rygor/lock",
        ".rygor/journal.json",
        ".rygor/journal.pending",
    }
)


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
        case GenerationPath.GITHUB | GenerationPath.ADOPTED:
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
    *,
    include_current_declarations: bool = True,
) -> SourceDelta:
    """Name changed baseline entries and, when requested, new source paths.

    File entries compare the raw digest of the observed bytes; directory entries
    compare presence and mode, because a directory's recorded tree digest cannot
    be re-derived from the bounded pass.  Copier source updates use the current
    ownership declaration to add newly observed descendants to the comparison
    set, so a source addition cannot hide outside the previous baseline.  Snapshot
    repair disables that extension: its recorded ownership entry is the only
    authority, preventing a changed declaration from reclassifying adopter files.
    A path reported by several entries is named once.
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

    ownership_file = files.get(SOURCE_OWNERSHIP_PATH)
    if include_current_declarations and ownership_file is not None:
        match decode_source_ownership(ownership_file.content):
            case Err(_):
                pass
            case Ok(ownership):
                baseline_paths = {entry.path for entry in entries}
                current_paths: set[RepoPath] = {SOURCE_OWNERSHIP_PATH}
                for path in (*files.keys(), *directories.keys()):
                    if path == SOURCE_OWNERSHIP_PATH or path in SEED_ONCE_PATHS:
                        continue
                    if any(
                        path == root or path.value.startswith(root.value + "/")
                        for root in ownership.lifecycle_paths
                    ):
                        current_paths.add(path)
                changed.update(current_paths - baseline_paths)
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
    delta = _source_delta(
        entries,
        files,
        directories,
        include_current_declarations=False,
    )
    if not delta.paths:
        return SnapshotSourceSame(managed)
    if not commit_reachable():
        return SnapshotSourceUnrecoverable(
            delta, "recorded snapshot commit is not reachable", managed
        )
    for path in delta.paths:
        entry = next((item for item in entries if item.path == path), None)
        if entry is None:
            # A newly declared path was absent from the recorded baseline.  A
            # missing object at the recorded commit is sufficient evidence that
            # targeted repair removes it; a present object indicates a baseline
            # that cannot be reconstructed from its own inventory.
            if path_bytes_at_commit(path) is not None:
                return SnapshotSourceUnrecoverable(
                    delta,
                    f"present at the recorded commit: {path.value}",
                    managed,
                )
            continue
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
    if not isinstance(  # pragma: no cover — classify routes only commit-binding generations; kept as a runtime guard
        baseline,
        GitHubSourceBaseline | AdoptedSourceBaseline,
    ):
        return SnapshotSourceUnrecoverable(  # pragma: no cover
            delta, "snapshot repair requires a commit-binding source baseline", managed
        )
    return SnapshotSourceChanged(
        delta, SnapshotRepair(baseline.snapshot_commit, delta.paths), managed
    )


@dataclass(frozen=True, slots=True)
class ResolvedShellTarget:
    """Resolution facts for one verified target."""

    environment: TargetEnvironment
    worktree: ResolvedGitWorktree | None = None
    remotes: tuple[str, ...] = ()


def _template_root() -> str:  # pyright: ignore[reportUnusedFunction] — shared template-root helper, imported by the cli shell
    return str(Path(__file__).resolve().parents[2])


def _remotes_for(worktree: ResolvedGitWorktree) -> tuple[str, ...]:
    match run_git(("remote", "--verbose"), cwd=worktree.root_abs):
        case Ok(result) if result.returncode == 0:
            pass
        case _:
            # A failed git command may carry partial output; never parse it.
            return ()
    urls: list[str] = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            urls.append(parts[1])
    return tuple(sorted(set(urls)))


def resolve_shell_target(
    target: str | None,
    *,
    cwd: str,
) -> Result[ResolvedShellTarget, ObservationError | CoreInternalFailure]:
    """Resolve the verified absolute worktree target and its protection."""

    root_abs = os.path.abspath(target if target is not None else cwd)
    match resolve_git_worktree(os.fsencode(root_abs)):
        case Err(error):
            return Err(error)
        case Ok(resolution):
            if isinstance(resolution, GitUnsupportedTarget):
                return Ok(
                    ResolvedShellTarget(
                        environment=UnsupportedGitTarget(resolution.reason)
                    )
                )
            worktree = resolution
    remotes = _remotes_for(worktree)
    protection = target_protection_for_remotes(remotes)
    from scripts.bootstrap.state import SupportedWorktree, WorktreeContext

    return Ok(
        ResolvedShellTarget(
            environment=SupportedWorktree(
                WorktreeContext(
                    target=worktree.target,
                    state_root=RepoPath("rygor"),
                    protection=protection,
                )
            ),
            worktree=worktree,
            remotes=remotes,
        )
    )


def _open_state_root(
    state_root_abs: bytes,
) -> Result[int | None, ObservationError | CoreInternalFailure]:
    root_fd = os.open(b"/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        components = tuple(part for part in state_root_abs.split(b"/") if part)
        match walk_no_follow(root_fd, components, allow_absent_final=True):
            case Err(error):
                return Err(error)
            case Ok(fd):
                if fd is None:
                    return Ok(None)
                try:
                    info = os.fstat(fd)
                except OSError as error:
                    os.close(fd)
                    return Err(map_observation_error(error, "state root"))
                if stat.S_IMODE(info.st_mode) != 0o700:
                    os.close(fd)
                    return Err(
                        ObservationError(
                            ObservationErrorKind.PERMISSION_DENIED,
                            f"state root permissions are {stat.S_IMODE(info.st_mode):04o}; 0700 is required",
                        )
                    )
                return Ok(fd)
    finally:
        os.close(root_fd)


def _empty_state_root_snapshot(target: TargetIdentity) -> StateRootSnapshot:
    return StateRootSnapshot(
        target=target,
        entries=(),
        journal=None,
        journal_irregular=False,
        pending=None,
        pending_irregular=False,
    )


def _capture_tree(
    root_abs: bytes,
    git_dir_abs: bytes,
    limits: ResourceLimits,
) -> Result[
    tuple[tuple[CapturedFile, ...], tuple[CapturedDirectory, ...]],
    ObservationError | CoreInternalFailure,
]:
    """Capture every non-administrative path: sorted, bounded, symlink-rejecting."""

    files: list[CapturedFile] = []
    directories: list[CapturedDirectory] = []
    total_bytes = 0
    git_dir = os.fsdecode(git_dir_abs)

    def visit(
        directory: str, relative: str
    ) -> Result[None, ObservationError | CoreInternalFailure]:
        nonlocal total_bytes
        try:
            with os.scandir(directory) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as error:
            return Err(map_observation_error(error, relative or "."))
        for name in names:
            child_abs = os.path.join(directory, name)
            child_rel = f"{relative}/{name}" if relative else name
            if not relative and name in _NON_PROJECT_ROOTS:
                continue
            if _is_transaction_artifact(child_rel):
                continue
            if child_abs == git_dir or child_abs.startswith(git_dir + os.sep):
                continue
            try:
                info = os.stat(child_abs, follow_symlinks=False)
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            if stat.S_ISLNK(info.st_mode):
                return Err(
                    ObservationError(
                        ObservationErrorKind.SYMLINK_ENCOUNTERED, child_rel
                    )
                )
            if stat.S_ISDIR(info.st_mode):
                if len(directories) + len(files) >= limits.max_paths:
                    return Err(
                        ObservationError(
                            ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "paths"
                        )
                    )
                match parse_path(child_rel):
                    case Err(_):
                        return Err(
                            ObservationError(
                                ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED,
                                child_rel,
                            )
                        )
                    case Ok(path):
                        pass
                directories.append(
                    CapturedDirectory(path, PosixMode(info.st_mode & 0o7777))
                )
                match visit(child_abs, child_rel):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
                continue
            if not stat.S_ISREG(info.st_mode):
                return Err(
                    ObservationError(
                        ObservationErrorKind.PATH_MISSING,
                        f"{child_rel} is not a regular file",
                    )
                )
            if info.st_nlink != 1:
                return Err(
                    ObservationError(
                        ObservationErrorKind.HARDLINK_ENCOUNTERED, child_rel
                    )
                )
            if len(directories) + len(files) >= limits.max_paths:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "paths"
                    )
                )
            if info.st_size > limits.max_file_bytes:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                    )
                )
            total_bytes += info.st_size
            if total_bytes > limits.max_unique_bytes:
                return Err(
                    ObservationError(
                        ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, "unique_bytes"
                    )
                )
            try:
                with open(child_abs, "rb") as handle:
                    content = handle.read()
            except OSError as error:
                return Err(map_observation_error(error, child_rel))
            match parse_path(child_rel):
                case Err(_):
                    return Err(
                        ObservationError(
                            ObservationErrorKind.OBSERVATION_LIMIT_EXCEEDED, child_rel
                        )
                    )
                case Ok(path):
                    pass
            files.append(CapturedFile(path, content, PosixMode(info.st_mode & 0o7777)))
        return Ok(None)

    match visit(os.fsdecode(root_abs), ""):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    files.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    directories.sort(key=lambda entry: entry.path.value.encode("utf-8"))
    return Ok((tuple(files), tuple(directories)))


def _is_transaction_artifact(relative: str) -> bool:
    """Keep transient transaction objects out of project snapshots."""

    if relative in _TRANSACTION_ARTIFACTS:
        return True
    components = tuple(relative.split("/"))
    return ".rygor-stage" in components or components[:2] == (
        ".rygor",
        "transactions",
    )


def capture_project_pass(
    resolved: ResolvedShellTarget,
    *,
    limits: ResourceLimits,
) -> Result[ProjectObservationPass, ObservationError | CoreInternalFailure]:
    """Capture one complete bounded observation pass for a supported worktree."""

    worktree = resolved.worktree
    if worktree is None:
        return Err(CoreInternalFailure(InternalCode.IMPOSSIBLE_STATE))
    match _open_state_root(worktree.state_root_abs):
        case Err(error):
            return Err(error)
        case Ok(fd):
            pass
    if fd is None:
        state_root = _empty_state_root_snapshot(worktree.target)
    else:
        try:
            match capture_state_root(fd, worktree.target, limits=limits):
                case Err(error):
                    return Err(error)
                case Ok(captured):
                    state_root = captured
        finally:
            os.close(fd)
    match _capture_tree(worktree.root_abs, worktree.git_dir_abs, limits):
        case Err(error):
            return Err(error)
        case Ok((files, directories)):
            pass
    return Ok(
        ProjectObservationPass(
            target=worktree.target,
            remotes=resolved.remotes,
            state_root=state_root,
            files=files,
            directories=directories,
        )
    )


def _collect_pass(
    resolved: ResolvedShellTarget,
    limits: ResourceLimits,
) -> Callable[[], StableRawProjectObservation]:
    def collect() -> StableRawProjectObservation:
        match capture_project_pass(resolved, limits=limits):
            case Err(error):
                raise _PassCaptureFailed(error)
            case Ok(pass_):
                return StableRawProjectObservation(pass_, b"")

    return collect


class _PassCaptureFailed(Exception):
    error: ObservationError | CoreInternalFailure

    def __init__(self, error: ObservationError | CoreInternalFailure) -> None:
        super().__init__(
            str(getattr(error, "kind", None) or getattr(error, "code", None) or "error")
        )
        self.error = error


@dataclass(frozen=True, slots=True)
class SystemObservation:
    """One closed system observation: environment, journal, project, and state."""

    environment: TargetEnvironment
    pass_: ProjectObservationPass | None
    system: SystemState


def _scaffold_bytes(template_root: str) -> dict[RepoPath, bytes]:
    """Load the template package's seed-once scaffold content, bounded."""

    scaffold: dict[RepoPath, bytes] = {}
    for path, source_path in SCAFFOLD_SOURCE_PATHS.items():
        absolute = os.path.join(template_root, source_path.value)
        try:
            with open(absolute, "rb") as handle:
                content = handle.read()
        except OSError:
            continue
        if len(content) <= DEFAULT_LIMITS.max_file_bytes:
            scaffold[path] = content
    return scaffold


def _cleanup_observation(
    files: Mapping[RepoPath, CapturedFile],
    directories: Mapping[RepoPath, CapturedDirectory],
) -> CleanupObservation:
    """Classify the snapshot maintenance inventory against observed paths.

    A Copier scaffold carries no inventory and is ``NoSnapshotCleanup``.  A
    GitHub scaffold's inventory is authorized only when the fingerprinted
    source-ownership declaration is present, decodes, and declares exactly the
    inventory's path set; every other shape names the differing paths and
    deletes nothing.
    """

    from scripts.bootstrap.state import CleanupContractMismatch, NoSnapshotCleanup

    inventory_file = files.get(MAINTENANCE_INVENTORY_PATH)
    if inventory_file is None:
        return NoSnapshotCleanup()
    ownership_file = files.get(SOURCE_OWNERSHIP_PATH)
    if ownership_file is None:
        return CleanupContractMismatch((SOURCE_OWNERSHIP_PATH,))
    match decode_source_ownership(ownership_file.content):
        case Err(mismatch):
            return mismatch
        case Ok(ownership):
            pass
    match decode_cleanup_inventory(inventory_file.content):
        case Err(mismatch):
            return mismatch
        case Ok(inventory):
            pass
    observed: dict[RepoPath, CleanupEntryObservation] = {}
    for path, kind, _digest in inventory.entries:
        if kind == "file":
            entry = files.get(path)
            observed[path] = CleanupEntryObservation(
                path=path,
                present=entry is not None,
                kind="file" if entry is not None else None,
                sha256=(sha256_hex(entry.content) if entry is not None else None),
            )
        else:
            if path not in directories:
                observed[path] = CleanupEntryObservation(path, False)
                continue
            prefix = path.value + "/"
            # Git checkouts mask modes with the umask, so digest canonical
            # modes: an unchanged snapshot must verify under any environment.
            # Files keep only the executable bit over the 0o644 base;
            # directories are always 0o755.
            child_files = tuple(
                (entry.path, entry.content, 0o644 | (entry.mode.value & 0o100))
                for entry in files.values()
                if entry.path.value.startswith(prefix)
            )
            child_dirs = tuple(
                (entry.path, 0o755)
                for entry in directories.values()
                if entry.path.value.startswith(prefix)
            )
            observed[path] = CleanupEntryObservation(
                path=path,
                present=True,
                kind="directory",
                sha256=cleanup_directory_digest(
                    path, files=child_files, directories=child_dirs
                ),
            )
    return classify_cleanup(
        inventory=inventory_file.content,
        observed=observed,
        declared_cleanup_paths=ownership.snapshot_cleanup_paths,
    )


def collect_template_source_entries(
    template_root: str,
    *,
    managed_paths: AbstractSet[RepoPath],
    limits: ResourceLimits,
) -> Result[tuple[LifecycleSourceEntry, ...], ContractError]:
    """Inventory only the source paths authorized by source ownership.

    Git is deliberately absent from this boundary: the declaration is the
    authority, so an adopter-owned tracked file cannot silently become part of
    the lifecycle baseline.  Every owned symlink and hardlink is rejected, and
    file reads are descriptor-bound so a source change cannot turn a checked
    regular file into a different object between stat and read.
    """

    ownership_abs = os.path.join(template_root, SOURCE_OWNERSHIP_PATH.value)
    try:
        ownership_info = os.lstat(ownership_abs)
    except OSError as error:
        return Err(
            ContractError(
                ContractErrorKind.SOURCE_CONTRACT_INVALID,
                f"{SOURCE_OWNERSHIP_PATH.value}: {error.strerror or error}",
            )
        )
    if not stat.S_ISREG(ownership_info.st_mode) or ownership_info.st_nlink != 1:
        return Err(
            ContractError(
                ContractErrorKind.SOURCE_CONTRACT_INVALID,
                SOURCE_OWNERSHIP_PATH.value,
            )
        )
    try:
        ownership_fd = os.open(
            ownership_abs, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(ownership_fd, "rb") as handle:
            ownership_bytes = handle.read(limits.max_file_bytes + 1)
    except OSError as error:
        return Err(
            ContractError(
                ContractErrorKind.SOURCE_CONTRACT_INVALID,
                f"{SOURCE_OWNERSHIP_PATH.value}: {error.strerror or error}",
            )
        )
    if len(ownership_bytes) > limits.max_file_bytes:
        return Err(
            ContractError(
                ContractErrorKind.SOURCE_CONTRACT_INVALID,
                SOURCE_OWNERSHIP_PATH.value,
            )
        )
    match decode_source_ownership(ownership_bytes):
        case Err(_):
            return Err(
                ContractError(
                    ContractErrorKind.SOURCE_CONTRACT_INVALID,
                    SOURCE_OWNERSHIP_PATH.value,
                )
            )
        case Ok(ownership):
            pass

    entries: list[LifecycleSourceEntry] = []
    seen: set[str] = set()
    total_bytes = 0
    reserved_paths = {path.value for path in (*SEED_ONCE_PATHS, *managed_paths)}

    def source_error(path: str) -> ContractError:
        return ContractError(ContractErrorKind.SOURCE_CONTRACT_INVALID, path)

    def add_entry(entry: LifecycleSourceEntry) -> Result[None, ContractError]:
        if entry.path.value in seen:
            return Err(source_error(entry.path.value))
        if len(entries) >= limits.max_paths:
            return Err(source_error("paths"))
        seen.add(entry.path.value)
        entries.append(entry)
        return Ok(None)

    def read_file(
        path: str, relative: str
    ) -> Result[tuple[os.stat_result, bytes], ContractError]:
        nonlocal total_bytes
        try:
            before = os.lstat(path)
        except OSError as error:
            return Err(source_error(f"{relative}: {error.strerror or error}"))
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            return Err(source_error(relative))
        if before.st_nlink != 1:
            return Err(source_error(relative))
        if before.st_size > limits.max_file_bytes:
            return Err(source_error(relative))
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as handle:
                after = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(after.st_mode)
                    or after.st_nlink != 1
                    or after.st_dev != before.st_dev
                    or after.st_ino != before.st_ino
                    or after.st_size > limits.max_file_bytes
                ):
                    return Err(source_error(relative))
                content = handle.read(limits.max_file_bytes + 1)
                after_read = os.fstat(handle.fileno())
        except OSError as error:
            return Err(source_error(f"{relative}: {error.strerror or error}"))
        if (
            len(content) > limits.max_file_bytes
            or not stat.S_ISREG(after_read.st_mode)
            or after_read.st_nlink != 1
            or after_read.st_dev != before.st_dev
            or after_read.st_ino != before.st_ino
            or after_read.st_size > limits.max_file_bytes
        ):
            return Err(source_error(relative))
        if total_bytes + len(content) > limits.max_unique_bytes:
            return Err(source_error("unique_bytes"))
        total_bytes += len(content)
        return Ok((after_read, content))

    def skip_generated(relative: str) -> bool:
        return any(
            part in _GENERATED_SOURCE_NAMES or part.endswith((".pyc", ".pyo"))
            for part in relative.split("/")
        )

    def skip_reserved(relative: str) -> bool:
        return any(
            relative == path or relative.startswith(path + "/")
            for path in reserved_paths
        )

    def visit(directory: str, relative: str) -> Result[None, ContractError]:
        if skip_generated(relative):
            return Ok(None)
        try:
            info = os.lstat(directory)
        except OSError as error:
            return Err(source_error(f"{relative}: {error.strerror or error}"))
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return Err(source_error(relative))
        if relative and not skip_reserved(relative):
            match parse_path(relative):
                case Err(_):
                    return Err(source_error(relative))
                case Ok(path):
                    pass
            match add_entry(
                LifecycleSourceEntry(
                    path=path,
                    kind="directory",
                    mode=PosixMode.DIRECTORY,
                    sha256=sha256_hex(b"template/source/dir:" + os.fsencode(relative)),
                )
            ):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass
        try:
            names = sorted(os.listdir(directory))
        except OSError as error:
            return Err(source_error(f"{relative}: {error.strerror or error}"))
        for name in names:
            child_relative = f"{relative}/{name}" if relative else name
            child_abs = os.path.join(directory, name)
            if child_relative == ".git" or child_relative == ".rygor":
                continue
            if skip_reserved(child_relative):
                continue
            if skip_generated(child_relative):
                continue
            try:
                child_info = os.lstat(child_abs)
            except OSError as error:
                return Err(source_error(f"{child_relative}: {error.strerror or error}"))
            if stat.S_ISLNK(child_info.st_mode):
                return Err(source_error(child_relative))
            if stat.S_ISDIR(child_info.st_mode):
                match visit(child_abs, child_relative):
                    case Err(error):
                        return Err(error)
                    case Ok(_):
                        pass
                continue
            match read_file(child_abs, child_relative):
                case Err(error):
                    return Err(error)
                case Ok((file_info, content)):
                    pass
            match parse_path(child_relative):
                case Err(_):
                    return Err(source_error(child_relative))
                case Ok(path):
                    pass
            match add_entry(
                LifecycleSourceEntry(
                    path=path,
                    kind="file",
                    mode=(
                        PosixMode.EXECUTABLE
                        if file_info.st_mode & 0o100
                        else PosixMode.FILE
                    ),
                    sha256=sha256_hex(content),
                )
            ):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass
        return Ok(None)

    for declared_path in ownership.lifecycle_paths:
        absolute = os.path.join(template_root, declared_path.value)
        if skip_reserved(declared_path.value):
            continue
        try:
            info = os.lstat(absolute)
        except OSError as error:
            return Err(
                source_error(f"{declared_path.value}: {error.strerror or error}")
            )
        if stat.S_ISLNK(info.st_mode):
            return Err(source_error(declared_path.value))
        if stat.S_ISDIR(info.st_mode):
            match visit(absolute, declared_path.value):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass
        else:
            match read_file(absolute, declared_path.value):
                case Err(error):
                    return Err(error)
                case Ok((file_info, content)):
                    pass
            match add_entry(
                LifecycleSourceEntry(
                    path=declared_path,
                    kind="file",
                    mode=(
                        PosixMode.EXECUTABLE
                        if file_info.st_mode & 0o100
                        else PosixMode.FILE
                    ),
                    sha256=sha256_hex(content),
                )
            ):
                case Err(error):
                    return Err(error)
                case Ok(_):
                    pass

    match read_file(ownership_abs, SOURCE_OWNERSHIP_PATH.value):
        case Err(error):
            return Err(error)
        case Ok((ownership_info, ownership_content)):
            pass
    match add_entry(
        LifecycleSourceEntry(
            path=SOURCE_OWNERSHIP_PATH,
            kind="file",
            mode=(
                PosixMode.EXECUTABLE
                if ownership_info.st_mode & 0o100
                else PosixMode.FILE
            ),
            sha256=sha256_hex(ownership_content),
        )
    ):
        case Err(error):
            return Err(error)
        case Ok(_):
            pass
    return Ok(
        tuple(sorted(entries, key=lambda entry: entry.path.value.encode("utf-8")))
    )


def _retained_cleanup_contract(  # pyright: ignore[reportUnusedFunction] — shared cleanup-contract helper, imported by the cli shell
    pass_: ProjectObservationPass,
) -> Result[CleanupContract, ContractError]:
    """Derive the retention contract for a cleanup inventory that no longer matches.

    ``--leave-maintenance-artifacts`` skips every cleanup deletion.  The
    retained set is the fingerprinted source-ownership declaration's
    snapshot-cleanup paths plus the inventory itself; a missing or corrupt
    declaration falls back to the decoded inventory's declared paths, while a
    valid declaration is honored verbatim (including an empty path set).
    """

    inventory = next(
        (entry for entry in pass_.files if entry.path == MAINTENANCE_INVENTORY_PATH),
        None,
    )
    if inventory is None:
        return Err(
            ContractError(
                ContractErrorKind.CLEANUP_CONTRACT_INVALID,
                "--leave-maintenance-artifacts requires a maintenance inventory",
            )
        )
    declared: tuple[RepoPath, ...] | None = None
    ownership = next(
        (entry for entry in pass_.files if entry.path == SOURCE_OWNERSHIP_PATH),
        None,
    )
    if ownership is not None:
        match decode_source_ownership(ownership.content):
            case Ok(decoded):
                declared = decoded.snapshot_cleanup_paths
            case Err(_):
                pass
    if declared is None:
        match decode_cleanup_inventory(inventory.content):
            case Err(_):
                declared = ()
            case Ok(decoded):
                declared = tuple(path for path, _kind, _digest in decoded.entries)
    retained = tuple(
        sorted(
            (*declared, MAINTENANCE_INVENTORY_PATH),
            key=lambda path: path.value.encode("utf-8"),
        )
    )
    return Ok(
        CleanupContract(
            lifecycle_paths=(),
            cleanup_paths=retained,
            fingerprint=tagged_digest(b"cleanup-inventory", inventory.content),
        )
    )


def _snapshot_evidence(
    worktree: ResolvedGitWorktree,
    *,
    snapshot_commit: str | None = None,
) -> tuple[Callable[[], bool], Callable[[RepoPath], bytes | None]]:
    """Lazy Git-backed snapshot-repair evidence providers."""

    commit_cache: str | None = snapshot_commit
    reachable_cache: bool | None = None

    def recorded_commit() -> str | None:
        nonlocal commit_cache
        if commit_cache is None:
            match run_git(("rev-parse", "HEAD"), cwd=worktree.root_abs):
                case Ok(result) if result.returncode == 0:
                    commit_cache = result.stdout.decode("ascii", "replace").strip()
                case _:
                    commit_cache = ""
        return commit_cache or None

    def reachable() -> bool:
        nonlocal reachable_cache
        if reachable_cache is None:
            commit = recorded_commit()
            if commit is None:
                reachable_cache = False
            else:
                match run_git(
                    ("rev-parse", "--verify", f"{commit}^{{commit}}"),
                    cwd=worktree.root_abs,
                ):
                    case Ok(result):
                        reachable_cache = result.returncode == 0
                    case Err(_):
                        reachable_cache = False
        return reachable_cache

    def path_bytes(path: RepoPath) -> bytes | None:
        commit = recorded_commit()
        if commit is None:
            return None
        match run_git(("show", f"{commit}:{path.value}"), cwd=worktree.root_abs):
            case Ok(result) if result.returncode == 0:
                if len(result.stdout) <= DEFAULT_LIMITS.max_file_bytes:
                    return result.stdout
            case _:
                pass
        return None

    return reachable, path_bytes


def observe_system(
    resolved: ResolvedShellTarget,
    *,
    coherent: bool,
    template_root: str,
    limits: ResourceLimits,
) -> Result[SystemObservation, CommandError]:
    """Capture one (or a coherent pair of) pass and assemble the closed state."""

    from scripts.bootstrap.state import SupportedWorktree

    environment = resolved.environment
    match environment:
        case UnsupportedGitTarget():
            return Ok(
                SystemObservation(
                    environment=environment,
                    pass_=None,
                    system=TargetUnavailable(environment),
                )
            )
        case SupportedWorktree():
            pass
    try:
        if coherent:
            match collect_coherent_observation(_collect_pass(resolved, limits)):
                case Err(error):
                    return Err(error)
                case Ok(observed):
                    pass_ = cast(ProjectObservationPass, observed.semantic_identity)
        else:
            match capture_project_pass(resolved, limits=limits):
                case Err(error):
                    return Err(error)
                case Ok(captured):
                    pass_ = captured
    except _PassCaptureFailed as failed:
        return Err(failed.error)
    journal = classify_state_root(pass_.state_root)
    files = {entry.path: entry for entry in pass_.files}
    directories = {entry.path: entry for entry in pass_.directories}
    project: ProjectObservation | None = None
    if isinstance(journal, NoJournal):
        worktree = resolved.worktree
        assert worktree is not None  # supported environments always carry one
        manifest_decoded = (
            decode_manifest(files[MANIFEST_PATH].content)
            if MANIFEST_PATH in files
            else None
        )
        if MANIFEST_PATH in files and SOURCE_OWNERSHIP_PATH in files:
            match manifest_decoded:
                case Err(_):
                    pass
                case Ok(_):
                    match decode_source_ownership(files[SOURCE_OWNERSHIP_PATH].content):
                        case Err(_):
                            return Err(
                                ContractError(
                                    ContractErrorKind.SOURCE_CONTRACT_INVALID,
                                    SOURCE_OWNERSHIP_PATH.value,
                                )
                            )
                        case Ok(_):
                            pass
                case None:
                    pass
        snapshot_commit: str | None = None
        if manifest_decoded is not None:
            match manifest_decoded:
                case Ok(manifest):
                    baseline = manifest.provenance.source_baseline
                    if isinstance(
                        baseline, GitHubSourceBaseline | AdoptedSourceBaseline
                    ):
                        snapshot_commit = baseline.snapshot_commit
                case Err(_):
                    pass
        reachable, path_bytes = _snapshot_evidence(
            worktree, snapshot_commit=snapshot_commit
        )
        project = classify_project_observation(
            copier_answers=(
                files[COPIER_ANSWERS_PATH].content
                if COPIER_ANSWERS_PATH in files
                else None
            ),
            manifest=(files[MANIFEST_PATH].content if MANIFEST_PATH in files else None),
            files=files,
            directories=directories,
            scaffold=_scaffold_bytes(template_root),
            cleanup=_cleanup_observation(files, directories),
            snapshot_commit_reachable=reachable,
            path_bytes_at_commit=path_bytes,
        )
    from scripts.bootstrap.state import SupportedWorktree as _SupportedWorktree

    state_root = (
        environment.context.state_root
        if isinstance(  # pyright: ignore[reportUnnecessaryIsInstance] — deliberate runtime contract check
            environment, _SupportedWorktree
        )
        else RepoPath("rygor")
    )
    system = build_system_state(
        environment=environment,
        journal=journal,
        project=project,
        state_root=state_root,
    )
    return Ok(SystemObservation(environment=environment, pass_=pass_, system=system))
