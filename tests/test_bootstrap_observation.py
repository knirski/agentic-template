"""Existing-project classification and system-state assembly for the observation pipeline.

Covers T12 observation classification: ``build_system_state`` closed-state assembly,
``classify_existing_project`` topology/closure/generation classification, and the
pass-shape contract of ``ProjectObservationPass``.  Also pins the shell-side cleanup
classification and git-evidence contracts directly (they are only exercised
through the CLI happy path otherwise).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.bootstrap.errors import ContractErrorKind
from scripts.bootstrap.git_state import ResolvedGitWorktree
from scripts.bootstrap.identity import (
    PosixMode,
    content_identity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.journal import StateRootSnapshot
from scripts.bootstrap.manifest import (
    CandidateManifest,
    LicensingRecord,
    MaintenanceRecord,
    ManagedInventoryEntry,
    ManifestAdditions,
    ManifestAnswers,
    ManifestErrorKind,
    ProfileSelection,
    ProjectFacts,
    ProvenanceRecord,
    SlotContent,
    build_candidate_manifest,
)
from scripts.bootstrap.observation import (
    CapturedDirectory,
    CapturedFile,
    ProjectObservationPass,
    _capture_tree,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _cleanup_observation,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _retained_cleanup_contract,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _snapshot_evidence,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    build_system_state,
    classify_existing_project,
    collect_template_source_entries,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.scaffold import (
    MAINTENANCE_INVENTORY_PATH,
    SEED_ONCE_PATHS,
    SOURCE_OWNERSHIP_PATH,
)
from scripts.bootstrap.source_baseline import (
    AdoptedSourceBaseline,
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
    template_source_fingerprint,
)
from scripts.bootstrap.state import (
    CleanupContractMismatch,
    CleanupContractValid,
    CopierConflicted,
    CopierExistingProject,
    CopierSourceChanged,
    CopierSourceSame,
    ExistingProjectState,
    IncompatibleExistingProject,
    ManagedDrift,
    ManagedVerified,
    NoJournal,
    OrdinaryProject,
    SnapshotExistingProject,
    SnapshotSourceChanged,
    SnapshotSourceSame,
    SnapshotSourceUnrecoverable,
    SupportedWorktree,
    TargetReason,
    TargetUnavailable,
    TopologyError,
    UnsafeExistingProject,
    UnsupportedGitTarget,
    WorktreeContext,
)
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits
from tests.factory import seed_repo
from tests.fixtures import assert_err, assert_ok

TARGET = target_identity(b"/work/example", device=1, inode=2)


def _answers(
    *,
    requested: tuple[str, ...] = (),
    settings: dict[str, dict[str, str | bool]] | None = None,
) -> ManifestAnswers:
    return ManifestAnswers(
        project=ProjectFacts(name="example", default_branch="main"),
        profile=ProfileSelection(id="portable", requested=requested),
        settings=settings if settings is not None else {},
        licensing=LicensingRecord(mode="retain-apache-2.0", content_sha256=None),
        slots={
            slot_id: SlotContent(mode="scaffold", content_sha256=None)
            for slot_id in (
                "readme",
                "prd",
                "security_policy",
                "contributing",
                "validation_hook",
            )
        },
    )


def _source_entries() -> tuple[LifecycleSourceEntry, ...]:
    return (
        LifecycleSourceEntry(
            path=RepoPath("src/lib.py"),
            kind="file",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"present\n"),
        ),
        LifecycleSourceEntry(
            path=RepoPath("src/tools"),
            kind="directory",
            mode=PosixMode.DIRECTORY,
            sha256=sha256_hex(b"tree"),
        ),
    )


def _github_baseline(
    *, entries: tuple[LifecycleSourceEntry, ...] | None = None
) -> GitHubSourceBaseline:
    selected_entries = tuple(
        sorted(
            entries if entries is not None else _source_entries(),
            key=lambda entry: entry.path.value.encode("utf-8"),
        )
    )
    return GitHubSourceBaseline(
        kind="github",
        fingerprint=template_source_fingerprint(selected_entries),
        entries=selected_entries,
        snapshot_commit="0" * 40,
    )


def _copier_baseline() -> CopierSourceBaseline:
    entries = _source_entries()
    return CopierSourceBaseline(
        kind="copier",
        fingerprint=template_source_fingerprint(entries),
        entries=entries,
    )


def _adopted_baseline(
    *, entries: tuple[LifecycleSourceEntry, ...] | None = None
) -> AdoptedSourceBaseline:
    selected_entries = tuple(
        sorted(
            entries if entries is not None else _source_entries(),
            key=lambda entry: entry.path.value.encode("utf-8"),
        )
    )
    return AdoptedSourceBaseline(
        kind="adopted",
        fingerprint=template_source_fingerprint(selected_entries),
        entries=selected_entries,
        snapshot_commit="0" * 40,
    )


def _manifest(
    *,
    copier: bool = False,
    adopted: bool = False,
    baseline: (
        GitHubSourceBaseline | CopierSourceBaseline | AdoptedSourceBaseline | None
    ) = None,
    managed: tuple[ManagedInventoryEntry, ...] = (),
    answers: ManifestAnswers | None = None,
    additions: ManifestAdditions | None = None,
) -> CandidateManifest:
    generation = (
        GenerationPath.ADOPTED
        if adopted
        else (GenerationPath.COPIER if copier else GenerationPath.GITHUB)
    )
    provenance = ProvenanceRecord(
        generation_path=generation,
        maintenance=MaintenanceRecord(status="clean"),
        source_baseline=(
            baseline
            if baseline is not None
            else (
                _adopted_baseline()
                if adopted
                else (_copier_baseline() if copier else _github_baseline())
            )
        ),
    )
    return assert_ok(
        build_candidate_manifest(
            answers=answers if answers is not None else _answers(),
            additions=additions if additions is not None else ManifestAdditions(),
            provenance=provenance,
            managed=managed,
        ),
        "manifest build",
    )


def _observed_files() -> dict[RepoPath, CapturedFile]:
    """Observed files matching every file entry of ``_source_entries`` exactly."""
    return {
        RepoPath("src/lib.py"): CapturedFile(
            RepoPath("src/lib.py"), b"present\n", PosixMode.FILE
        ),
    }


def _observed_directories() -> dict[RepoPath, CapturedDirectory]:
    """Observed directories matching every directory entry of ``_source_entries``."""
    return {
        RepoPath("src/tools"): CapturedDirectory(
            RepoPath("src/tools"), PosixMode.DIRECTORY
        ),
    }


def _classify(
    manifest: CandidateManifest,
    *,
    copier_answers_present: bool = False,
    files: dict[RepoPath, CapturedFile] | None = None,
    directories: dict[RepoPath, CapturedDirectory] | None = None,
    commit_reachable: bool = True,
    at_commit: bytes | None = None,
) -> ExistingProjectState:
    return classify_existing_project(
        manifest=manifest,
        copier_answers_present=copier_answers_present,
        files=files if files is not None else {},
        directories=directories if directories is not None else {},
        snapshot_commit_reachable=lambda: commit_reachable,
        path_bytes_at_commit=lambda _path: at_commit,
    )


class TestProjectClassification:
    def test_github_matching_observation_classifies_source_same(self) -> None:
        result = _classify(
            _manifest(),
            files=_observed_files(),
            directories=_observed_directories(),
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceSame)
        assert isinstance(result.condition.managed, ManagedVerified)

    def test_adopted_matching_observation_classifies_source_same(self) -> None:
        result = _classify(
            _manifest(adopted=True),
            files=_observed_files(),
            directories=_observed_directories(),
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceSame)
        assert isinstance(result.condition.managed, ManagedVerified)

    def test_adopted_manifest_rejects_mismatched_baseline_kind(self) -> None:
        error = assert_err(
            build_candidate_manifest(
                answers=_answers(),
                additions=ManifestAdditions(),
                provenance=ProvenanceRecord(
                    generation_path=GenerationPath.ADOPTED,
                    maintenance=MaintenanceRecord(status="clean"),
                    source_baseline=_github_baseline(),
                ),
                managed=(),
            ),
            "expected a baseline/generation mismatch failure",
        )
        assert error.kind == ManifestErrorKind.SCHEMA_VIOLATION
        assert error.subject == "source_baseline"

    def test_unreachable_snapshot_commit_is_unrecoverable(self) -> None:
        result = _classify(_manifest(), files={}, commit_reachable=False)
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)

    def test_directory_source_repair_is_unavailable(self) -> None:
        # The manifest builder rejects duplicate baseline paths, so this
        # defensive branch is exercised with a directly-constructed manifest.
        baseline = GitHubSourceBaseline(
            kind="github",
            fingerprint=sha256_hex(b"source"),
            entries=(
                LifecycleSourceEntry(
                    path=RepoPath("docs/agents/domain.md"),
                    kind="directory",
                    mode=PosixMode.DIRECTORY,
                    sha256=sha256_hex(b"tree"),
                ),
                LifecycleSourceEntry(
                    path=RepoPath("docs/agents/domain.md"),
                    kind="file",
                    mode=PosixMode.FILE,
                    sha256=sha256_hex(b"present\n"),
                ),
            ),
            snapshot_commit="0" * 40,
        )
        manifest = CandidateManifest(
            schema_version=1,
            answers=_answers(),
            additions=ManifestAdditions(),
            provenance=ProvenanceRecord(
                generation_path=GenerationPath.GITHUB,
                maintenance=MaintenanceRecord(status="clean"),
                source_baseline=baseline,
            ),
            managed=(),
        )
        result = _classify(manifest, files={})
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert "directory source repair is unavailable" in result.condition.reason

    def test_content_differing_at_commit_is_unrecoverable(self) -> None:
        result = _classify(_manifest(), files={}, at_commit=b"wrong bytes")
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert "differs at commit" in result.condition.reason

    def test_changed_file_repairs_from_the_recorded_commit(self) -> None:
        result = _classify(
            _manifest(),
            files={},
            directories=_observed_directories(),
            at_commit=b"present\n",
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert result.condition.repair.commit == "0" * 40
        assert result.condition.repair.paths == (RepoPath("src/lib.py"),)

    def test_adopted_changed_file_repairs_from_the_recorded_commit(self) -> None:
        result = _classify(
            _manifest(adopted=True),
            files={},
            directories=_observed_directories(),
            at_commit=b"present\n",
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert result.condition.repair.commit == "0" * 40
        assert result.condition.repair.paths == (RepoPath("src/lib.py"),)

    def test_new_declared_source_file_is_source_drift(self) -> None:
        ownership = CapturedFile(
            SOURCE_OWNERSHIP_PATH,
            _ownership_bytes((), lifecycle_paths=(RepoPath("src"),)),
            PosixMode.FILE,
        )
        files = {
            **_observed_files(),
            ownership.path: ownership,
            RepoPath("src/new.py"): CapturedFile(
                RepoPath("src/new.py"), b"new\n", PosixMode.FILE
            ),
        }
        result = _classify(
            _manifest(copier=True),
            copier_answers_present=True,
            files=files,
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceChanged)
        assert isinstance(result.condition, CopierSourceChanged)
        assert RepoPath("src/new.py") in result.condition.delta.paths

    def test_snapshot_does_not_reclassify_new_adopter_file_from_changed_ownership(
        self,
    ) -> None:
        original_ownership = _ownership_bytes((), lifecycle_paths=(RepoPath("src"),))
        changed_ownership = _ownership_bytes(
            (), lifecycle_paths=(RepoPath("src"), RepoPath("adopter"))
        )
        baseline = _github_baseline(
            entries=(
                *_source_entries(),
                LifecycleSourceEntry(
                    path=SOURCE_OWNERSHIP_PATH,
                    kind="file",
                    mode=PosixMode.FILE,
                    sha256=sha256_hex(original_ownership),
                ),
            )
        )
        ownership = CapturedFile(
            SOURCE_OWNERSHIP_PATH, changed_ownership, PosixMode.FILE
        )
        files = {
            **_observed_files(),
            ownership.path: ownership,
            RepoPath("adopter/settings.toml"): CapturedFile(
                RepoPath("adopter/settings.toml"), b"adopter\n", PosixMode.FILE
            ),
        }
        result = _classify(
            _manifest(baseline=baseline),
            files=files,
            directories=_observed_directories(),
            at_commit=original_ownership,
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert isinstance(result.condition, SnapshotSourceChanged)
        assert result.condition.delta.paths == (SOURCE_OWNERSHIP_PATH,)
        assert result.condition.repair.paths == (SOURCE_OWNERSHIP_PATH,)

    def test_absent_directory_is_source_drift(self) -> None:
        result = _classify(_manifest(), files=_observed_files(), directories={})
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert "directory source repair is unavailable" in result.condition.reason

    def test_changed_directory_mode_is_source_drift(self) -> None:
        result = _classify(
            _manifest(),
            files=_observed_files(),
            directories={
                RepoPath("src/tools"): CapturedDirectory(
                    RepoPath("src/tools"), PosixMode(0o700)
                )
            },
        )
        assert isinstance(result, SnapshotExistingProject)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert isinstance(result.condition, SnapshotSourceUnrecoverable)
        assert "directory source repair is unavailable" in result.condition.reason

    def test_missing_copier_answers_is_conflicted(self) -> None:
        result = _classify(_manifest(copier=True), copier_answers_present=False)
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierConflicted)

    def test_copier_matching_observation_is_source_same(self) -> None:
        result = _classify(
            _manifest(copier=True),
            copier_answers_present=True,
            files=_observed_files(),
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceSame)

    def test_copier_source_change_is_reported(self) -> None:
        result = _classify(
            _manifest(copier=True),
            copier_answers_present=True,
            files={},
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceChanged)
        assert isinstance(result.condition, CopierSourceChanged)
        assert result.condition.delta.paths == (RepoPath("src/lib.py"),)

    def test_missing_managed_file_is_drift(self) -> None:
        managed = (
            ManagedInventoryEntry(
                path=RepoPath("docs/api.md"),
                kind="text",
                mode=PosixMode.FILE,
                sha256=sha256_hex(b"x"),
            ),
        )
        result = _classify(
            _manifest(copier=True, managed=managed),
            copier_answers_present=True,
            files=_observed_files(),
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition.managed, ManagedDrift)
        assert isinstance(result.condition.managed, ManagedDrift)
        assert result.condition.managed.delta.paths == (RepoPath("docs/api.md"),)

    def test_changed_managed_mode_is_drift(self) -> None:
        managed = (
            ManagedInventoryEntry(
                path=RepoPath("docs/api.md"),
                kind="text",
                mode=PosixMode.EXECUTABLE,
                sha256=sha256_hex(b"x"),
            ),
        )
        files = _observed_files()
        files[RepoPath("docs/api.md")] = CapturedFile(
            RepoPath("docs/api.md"), b"x", PosixMode.FILE
        )
        result = _classify(
            _manifest(copier=True, managed=managed),
            copier_answers_present=True,
            files=files,
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition.managed, ManagedDrift)

    def test_matching_managed_inventory_is_verified(self) -> None:
        managed = (
            ManagedInventoryEntry(
                path=RepoPath("docs/api.md"),
                kind="text",
                mode=PosixMode.FILE,
                sha256=content_identity(b"x", text=True).normalized_sha256,
            ),
        )
        files = _observed_files()
        files[RepoPath("docs/api.md")] = CapturedFile(
            RepoPath("docs/api.md"), b"x", PosixMode.FILE
        )
        result = _classify(
            _manifest(copier=True, managed=managed),
            copier_answers_present=True,
            files=files,
            directories=_observed_directories(),
        )
        assert isinstance(result, CopierExistingProject)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition, CopierSourceSame)
        assert isinstance(result.condition.managed, ManagedVerified)

    def test_managed_path_observed_as_directory_is_unsafe(self) -> None:
        managed = (
            ManagedInventoryEntry(
                path=RepoPath("docs/agents/domain.md"),
                kind="text",
                mode=PosixMode.FILE,
                sha256=sha256_hex(b"x"),
            ),
        )
        result = _classify(
            _manifest(managed=managed),
            files=_observed_files(),
            directories={
                RepoPath("docs/agents/domain.md"): CapturedDirectory(
                    RepoPath("docs/agents/domain.md"), PosixMode.DIRECTORY
                )
            },
        )
        assert isinstance(result, UnsafeExistingProject)
        assert isinstance(result.error, TopologyError)

    def test_baseline_shape_mismatch_is_unsafe(self) -> None:
        files = _observed_files()
        _ = files.pop(RepoPath("src/lib.py"))
        result = _classify(
            _manifest(),
            files=files,
            directories={
                RepoPath("src/lib.py"): CapturedDirectory(
                    RepoPath("src/lib.py"), PosixMode.DIRECTORY
                )
            },
        )
        assert isinstance(result, UnsafeExistingProject)

    def test_overlapping_unsafe_path_is_named_once(self) -> None:
        path = RepoPath("docs/agents/domain.md")
        managed = (
            ManagedInventoryEntry(
                path=path,
                kind="text",
                mode=PosixMode.FILE,
                sha256=sha256_hex(b"x"),
            ),
        )
        baseline = _github_baseline(
            entries=(
                LifecycleSourceEntry(
                    path=path,
                    kind="file",
                    mode=PosixMode.FILE,
                    sha256=sha256_hex(b"present\n"),
                ),
            )
        )
        result = _classify(
            _manifest(baseline=baseline, managed=managed),
            files={},
            directories={path: CapturedDirectory(path, PosixMode.DIRECTORY)},
        )
        assert isinstance(result, UnsafeExistingProject)
        assert isinstance(result, UnsafeExistingProject)
        assert result.error.paths == (path,)

    def test_duplicate_recorded_addition_is_incompatible(self) -> None:
        result = _classify(
            _manifest(
                answers=_answers(requested=("nix",)),
                additions=ManifestAdditions(requested=("nix",)),
            ),
            files=_observed_files(),
        )
        assert isinstance(result, IncompatibleExistingProject)
        assert isinstance(result, IncompatibleExistingProject)
        assert result.error.reason == "duplicate_addition"

    def test_unknown_recorded_capability_is_incompatible(self) -> None:
        result = _classify(
            _manifest(additions=ManifestAdditions(requested=("bogus",))),
            files=_observed_files(),
        )
        assert isinstance(result, IncompatibleExistingProject)
        assert isinstance(result, IncompatibleExistingProject)
        assert result.error.reason == "unknown_capability:bogus"

    def test_unselected_recorded_settings_are_incompatible(self) -> None:
        result = _classify(
            _manifest(answers=_answers(settings={"bogus": {}})),
            files=_observed_files(),
        )
        assert isinstance(result, IncompatibleExistingProject)
        assert isinstance(result, IncompatibleExistingProject)
        assert result.error.reason == "unselected_settings:bogus"


def _state_root_snapshot() -> StateRootSnapshot:
    return StateRootSnapshot(TARGET, (), None, False, None, False)


class TestSystemStateAssembly:
    def test_unsupported_target_is_unavailable(self) -> None:
        result = build_system_state(
            environment=UnsupportedGitTarget(TargetReason.NOT_WORKTREE),
            journal=NoJournal(),
            project=None,
            state_root=RepoPath("x"),
        )
        assert isinstance(result, TargetUnavailable)

    def test_no_journal_requires_project_facts(self) -> None:
        context = WorktreeContext(
            target=TARGET,
            state_root=RepoPath(".git/rygor"),
            protection=OrdinaryProject(),
        )
        with pytest.raises(TypeError):
            _ = build_system_state(
                environment=SupportedWorktree(context),
                journal=NoJournal(),
                project=None,
                state_root=RepoPath(".git/rygor"),
            )

    def test_observation_pass_requires_sorted_files(self) -> None:
        files = (
            CapturedFile(RepoPath("b.txt"), b"", PosixMode.FILE),
            CapturedFile(RepoPath("a.txt"), b"", PosixMode.FILE),
        )
        with pytest.raises(TypeError):
            _ = ProjectObservationPass(TARGET, (), _state_root_snapshot(), files, ())

    def test_observation_pass_requires_sorted_directories(self) -> None:
        directories = (
            CapturedDirectory(RepoPath("z"), PosixMode.DIRECTORY),
            CapturedDirectory(RepoPath("a"), PosixMode.DIRECTORY),
        )
        with pytest.raises(TypeError):
            _ = ProjectObservationPass(
                TARGET, (), _state_root_snapshot(), (), directories
            )

    def test_observation_pass_accepts_sorted_captures(self) -> None:
        files = (CapturedFile(RepoPath("a.txt"), b"", PosixMode.FILE),)
        directories = (CapturedDirectory(RepoPath("z"), PosixMode.DIRECTORY),)
        _ = ProjectObservationPass(
            TARGET, (), _state_root_snapshot(), files, directories
        )


def _inventory_bytes(
    paths: tuple[RepoPath, ...],
    *,
    kinds: dict[str, tuple[str, str]] | None = None,
) -> bytes:
    entries: list[dict[str, str]] = []
    for path in paths:
        kind, sha256 = (kinds or {}).get(path.value, ("directory", sha256_hex(b"tree")))
        entries.append({"path": path.value, "kind": kind, "sha256": sha256})
    return json.dumps({"schema_version": 1, "entries": entries}, sort_keys=True).encode(
        "utf-8"
    )


def _ownership_bytes(
    paths: tuple[RepoPath, ...], *, lifecycle_paths: tuple[RepoPath, ...] = ()
) -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "lifecycle_paths": [path.value for path in lifecycle_paths],
            "snapshot_cleanup_paths": [path.value for path in paths],
        },
        sort_keys=True,
    ).encode("utf-8")


def _observation_pass(
    files: tuple[CapturedFile, ...] = (),
    directories: tuple[CapturedDirectory, ...] = (),
) -> ProjectObservationPass:
    return ProjectObservationPass(
        TARGET, (), _state_root_snapshot(), files, directories
    )


def _git_worktree(parent: str) -> ResolvedGitWorktree:
    root = seed_repo(Path(parent), {"file.txt": "hello\n"})
    return ResolvedGitWorktree(
        root_abs=os.fsencode(os.fspath(root)),
        git_dir_abs=os.fsencode(os.fspath(root / ".git")),
        state_root_abs=os.fsencode(os.fspath(root / "rygor")),
        target=TARGET,
    )


class TestObservationShellContract:
    """In-process contracts for the shell-side cleanup and git-evidence helpers.

    The CLI end-to-end suite reaches these helpers only through success paths;
    these tests pin the bounded rejection and repair branches directly.
    """

    def test_repository_claude_aliases_are_outside_project_observation(self) -> None:
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".claude", "skills"))
        with open(os.path.join(root, "keep.txt"), "w", encoding="utf-8") as handle:
            _ = handle.write("kept\n")
        os.symlink("../../missing-skill", os.path.join(root, ".claude", "skills", "x"))
        result = _capture_tree(
            os.fsencode(root),
            os.fsencode(os.path.join(root, ".git")),
            DEFAULT_LIMITS,
        )
        files, directories = assert_ok(result, "non-project aliases should be ignored")
        assert tuple(entry.path for entry in files) == (RepoPath("keep.txt"),)
        assert RepoPath(".claude") not in tuple(entry.path for entry in directories)

    def test_cleanup_observation_rejects_invalid_inventories(self) -> None:
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH, b"not json", PosixMode.FILE
        )
        result = _cleanup_observation({inventory.path: inventory}, {})
        assert isinstance(result, CleanupContractMismatch)

    def test_cleanup_observation_requires_the_source_ownership(self) -> None:
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH,
            _inventory_bytes((RepoPath("tests"),)),
            PosixMode.FILE,
        )
        result = _cleanup_observation({inventory.path: inventory}, {})
        assert isinstance(result, CleanupContractMismatch)
        assert isinstance(result, CleanupContractMismatch)
        assert result.paths == (SOURCE_OWNERSHIP_PATH,)

    def test_cleanup_observation_rejects_corrupt_source_ownership(self) -> None:
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH,
            _inventory_bytes((RepoPath("tests"),)),
            PosixMode.FILE,
        )
        ownership = CapturedFile(SOURCE_OWNERSHIP_PATH, b"not json", PosixMode.FILE)
        result = _cleanup_observation(
            {inventory.path: inventory, ownership.path: ownership}, {}
        )
        assert isinstance(result, CleanupContractMismatch)

    def test_cleanup_observation_rejects_declared_set_disagreement(self) -> None:
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH,
            _inventory_bytes((RepoPath("tests"),)),
            PosixMode.FILE,
        )
        ownership = CapturedFile(
            SOURCE_OWNERSHIP_PATH,
            _ownership_bytes((RepoPath("tests"), RepoPath("pyproject.toml"))),
            PosixMode.FILE,
        )
        result = _cleanup_observation(
            {inventory.path: inventory, ownership.path: ownership}, {}
        )
        assert isinstance(result, CleanupContractMismatch)
        assert isinstance(result, CleanupContractMismatch)
        assert RepoPath("pyproject.toml") in result.paths

    def test_cleanup_observation_verifies_present_file_entries(self) -> None:
        content = b"tests content"
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH,
            _inventory_bytes(
                (RepoPath("tests"),), kinds={"tests": ("file", sha256_hex(content))}
            ),
            PosixMode.FILE,
        )
        ownership = CapturedFile(
            SOURCE_OWNERSHIP_PATH,
            _ownership_bytes((RepoPath("tests"),)),
            PosixMode.FILE,
        )
        observed = _cleanup_observation(
            {
                inventory.path: inventory,
                ownership.path: ownership,
                RepoPath("tests"): CapturedFile(
                    RepoPath("tests"), content, PosixMode.FILE
                ),
            },
            {},
        )
        assert isinstance(observed, CleanupContractValid)

    def test_cleanup_observation_reports_missing_directory_entries(self) -> None:
        inventory = CapturedFile(
            MAINTENANCE_INVENTORY_PATH,
            _inventory_bytes((RepoPath("vendor"),)),
            PosixMode.FILE,
        )
        ownership = CapturedFile(
            SOURCE_OWNERSHIP_PATH,
            _ownership_bytes((RepoPath("vendor"),)),
            PosixMode.FILE,
        )
        observed = _cleanup_observation(
            {inventory.path: inventory, ownership.path: ownership}, {}
        )
        assert isinstance(observed, CleanupContractMismatch)

    def test_retained_cleanup_contract_requires_an_inventory(self) -> None:
        error = assert_err(
            _retained_cleanup_contract(_observation_pass()),
            "expected CLEANUP_CONTRACT_INVALID",
        )
        assert error.kind.value == "cleanup_contract_invalid"

    def test_retained_cleanup_contract_falls_back_to_inventory_when_ownership_is_corrupt(
        self,
    ) -> None:
        pass_ = _observation_pass(
            (
                CapturedFile(
                    MAINTENANCE_INVENTORY_PATH,
                    _inventory_bytes((RepoPath("tests"),)),
                    PosixMode.FILE,
                ),
                CapturedFile(SOURCE_OWNERSHIP_PATH, b"not json", PosixMode.FILE),
            )
        )
        contract = assert_ok(_retained_cleanup_contract(pass_), "expected retention")
        assert contract.cleanup_paths == (
            MAINTENANCE_INVENTORY_PATH,
            RepoPath("tests"),
        )

    def test_retained_cleanup_contract_prefers_the_source_ownership(self) -> None:
        pass_ = _observation_pass(
            (
                CapturedFile(
                    MAINTENANCE_INVENTORY_PATH,
                    _inventory_bytes((RepoPath("tests"),)),
                    PosixMode.FILE,
                ),
                CapturedFile(
                    SOURCE_OWNERSHIP_PATH,
                    _ownership_bytes((RepoPath("a.txt"),)),
                    PosixMode.FILE,
                ),
            )
        )
        contract = assert_ok(_retained_cleanup_contract(pass_), "expected retention")
        assert contract.cleanup_paths == (
            MAINTENANCE_INVENTORY_PATH,
            RepoPath("a.txt"),
        )

    def test_retained_cleanup_contract_honors_a_valid_empty_declaration(self) -> None:
        pass_ = _observation_pass(
            (
                CapturedFile(
                    MAINTENANCE_INVENTORY_PATH,
                    _inventory_bytes((RepoPath("tests"),)),
                    PosixMode.FILE,
                ),
                CapturedFile(
                    SOURCE_OWNERSHIP_PATH,
                    _ownership_bytes(()),
                    PosixMode.FILE,
                ),
            )
        )
        contract = assert_ok(_retained_cleanup_contract(pass_), "expected retention")
        assert contract.cleanup_paths == (MAINTENANCE_INVENTORY_PATH,)

    def test_retained_cleanup_contract_tolerates_invalid_inventories(self) -> None:
        pass_ = _observation_pass(
            (CapturedFile(MAINTENANCE_INVENTORY_PATH, b"not json", PosixMode.FILE),)
        )
        contract = assert_ok(_retained_cleanup_contract(pass_), "expected retention")
        assert contract.cleanup_paths == (MAINTENANCE_INVENTORY_PATH,)

    def test_snapshot_evidence_reads_committed_content(self) -> None:
        tmp = tempfile.mkdtemp()
        reachable, path_bytes = _snapshot_evidence(_git_worktree(tmp))
        assert reachable()
        assert path_bytes(RepoPath("file.txt")) == b"hello\n"
        assert path_bytes(RepoPath("missing.txt")) is None

    def test_snapshot_evidence_reads_the_recorded_commit(self) -> None:
        tmp = tempfile.mkdtemp()
        worktree = _git_worktree(tmp)
        root = os.fsdecode(worktree.root_abs)
        with open(os.path.join(root, "file.txt"), "w", encoding="utf-8") as handle:
            _ = handle.write("changed\n")
        _ = subprocess.run(["git", "add", "file.txt"], cwd=root, check=True)
        _ = subprocess.run(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-q",
                "-m",
                "changed",
            ],
            cwd=root,
            check=True,
        )
        recorded = (
            subprocess.run(
                ["git", "rev-parse", "HEAD~1"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .strip()
        )
        reachable, path_bytes = _snapshot_evidence(worktree, snapshot_commit=recorded)
        assert reachable()
        assert path_bytes(RepoPath("file.txt")) == b"hello\n"

    def test_snapshot_evidence_handles_unborn_heads(self) -> None:
        tmp = tempfile.mkdtemp()
        root = os.path.join(tmp, "repo")
        os.mkdir(root)
        with open(os.path.join(root, "file.txt"), "w", encoding="utf-8") as handle:
            _ = handle.write("hello\n")
        _ = subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        worktree = ResolvedGitWorktree(
            root_abs=os.fsencode(root),
            git_dir_abs=os.fsencode(os.path.join(root, ".git")),
            state_root_abs=os.fsencode(os.path.join(root, "rygor")),
            target=TARGET,
        )
        reachable, path_bytes = _snapshot_evidence(worktree)
        assert not reachable()
        assert path_bytes(RepoPath("file.txt")) is None


def _write_ownership(root: str, lifecycle_paths: tuple[str, ...]) -> None:
    state_dir = os.path.join(root, ".rygor")
    os.makedirs(state_dir, exist_ok=True)
    with open(
        os.path.join(state_dir, "source-ownership.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "schema_version": 1,
                "lifecycle_paths": list(lifecycle_paths),
                "snapshot_cleanup_paths": [],
            },
            handle,
            sort_keys=True,
        )


def _lifecycle_roots(build: list[tuple[str, str]]) -> tuple[str, ...]:
    roots = {
        relative.split("/", 1)[0]
        for relative, _content in build
        if RepoPath(relative) not in SEED_ONCE_PATHS
    }
    return tuple(sorted(roots))


def _build_repo(
    build: list[tuple[str, str]],
) -> tuple[str, tuple[LifecycleSourceEntry, ...]]:
    files: dict[str, str] = dict(build)
    files[SOURCE_OWNERSHIP_PATH.value] = json.dumps(
        {
            "schema_version": 1,
            "lifecycle_paths": list(_lifecycle_roots(build)),
            "snapshot_cleanup_paths": [],
        },
        sort_keys=True,
    )
    root = seed_repo(Path(tempfile.mkdtemp()), files, name="template")
    return os.fspath(root), ()


def _walk_source(
    root: str, managed_paths: tuple[str, ...] = ()
) -> list[LifecycleSourceEntry]:
    entries = assert_ok(
        collect_template_source_entries(
            root,
            managed_paths={RepoPath(value) for value in managed_paths},
            limits=DEFAULT_LIMITS,
        ),
        "walk",
    )
    return list(entries)


class TestTemplateSourceWalker:
    """The source-baseline walker pins tracked template source with canonical modes."""

    def test_tracked_source_records_files_and_directories(self) -> None:
        root, _ = _build_repo(
            [
                ("src/lib.py", "present\n"),
                ("src/tools/run.sh", "#!/bin/sh\n"),
                ("scripts/validate-project", "#!/usr/bin/env python3\n"),
                ("README.md", "# Example\n"),
            ]
        )
        os.chmod(os.path.join(root, "src/tools/run.sh"), 0o755)
        entries = _walk_source(root)
        paths = [entry.path.value for entry in entries]
        assert paths == [
            ".rygor/source-ownership.json",
            "src",
            "src/lib.py",
            "src/tools",
            "src/tools/run.sh",
        ]
        by_path = {entry.path.value: entry for entry in entries}
        assert by_path["src/lib.py"].kind == "file"
        assert by_path["src/lib.py"].mode == PosixMode.FILE
        assert by_path["src/lib.py"].sha256 == sha256_hex(b"present\n")
        assert by_path["src/tools"].kind == "directory"
        assert by_path["src/tools"].mode == PosixMode.DIRECTORY
        assert by_path["src/tools"].sha256 == sha256_hex(
            b"template/source/dir:src/tools"
        )
        assert by_path["src/tools/run.sh"].mode == PosixMode.EXECUTABLE

    def test_untracked_and_generated_state_is_skipped(self) -> None:
        root, _ = _build_repo([("src/lib.py", "present\n")])
        for relative, content in [
            ("junk.tmp", "untracked\n"),
            (".venv/site-packages/pkg.py", "env\n"),
            ("__pycache__/lib.cpython-312.pyc", b"\x00\x01".decode("latin-1")),
        ]:
            target = os.path.join(root, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                _ = handle.write(content)
        entries = _walk_source(root)
        assert [entry.path.value for entry in entries] == [
            ".rygor/source-ownership.json",
            "src",
            "src/lib.py",
        ]

    def test_generated_state_below_declared_root_is_skipped(self) -> None:
        root, _ = _build_repo([("src/lib.py", "present\n")])
        cache = os.path.join(root, "src", "__pycache__")
        os.makedirs(cache)
        with open(os.path.join(cache, "lib.cpython-314.pyc"), "wb") as handle:
            _ = handle.write(b"bytecode")
        entries = _walk_source(root)
        assert [entry.path.value for entry in entries] == [
            ".rygor/source-ownership.json",
            "src",
            "src/lib.py",
        ]

    def test_state_subtree_and_seed_once_and_managed_paths_are_excluded(self) -> None:
        root, _ = _build_repo([("src/lib.py", "present\n")])
        state_dir = os.path.join(root, ".rygor")
        os.makedirs(state_dir, exist_ok=True)
        with open(
            os.path.join(state_dir, "state.json"), "w", encoding="utf-8"
        ) as handle:
            _ = handle.write("{}")
        for relative in ("docs/prd.md", "SECURITY.md"):
            target = os.path.join(root, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as handle:
                _ = handle.write("seed\n")
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        with open(
            os.path.join(root, ".claude/settings.json"), "w", encoding="utf-8"
        ) as handle:
            _ = handle.write("managed\n")
        entries = _walk_source(root, managed_paths=(".claude/settings.json",))
        paths = [entry.path.value for entry in entries]
        assert paths == [".rygor/source-ownership.json", "src", "src/lib.py"]
        assert ".rygor" not in paths
        for seed_once in SEED_ONCE_PATHS:
            assert seed_once.value not in paths

    def test_declared_symlink_is_a_source_contract_violation(self) -> None:
        root = os.path.join(tempfile.mkdtemp(), "template")
        os.mkdir(root)
        with open(os.path.join(root, "lib.py"), "w", encoding="utf-8") as handle:
            _ = handle.write("present\n")
        os.symlink("lib.py", os.path.join(root, "alias.py"))
        _write_ownership(root, ("lib.py", "alias.py"))
        _ = subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        _ = subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        error = assert_err(
            collect_template_source_entries(
                root, managed_paths=set(), limits=DEFAULT_LIMITS
            ),
            "declared symlink should be refused",
        )
        assert error.kind == ContractErrorKind.SOURCE_CONTRACT_INVALID
        assert error.subject == "alias.py"

    def test_unlisted_symlinks_are_not_hashed(self) -> None:
        root = os.path.join(tempfile.mkdtemp(), "template")
        os.mkdir(root)
        with open(os.path.join(root, "lib.py"), "w", encoding="utf-8") as handle:
            _ = handle.write("present\n")
        os.symlink("missing.py", os.path.join(root, "broken.py"))
        os.symlink("lib.py", os.path.join(root, "loose.py"))
        _write_ownership(root, ("lib.py",))
        _ = subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        _ = subprocess.run(["git", "add", "lib.py", "broken.py"], cwd=root, check=True)
        entries = _walk_source(root)
        paths = [entry.path.value for entry in entries]
        assert "broken.py" not in paths
        assert "loose.py" not in paths

    def test_unlisted_files_are_not_hashed_even_when_tracked(self) -> None:
        root, _ = _build_repo([("src/lib.py", "present\n")])
        with open(os.path.join(root, "adopter.py"), "w", encoding="utf-8") as handle:
            _ = handle.write("adopter\n")
        _ = subprocess.run(["git", "add", "adopter.py"], cwd=root, check=True)
        entries = _walk_source(root)
        paths = [entry.path.value for entry in entries]
        assert "adopter.py" not in paths
        assert ".rygor/source-ownership.json" in paths

    def test_oversized_file_is_a_source_contract_violation(self) -> None:
        root, _ = _build_repo([("big.bin", "x" * 512)])
        limits = ResourceLimits(max_file_bytes=256)
        error = assert_err(
            collect_template_source_entries(root, managed_paths=set(), limits=limits),
            "oversized file should be refused",
        )
        assert error.kind == ContractErrorKind.SOURCE_CONTRACT_INVALID
        assert error.subject == "big.bin"

    def test_path_and_unique_bytes_bounds_are_enforced(self) -> None:
        root, _ = _build_repo([("a.txt", "a\n"), ("b.txt", "b\n"), ("c.txt", "c\n")])
        path_error = assert_err(
            collect_template_source_entries(
                root, managed_paths=set(), limits=ResourceLimits(max_paths=2)
            ),
            "path bound should be enforced",
        )
        assert path_error.kind == ContractErrorKind.SOURCE_CONTRACT_INVALID
        assert path_error.subject == "paths"
        byte_error = assert_err(
            collect_template_source_entries(
                root, managed_paths=set(), limits=ResourceLimits(max_unique_bytes=4)
            ),
            "unique-byte bound should be enforced",
        )
        assert byte_error.kind == ContractErrorKind.SOURCE_CONTRACT_INVALID
        assert byte_error.subject == "unique_bytes"
