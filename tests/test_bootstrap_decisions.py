from __future__ import annotations

import unittest
from typing import cast

from scripts.bootstrap.decisions import (
    AddCapabilities,
    CompileCandidate,
    DescribeStatus,
    DiscardPreparation,
    DiscardStalePending,
    FinishForward,
    FinishRollbackCleanup,
    InitialInstall,
    NoRecoveryNeeded,
    ReconcileTemplate,
    RefuseMutation,
    RefusePlan,
    RefuseRecovery,
    RestoreManaged,
    RollBack,
    WriteBundle,
    decide_bundle,
    decide_project,
)
from scripts.bootstrap.errors import (
    ObservationErrorKind,
    TransitionError,
    TransitionErrorKind,
)
from scripts.bootstrap.identity import TargetIdentity
from scripts.bootstrap.intents import (
    Add,
    AddOptions,
    Apply,
    ApplyOptions,
    ApplyPlanOptions,
    GenerationPath,
    InitBundle,
    InitOptions,
    InspectStatus,
    PlanAdd,
    PlanApply,
    PlanReconcile,
    PlanRestore,
    Reconcile,
    ReconcileOptions,
    Recover,
    RecoverOptions,
    Restore,
    RestoreOptions,
    StatusOptions,
)
from scripts.bootstrap.observation import (
    StableRawProjectObservation,
    collect_coherent_observation,
    normalize_remote,
    target_protection_for_remotes,
)
from scripts.bootstrap.ownership import CleanupContract, validate_cleanup_contract
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.state import (
    CanonicalTemplateSource,
    CleanupContractMismatch,
    CleanupContractValid,
    ClosureError,
    CopierConflicted,
    CopierExistingProject,
    CopierSourceChanged,
    CopierSourceSame,
    EmptyManifestFree,
    ExistingProject,
    IncompatibleExistingProject,
    InvalidJournal,
    InvalidManifest,
    JournalAtDifferentTarget,
    JournalPending,
    ManagedDrift,
    ManagedVerified,
    NoSnapshotCleanup,
    OrdinaryProject,
    OrphanTransactionState,
    OutputAvailable,
    PathDelta,
    PendingIdentity,
    ProjectAvailable,
    ProtectedTargetAvailable,
    RecognizedScaffold,
    RecordedProjectState,
    SnapshotExistingProject,
    SnapshotRepair,
    SnapshotSourceChanged,
    SnapshotSourceSame,
    SnapshotSourceUnrecoverable,
    SourceDelta,
    StalePendingWrite,
    StateRootInvalid,
    SupportedWorktree,
    TargetReason,
    TargetSnapshot,
    TargetUnavailable,
    TopologyError,
    UnsafeExistingProject,
    UnsupportedGitTarget,
    UnsupportedManifestFree,
    ValidatedJournal,
    WorktreeContext,
    context_of,
    is_protected,
)
from scripts.bootstrap.values import JournalPhase


def worktree(*, protected: bool = False) -> SupportedWorktree:
    protection = (
        CanonicalTemplateSource("github.com/knirski/agentic-template")
        if protected
        else OrdinaryProject()
    )
    return SupportedWorktree(
        WorktreeContext(
            target=TargetIdentity(b"/tmp/project", 1, 2, "target"),
            state_root=RepoPath(".agentic-template"),
            protection=protection,
        )
    )


