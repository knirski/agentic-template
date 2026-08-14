"""Existing-project classification and system-state assembly for the observation pipeline.

Covers T12 observation classification: ``build_system_state`` closed-state assembly,
``classify_existing_project`` topology/closure/generation classification, and the
pass-shape contract of ``ProjectObservationPass``.
"""

from __future__ import annotations

import unittest

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
    build_system_state,
    classify_existing_project,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
)
from scripts.bootstrap.state import (
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
    return GitHubSourceBaseline(
        kind="github",
        fingerprint=sha256_hex(b"source"),
        entries=entries if entries is not None else _source_entries(),
        snapshot_commit="0" * 40,
    )


def _copier_baseline() -> CopierSourceBaseline:
    return CopierSourceBaseline(
        kind="copier",
        fingerprint=sha256_hex(b"source"),
        entries=_source_entries(),
    )


def _manifest(
    *,
    copier: bool = False,
    baseline: GitHubSourceBaseline | CopierSourceBaseline | None = None,
    managed: tuple[ManagedInventoryEntry, ...] = (),
    answers: ManifestAnswers | None = None,
    additions: ManifestAdditions | None = None,
) -> CandidateManifest:
    provenance = ProvenanceRecord(
        generation_path=GenerationPath.COPIER if copier else GenerationPath.GITHUB,
        maintenance=MaintenanceRecord(status="clean"),
        source_baseline=(
            baseline
            if baseline is not None
            else (_copier_baseline() if copier else _github_baseline())
        ),
    )
    match build_candidate_manifest(
        answers=answers if answers is not None else _answers(),
        additions=additions if additions is not None else ManifestAdditions(),
        provenance=provenance,
        managed=managed,
    ):
        case Ok(manifest):
            return manifest
        case Err(error):
            raise AssertionError(f"manifest build failed: {error}")


def _observed_files() -> dict[RepoPath, CapturedFile]:
    """Observed files matching every file entry of ``_source_entries`` exactly."""
    return {
        RepoPath("src/lib.py"): CapturedFile(
            RepoPath("src/lib.py"), b"present\n", PosixMode.FILE
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


class ProjectClassificationTests(unittest.TestCase):
    def test_github_matching_observation_classifies_source_same(self) -> None:
        result = _classify(_manifest(), files=_observed_files())
        self.assertIsInstance(result, SnapshotExistingProject)
        if isinstance(result, SnapshotExistingProject):
            self.assertIsInstance(result.condition, SnapshotSourceSame)
            self.assertIsInstance(result.condition.managed, ManagedVerified)

    def test_unreachable_snapshot_commit_is_unrecoverable(self) -> None:
        result = _classify(_manifest(), files={}, commit_reachable=False)
        self.assertIsInstance(result, SnapshotExistingProject)
        if isinstance(result, SnapshotExistingProject):
            self.assertIsInstance(result.condition, SnapshotSourceUnrecoverable)

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
        self.assertIsInstance(result, SnapshotExistingProject)
        if isinstance(result, SnapshotExistingProject):
            self.assertIsInstance(result.condition, SnapshotSourceUnrecoverable)
            if isinstance(result.condition, SnapshotSourceUnrecoverable):
                self.assertIn(
                    "directory source repair is unavailable", result.condition.reason
                )

    def test_content_differing_at_commit_is_unrecoverable(self) -> None:
        result = _classify(_manifest(), files={}, at_commit=b"wrong bytes")
        self.assertIsInstance(result, SnapshotExistingProject)
        if isinstance(result, SnapshotExistingProject):
            self.assertIsInstance(result.condition, SnapshotSourceUnrecoverable)
            if isinstance(result.condition, SnapshotSourceUnrecoverable):
                self.assertIn("differs at commit", result.condition.reason)

    def test_changed_file_repairs_from_the_recorded_commit(self) -> None:
        result = _classify(_manifest(), files={}, at_commit=b"present\n")
        self.assertIsInstance(result, SnapshotExistingProject)
        if isinstance(result, SnapshotExistingProject):
            self.assertIsInstance(result.condition, SnapshotSourceChanged)
            if isinstance(result.condition, SnapshotSourceChanged):
                self.assertEqual(result.condition.repair.commit, "0" * 40)
                self.assertEqual(
                    result.condition.repair.paths,
                    (RepoPath("src/lib.py"),),
                )

    def test_missing_copier_answers_is_conflicted(self) -> None:
        result = _classify(_manifest(copier=True), copier_answers_present=False)
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierConflicted)

    def test_copier_matching_observation_is_source_same(self) -> None:
        result = _classify(
            _manifest(copier=True),
            copier_answers_present=True,
            files=_observed_files(),
        )
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierSourceSame)

    def test_copier_source_change_is_reported(self) -> None:
        result = _classify(
            _manifest(copier=True), copier_answers_present=True, files={}
        )
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierSourceChanged)
            if isinstance(result.condition, CopierSourceChanged):
                self.assertEqual(
                    result.condition.delta.paths,
                    (RepoPath("src/lib.py"),),
                )

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
        )
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierSourceSame)
            if isinstance(result.condition, CopierSourceSame):
                self.assertIsInstance(result.condition.managed, ManagedDrift)
                if isinstance(result.condition.managed, ManagedDrift):
                    self.assertEqual(
                        result.condition.managed.delta.paths,
                        (RepoPath("docs/api.md"),),
                    )

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
        )
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierSourceSame)
            if isinstance(result.condition, CopierSourceSame):
                self.assertIsInstance(result.condition.managed, ManagedDrift)

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
        )
        self.assertIsInstance(result, CopierExistingProject)
        if isinstance(result, CopierExistingProject):
            self.assertIsInstance(result.condition, CopierSourceSame)
            if isinstance(result.condition, CopierSourceSame):
                self.assertIsInstance(result.condition.managed, ManagedVerified)

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
        self.assertIsInstance(result, UnsafeExistingProject)
        if isinstance(result, UnsafeExistingProject):
            self.assertIsInstance(result.error, TopologyError)

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
        self.assertIsInstance(result, UnsafeExistingProject)

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
        self.assertIsInstance(result, UnsafeExistingProject)
        if isinstance(result, UnsafeExistingProject):
            self.assertEqual(result.error.paths, (path,))

    def test_duplicate_recorded_addition_is_incompatible(self) -> None:
        result = _classify(
            _manifest(
                answers=_answers(requested=("nix",)),
                additions=ManifestAdditions(requested=("nix",)),
            ),
            files=_observed_files(),
        )
        self.assertIsInstance(result, IncompatibleExistingProject)
        if isinstance(result, IncompatibleExistingProject):
            self.assertEqual(result.error.reason, "duplicate_addition")

    def test_unknown_recorded_capability_is_incompatible(self) -> None:
        result = _classify(
            _manifest(additions=ManifestAdditions(requested=("bogus",))),
            files=_observed_files(),
        )
        self.assertIsInstance(result, IncompatibleExistingProject)
        if isinstance(result, IncompatibleExistingProject):
            self.assertEqual(result.error.reason, "unknown_capability:bogus")

    def test_unselected_recorded_settings_are_incompatible(self) -> None:
        result = _classify(
            _manifest(answers=_answers(settings={"bogus": {}})),
            files=_observed_files(),
        )
        self.assertIsInstance(result, IncompatibleExistingProject)
        if isinstance(result, IncompatibleExistingProject):
            self.assertEqual(result.error.reason, "unselected_settings:bogus")