class StateAndDecisionTests(unittest.TestCase):
    def test_init_writes_available_bundle_and_refuses_occupied_output(self) -> None:
        intent = InitBundle(InitOptions(RepoPath("bootstrap.json")))
        self.assertIsInstance(decide_bundle(intent, OutputAvailable()), WriteBundle)

        from scripts.bootstrap.state import OutputLocationOccupied

        refused = decide_bundle(intent, OutputLocationOccupied())
        self.assertIsInstance(refused, RefusePlan)
        if isinstance(refused, RefusePlan):
            self.assertIsInstance(refused.error, TransitionError)
            if isinstance(refused.error, TransitionError):
                self.assertEqual(
                    refused.error.kind, TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED
                )

    def test_status_describes_supported_project_without_mutation(self) -> None:
        state = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        decision = decide_project(InspectStatus(StatusOptions()), state)
        self.assertIsInstance(decision, DescribeStatus)

    def test_protected_target_refuses_mutation_but_allows_status(self) -> None:
        state = ProjectAvailable(
            worktree(protected=True),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        mutation = decide_project(Apply(ApplyOptions()), state)
        self.assertIsInstance(mutation, RefuseMutation)
        if isinstance(mutation, RefuseMutation):
            self.assertIsInstance(mutation.error, TransitionError)
            if isinstance(mutation.error, TransitionError):
                self.assertEqual(
                    mutation.error.kind, TransitionErrorKind.UNSUPPORTED_TARGET
                )
        self.assertIsInstance(
            decide_project(InspectStatus(StatusOptions()), state), DescribeStatus
        )

    def test_protected_target_planning_refusal_stays_in_planning_family(self) -> None:
        state = ProtectedTargetAvailable(
            worktree(protected=True).context,
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        decision = decide_project(PlanApply(ApplyPlanOptions()), state)
        self.assertIsInstance(decision, RefusePlan)

    def test_unsupported_target_is_refused_and_recovery_is_noop(self) -> None:
        state = TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
        mutation = decide_project(Apply(ApplyOptions()), state)
        self.assertIsInstance(mutation, RefuseMutation)
        if isinstance(mutation, RefuseMutation):
            self.assertIsInstance(mutation.error, TransitionError)
            if isinstance(mutation.error, TransitionError):
                self.assertEqual(
                    mutation.error.kind, TransitionErrorKind.UNSUPPORTED_TARGET
                )
        self.assertIsInstance(
            decide_project(Recover(RecoverOptions()), state), RefuseRecovery
        )

    def test_scaffold_cleanup_mismatch_is_only_installable_with_leave_option(
        self,
    ) -> None:
        mismatch = CleanupContractMismatch((RepoPath("maintenance.json"),))
        state = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, mismatch, EmptyManifestFree(), ()
            ),
        )
        refused = decide_project(Apply(ApplyOptions()), state)
        self.assertIsInstance(refused, RefuseMutation)
        if isinstance(refused, RefuseMutation):
            self.assertIsInstance(refused.error, TransitionError)
            if isinstance(refused.error, TransitionError):
                self.assertEqual(
                    refused.error.kind, TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED
                )
        installed = decide_project(
            Apply(ApplyOptions(leave_maintenance_artifacts=True)), state
        )
        self.assertIsInstance(installed, InitialInstall)

    def test_apply_refuses_unrecoverable_snapshot_and_copier_conflicts(self) -> None:
        managed = ManagedVerified()
        snapshot = ProjectAvailable(
            worktree(),
            ExistingProject(
                SnapshotExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    SnapshotSourceUnrecoverable(
                        SourceDelta((RepoPath("source.txt"),)),
                        "source history is unavailable",
                        managed,
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        copier = ProjectAvailable(
            worktree(),
            ExistingProject(
                CopierExistingProject(
                    RecordedProjectState(GenerationPath.COPIER),
                    CopierConflicted(PathDelta((RepoPath(".rej"),))),
                    TargetSnapshot(()),
                )
            ),
        )

        refused_snapshot = decide_project(Apply(ApplyOptions()), snapshot)
        self.assertIsInstance(refused_snapshot, RefuseMutation)
        if isinstance(refused_snapshot, RefuseMutation):
            self.assertIsInstance(refused_snapshot.error, TransitionError)
            if isinstance(refused_snapshot.error, TransitionError):
                self.assertEqual(
                    refused_snapshot.error.kind, TransitionErrorKind.TEMPLATE_CHANGED
                )

        refused_copier = decide_project(Apply(ApplyOptions()), copier)
        self.assertIsInstance(refused_copier, RefuseMutation)
        if isinstance(refused_copier, RefuseMutation):
            self.assertIsInstance(refused_copier.error, TransitionError)
            if isinstance(refused_copier.error, TransitionError):
                self.assertEqual(
                    refused_copier.error.kind, TransitionErrorKind.COPIER_CONFLICTS
                )

        for state in (snapshot, copier):
            planned = decide_project(PlanApply(ApplyPlanOptions()), state)
            self.assertIsInstance(planned, RefusePlan)

    def test_source_change_takes_precedence_over_managed_drift(self) -> None:
        managed_drift = ManagedDrift(PathDelta((RepoPath("managed.txt"),)))
        snapshot = ProjectAvailable(
            worktree(),
            ExistingProject(
                SnapshotExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    SnapshotSourceChanged(
                        SourceDelta((RepoPath("source.txt"),)),
                        SnapshotRepair("repair", (RepoPath("source.txt"),)),
                        managed_drift,
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        decision = decide_project(Apply(ApplyOptions()), snapshot)
        self.assertIsInstance(decision, RefuseMutation)
        if isinstance(decision, RefuseMutation):
            self.assertIsInstance(decision.error, TransitionError)
            if isinstance(decision.error, TransitionError):
                self.assertEqual(
                    decision.error.kind, TransitionErrorKind.TEMPLATE_CHANGED
                )

    def test_planning_refusal_stays_in_the_planning_decision_family(self) -> None:
        state = TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
        decision = decide_project(PlanApply(ApplyPlanOptions()), state)
        self.assertIsInstance(decision, RefusePlan)

    def test_generation_specific_project_constructors_reject_crossed_conditions(
        self,
    ) -> None:
        snapshot = TargetSnapshot(())
        recorded = RecordedProjectState(GenerationPath.GITHUB)
        with self.assertRaises(TypeError):
            _ = SnapshotExistingProject(
                recorded,
                CopierSourceSame(ManagedVerified()),  # pyright: ignore[reportArgumentType]  intentional wrong-condition-type negative test
                snapshot,
            )
        with self.assertRaises(TypeError):
            _ = CopierExistingProject(
                recorded,
                SnapshotSourceSame(ManagedVerified()),  # pyright: ignore[reportArgumentType]  intentional wrong-condition-type negative test
                snapshot,
            )

    def test_unsupported_git_target_rejects_out_of_vocabulary_reasons(self) -> None:
        with self.assertRaises(TypeError):
            _ = UnsupportedGitTarget("bogus")  # pyright: ignore[reportArgumentType]  intentional out-of-vocabulary negative test

    def test_recognized_scaffold_rejects_out_of_vocabulary_generations(self) -> None:
        with self.assertRaises(TypeError):
            _ = RecognizedScaffold(
                "other",  # pyright: ignore[reportArgumentType]  intentional out-of-vocabulary negative test
                NoSnapshotCleanup(),
                EmptyManifestFree(),
                (),
            )

    def test_recovery_without_journal_is_a_typed_noop(self) -> None:
        state = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        self.assertIsInstance(
            decide_project(Recover(RecoverOptions()), state), NoRecoveryNeeded
        )

    def test_recovery_dispatches_all_journal_phases_and_blockers(self) -> None:
        phase_results = (
            (JournalPhase.PLANNED, DiscardPreparation),
            (JournalPhase.MUTATING, RollBack),
            (JournalPhase.RESTORED, FinishRollbackCleanup),
            (JournalPhase.SEALED, FinishForward),
        )
        for phase, decision_type in phase_results:
            state = JournalPending(
                worktree().context,
                ValidatedJournal(
                    "apply", TargetIdentity(b"/tmp/project", 1, 2, "target"), phase
                ),
            )
            decision = decide_project(Recover(RecoverOptions()), state)
            self.assertIsInstance(decision, decision_type)

        unknown_phase = JournalPending(
            worktree().context,
            ValidatedJournal(
                "apply",
                TargetIdentity(b"/tmp/project", 1, 2, "target"),
                cast(JournalPhase, "UNKNOWN"),  # pyright: ignore[reportInvalidCast]  intentional out-of-vocabulary phase
            ),
        )
        self.assertIsInstance(
            decide_project(Recover(RecoverOptions()), unknown_phase), RefuseRecovery
        )

        mismatch = JournalAtDifferentTarget(
            worktree().context,
            ValidatedJournal(
                "apply",
                TargetIdentity(b"/tmp/other", 1, 2, "other"),
                JournalPhase.SEALED,
            ),
            TargetIdentity(b"/tmp/project", 1, 2, "target"),
        )
        self.assertIsInstance(
            decide_project(Recover(RecoverOptions()), mismatch), RefuseRecovery
        )
        for state in (
            TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE)),
            StateRootInvalid(worktree().context, OrphanTransactionState("orphan")),
            StalePendingWrite(worktree().context, PendingIdentity("digest")),
        ):
            decision = decide_project(Recover(RecoverOptions()), state)
            self.assertIsInstance(decision, (RefuseRecovery, DiscardStalePending))

        # A canonical template source needs no recovery: the design maps it
        # to ``NoRecoveryNeeded`` rather than a refusal.
        self.assertIsInstance(
            decide_project(
                Recover(RecoverOptions()),
                ProtectedTargetAvailable(
                    worktree(protected=True).context,
                    RecognizedScaffold(
                        GenerationPath.GITHUB,
                        NoSnapshotCleanup(),
                        EmptyManifestFree(),
                        (),
                    ),
                ),
            ),
            NoRecoveryNeeded,
        )

        for state in (
            StalePendingWrite(worktree().context, PendingIdentity("digest")),
            JournalPending(
                worktree().context,
                ValidatedJournal(
                    "apply",
                    TargetIdentity(b"/tmp/project", 1, 2, "target"),
                    JournalPhase.PLANNED,
                ),
            ),
            mismatch,
            StateRootInvalid(worktree().context, OrphanTransactionState("orphan")),
        ):
            self.assertIsInstance(
                decide_project(Apply(ApplyOptions()), state), RefuseMutation
            )

    def test_apply_decision_handles_all_existing_state_families(self) -> None:
        scaffold = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB,
                CleanupContractValid(CleanupContract((), (), "fingerprint")),
                EmptyManifestFree(),
                (),
            ),
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), scaffold), InitialInstall
        )
        no_cleanup_scaffold = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), no_cleanup_scaffold), InitialInstall
        )
        for observation in (
            UnsupportedManifestFree(EmptyManifestFree(), ()),
            InvalidManifest("invalid", ()),
        ):
            self.assertIsInstance(
                decide_project(
                    Apply(ApplyOptions()), ProjectAvailable(worktree(), observation)
                ),
                RefuseMutation,
            )

        for existing, expected_kind in (
            (
                UnsafeExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    TopologyError(()),
                    TargetSnapshot(()),
                ),
                TransitionErrorKind.UNSUPPORTED_TARGET,
            ),
            (
                IncompatibleExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    ClosureError("incompatible"),
                    TargetSnapshot(()),
                ),
                TransitionErrorKind.OPERATION_UNAVAILABLE,
            ),
        ):
            decision = decide_project(
                Apply(ApplyOptions()),
                ProjectAvailable(worktree(), ExistingProject(existing)),
            )
            self.assertIsInstance(decision, RefuseMutation)
            if isinstance(decision, RefuseMutation):
                self.assertIsInstance(decision.error, TransitionError)
                if isinstance(decision.error, TransitionError):
                    self.assertEqual(decision.error.kind, expected_kind)

        verified_snapshot = ProjectAvailable(
            worktree(),
            ExistingProject(
                SnapshotExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    SnapshotSourceSame(ManagedVerified()),
                    TargetSnapshot(()),
                )
            ),
        )
        decision = decide_project(Apply(ApplyOptions()), verified_snapshot)
        self.assertIsInstance(decision, RefuseMutation)
        if isinstance(decision, RefuseMutation):
            self.assertIsInstance(decision.error, TransitionError)
            if isinstance(decision.error, TransitionError):
                self.assertEqual(
                    decision.error.kind, TransitionErrorKind.OPERATION_UNAVAILABLE
                )

        drifted_snapshot = ProjectAvailable(
            worktree(),
            ExistingProject(
                SnapshotExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    SnapshotSourceSame(
                        ManagedDrift(PathDelta((RepoPath("managed.txt"),)))
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), drifted_snapshot), RefuseMutation
        )

        drifted_copier = ProjectAvailable(
            worktree(),
            ExistingProject(
                CopierExistingProject(
                    RecordedProjectState(GenerationPath.COPIER),
                    CopierSourceSame(
                        ManagedDrift(PathDelta((RepoPath("managed.txt"),)))
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), drifted_copier), RefuseMutation
        )

        changed_copier = ProjectAvailable(
            worktree(),
            ExistingProject(
                CopierExistingProject(
                    RecordedProjectState(GenerationPath.COPIER),
                    CopierSourceChanged(
                        SourceDelta((RepoPath("source.txt"),)), ManagedVerified()
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), changed_copier), RefuseMutation
        )

    def test_project_actions_cover_add_restore_and_reconcile_families(self) -> None:
        copier_same = ProjectAvailable(
            worktree(),
            ExistingProject(
                CopierExistingProject(
                    RecordedProjectState(GenerationPath.COPIER),
                    CopierSourceSame(ManagedVerified()),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Add(AddOptions(("capability",))), copier_same),
            AddCapabilities,
        )
        self.assertIsInstance(
            decide_project(PlanAdd(AddOptions(("capability",))), copier_same),
            CompileCandidate,
        )
        self.assertIsInstance(
            decide_project(Apply(ApplyOptions()), copier_same), RefuseMutation
        )

        snapshot_same = ProjectAvailable(
            worktree(),
            ExistingProject(
                SnapshotExistingProject(
                    RecordedProjectState(GenerationPath.GITHUB),
                    SnapshotSourceSame(ManagedVerified()),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Restore(RestoreOptions()), snapshot_same), RestoreManaged
        )
        self.assertIsInstance(
            decide_project(PlanRestore(RestoreOptions()), snapshot_same),
            CompileCandidate,
        )

        copier_changed = ProjectAvailable(
            worktree(),
            ExistingProject(
                CopierExistingProject(
                    RecordedProjectState(GenerationPath.COPIER),
                    CopierSourceChanged(
                        SourceDelta((RepoPath("source.txt"),)), ManagedVerified()
                    ),
                    TargetSnapshot(()),
                )
            ),
        )
        self.assertIsInstance(
            decide_project(Reconcile(ReconcileOptions()), copier_changed),
            ReconcileTemplate,
        )
        self.assertIsInstance(
            decide_project(PlanReconcile(ReconcileOptions()), copier_changed),
            CompileCandidate,
        )

        self.assertIsInstance(
            decide_project(Add(AddOptions()), snapshot_same), RefuseMutation
        )
        self.assertIsInstance(
            decide_project(Restore(RestoreOptions()), copier_changed), RefuseMutation
        )
        self.assertIsInstance(
            decide_project(Reconcile(ReconcileOptions()), snapshot_same), RefuseMutation
        )

    def test_plan_apply_on_a_supported_scaffold_compiles(self) -> None:
        scaffold = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        self.assertIsInstance(
            decide_project(PlanApply(ApplyPlanOptions()), scaffold), CompileCandidate
        )

    def test_add_and_restore_cover_every_copier_condition_branch(self) -> None:
        scaffold = ProjectAvailable(
            worktree(),
            RecognizedScaffold(
                GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
            ),
        )
        # Non-ExistingProject observations fall through to the refusal arm.
        self.assertIsInstance(
            decide_project(Add(AddOptions()), scaffold), RefuseMutation
        )
        self.assertIsInstance(
            decide_project(Restore(RestoreOptions()), scaffold), RefuseMutation
        )
        for condition in (
            CopierSourceSame(ManagedDrift(PathDelta((RepoPath("managed.txt"),)))),
            CopierConflicted(PathDelta((RepoPath(".rej"),))),
            CopierSourceChanged(
                SourceDelta((RepoPath("source.txt"),)), ManagedVerified()
            ),
        ):
            state = ProjectAvailable(
                worktree(),
                ExistingProject(
                    CopierExistingProject(
                        RecordedProjectState(GenerationPath.COPIER),
                        condition,
                        TargetSnapshot(()),
                    )
                ),
            )
            decision = decide_project(Add(AddOptions()), state)
            self.assertIsInstance(decision, RefuseMutation)
            if isinstance(decision, RefuseMutation):
                self.assertIsInstance(decision.error, TransitionError)
                if isinstance(decision.error, TransitionError):
                    self.assertEqual(
                        decision.error.kind,
                        TransitionErrorKind.OPERATION_UNAVAILABLE,
                    )

    def test_context_of_and_is_protected_cover_every_state_family(self) -> None:
        context = worktree().context
        scaffold = RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        )
        journal = ValidatedJournal("apply", context.target, JournalPhase.PLANNED)
        self.assertIsNone(
            context_of(
                TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )
        )
        self.assertEqual(
            context_of(StalePendingWrite(context, PendingIdentity("0" * 64))),
            context,
        )
        self.assertEqual(context_of(JournalPending(context, journal)), context)
        self.assertEqual(
            context_of(JournalAtDifferentTarget(context, journal, context.target)),
            context,
        )
        self.assertEqual(
            context_of(StateRootInvalid(context, InvalidJournal("bad"))), context
        )
        protected = ProtectedTargetAvailable(worktree(protected=True).context, scaffold)
        self.assertEqual(context_of(protected), worktree(protected=True).context)
        self.assertTrue(is_protected(protected))
        self.assertFalse(
            is_protected(
                TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
            )
        )
        self.assertFalse(is_protected(ProjectAvailable(worktree(), scaffold)))


class ObservationTests(unittest.TestCase):
    def test_coherent_observation_retries_and_returns_stable_second_pair(self) -> None:
        passes = iter(
            [
                StableRawProjectObservation("a", b"first"),
                StableRawProjectObservation("b", b"changed"),
                StableRawProjectObservation("c", b"stable"),
                StableRawProjectObservation("c", b"stable"),
            ]
        )
        result = collect_coherent_observation(lambda: next(passes))
        self.assertEqual(result, Ok(StableRawProjectObservation("c", b"stable")))

    def test_three_unstable_pairs_return_concurrent_target_change(self) -> None:
        values = iter(
            StableRawProjectObservation(str(index), bytes([index]))
            for index in range(6)
        )
        result = collect_coherent_observation(lambda: next(values))
        self.assertIsInstance(result, Err)
        if isinstance(result, Err):
            self.assertEqual(
                result.error.kind, ObservationErrorKind.CONCURRENT_TARGET_CHANGE
            )

    def test_remote_normalization_matches_supported_github_forms(self) -> None:
        forms = (
            "https://github.com/knirski/agentic-template.git",
            "ssh://git@github.com:22/knirski/agentic-template.git",
            "git@github.com:knirski/agentic-template",
        )
        self.assertEqual(
            {normalize_remote(form) for form in forms},
            {"github.com/knirski/agentic-template"},
        )
        self.assertIsInstance(
            target_protection_for_remotes(forms), CanonicalTemplateSource
        )


class OwnershipTests(unittest.TestCase):
    def test_cleanup_contract_requires_exact_disjoint_declared_paths(self) -> None:
        result = validate_cleanup_contract(
            CleanupContract(
                lifecycle_paths=(RepoPath("scripts/bootstrap.py"),),
                cleanup_paths=(RepoPath("pyproject.toml"),),
                fingerprint="fingerprint",
            ),
            (RepoPath("pyproject.toml"),),
        )
        self.assertIsInstance(result, Ok)
        invalid = validate_cleanup_contract(
            CleanupContract(
                lifecycle_paths=(RepoPath("pyproject.toml"),),
                cleanup_paths=(RepoPath("pyproject.toml"),),
                fingerprint="fingerprint",
            ),
            (RepoPath("pyproject.toml"),),
        )
        self.assertIsInstance(invalid, Err)


if __name__ == "__main__":
    _ = unittest.main()