def _state_root_snapshot() -> StateRootSnapshot:
    return StateRootSnapshot(TARGET, (), None, False, None, False)


class SystemStateAssemblyTests(unittest.TestCase):
    def test_unsupported_target_is_unavailable(self) -> None:
        result = build_system_state(
            environment=UnsupportedGitTarget(TargetReason.NOT_WORKTREE),
            journal=NoJournal(),
            project=None,
            state_root=RepoPath("x"),
        )
        self.assertIsInstance(result, TargetUnavailable)

    def test_no_journal_requires_project_facts(self) -> None:
        context = WorktreeContext(
            target=TARGET,
            state_root=RepoPath(".git/agentic-template"),
            protection=OrdinaryProject(),
        )
        with self.assertRaises(TypeError):
            _ = build_system_state(
                environment=SupportedWorktree(context),
                journal=NoJournal(),
                project=None,
                state_root=RepoPath(".git/agentic-template"),
            )

    def test_observation_pass_requires_sorted_files(self) -> None:
        files = (
            CapturedFile(RepoPath("b.txt"), b"", PosixMode.FILE),
            CapturedFile(RepoPath("a.txt"), b"", PosixMode.FILE),
        )
        with self.assertRaises(TypeError):
            _ = ProjectObservationPass(TARGET, (), _state_root_snapshot(), files, ())

    def test_observation_pass_requires_sorted_directories(self) -> None:
        directories = (
            CapturedDirectory(RepoPath("z"), PosixMode.DIRECTORY),
            CapturedDirectory(RepoPath("a"), PosixMode.DIRECTORY),
        )
        with self.assertRaises(TypeError):
            _ = ProjectObservationPass(
                TARGET, (), _state_root_snapshot(), (), directories
            )

    def test_observation_pass_accepts_sorted_captures(self) -> None:
        files = (CapturedFile(RepoPath("a.txt"), b"", PosixMode.FILE),)
        directories = (CapturedDirectory(RepoPath("z"), PosixMode.DIRECTORY),)
        _ = ProjectObservationPass(
            TARGET, (), _state_root_snapshot(), files, directories
        )


if __name__ == "__main__":
    _ = unittest.main()
