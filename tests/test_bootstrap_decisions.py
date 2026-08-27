from __future__ import annotations

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
    ContractError,
    ContractErrorKind,
    ObservationErrorKind,
    TransactionError,
    TransactionErrorKind,
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
        CanonicalTemplateSource("github.com/knirski/rygor")
        if protected
        else OrdinaryProject()
    )
    return SupportedWorktree(
        WorktreeContext(
            target=TargetIdentity(b"/tmp/project", 1, 2, "target"),
            state_root=RepoPath(".rygor"),
            protection=protection,
        )
    )


def test_init_writes_available_bundle_and_refuses_occupied_output() -> None:
    intent = InitBundle(InitOptions(RepoPath("bootstrap.json")))
    assert isinstance(decide_bundle(intent, OutputAvailable()), WriteBundle)

    from scripts.bootstrap.state import OutputLocationOccupied

    refused = decide_bundle(intent, OutputLocationOccupied())
    assert isinstance(refused, RefusePlan)
    assert isinstance(refused.error, TransitionError)
    assert refused.error.kind == TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED


def test_status_describes_supported_project_without_mutation() -> None:
    state = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    decision = decide_project(InspectStatus(StatusOptions()), state)
    assert isinstance(decision, DescribeStatus)


def test_protected_target_refuses_mutation_but_allows_status() -> None:
    state = ProjectAvailable(
        worktree(protected=True),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    mutation = decide_project(Apply(ApplyOptions()), state)
    assert isinstance(mutation, RefuseMutation)
    assert isinstance(mutation.error, TransitionError)
    assert mutation.error.kind == TransitionErrorKind.UNSUPPORTED_TARGET
    assert isinstance(
        decide_project(InspectStatus(StatusOptions()), state), DescribeStatus
    )


def test_protected_target_planning_refusal_stays_in_planning_family() -> None:
    state = ProtectedTargetAvailable(
        worktree(protected=True).context,
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    decision = decide_project(PlanApply(ApplyPlanOptions()), state)
    assert isinstance(decision, RefusePlan)


def test_unsupported_target_is_refused_and_recovery_is_noop() -> None:
    state = TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
    mutation = decide_project(Apply(ApplyOptions()), state)
    assert isinstance(mutation, RefuseMutation)
    assert isinstance(mutation.error, TransitionError)
    assert mutation.error.kind == TransitionErrorKind.UNSUPPORTED_TARGET
    assert isinstance(decide_project(Recover(RecoverOptions()), state), RefuseRecovery)


def test_scaffold_cleanup_mismatch_is_only_installable_with_leave_option() -> None:
    mismatch = CleanupContractMismatch((RepoPath("maintenance.json"),))
    state = ProjectAvailable(
        worktree(),
        RecognizedScaffold(GenerationPath.GITHUB, mismatch, EmptyManifestFree(), ()),
    )
    refused = decide_project(Apply(ApplyOptions()), state)
    assert isinstance(refused, RefuseMutation)
    assert isinstance(refused.error, TransitionError)
    assert refused.error.kind == TransitionErrorKind.OUTPUT_LOCATION_OCCUPIED
    installed = decide_project(
        Apply(ApplyOptions(leave_maintenance_artifacts=True)), state
    )
    assert isinstance(installed, InitialInstall)


def test_apply_refuses_unrecoverable_snapshot_and_copier_conflicts() -> None:
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
    assert isinstance(refused_snapshot, RefuseMutation)
    assert isinstance(refused_snapshot.error, TransitionError)
    assert refused_snapshot.error.kind == TransitionErrorKind.TEMPLATE_CHANGED

    refused_copier = decide_project(Apply(ApplyOptions()), copier)
    assert isinstance(refused_copier, RefuseMutation)
    assert isinstance(refused_copier.error, TransitionError)
    assert refused_copier.error.kind == TransitionErrorKind.COPIER_CONFLICTS

    for state in (snapshot, copier):
        planned = decide_project(PlanApply(ApplyPlanOptions()), state)
        assert isinstance(planned, RefusePlan)


def test_source_change_takes_precedence_over_managed_drift() -> None:
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
    assert isinstance(decision, RefuseMutation)
    assert isinstance(decision.error, TransitionError)
    assert decision.error.kind == TransitionErrorKind.TEMPLATE_CHANGED


def test_planning_refusal_stays_in_the_planning_decision_family() -> None:
    state = TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
    decision = decide_project(PlanApply(ApplyPlanOptions()), state)
    assert isinstance(decision, RefusePlan)


def test_generation_specific_project_constructors_reject_crossed_conditions() -> None:
    snapshot = TargetSnapshot(())
    recorded = RecordedProjectState(GenerationPath.GITHUB)
    try:
        _ = SnapshotExistingProject(
            recorded,
            CopierSourceSame(ManagedVerified()),  # pyright: ignore[reportArgumentType]  intentional wrong-condition-type negative test
            snapshot,
        )
        raise AssertionError("expected TypeError")
    except TypeError:
        pass
    try:
        _ = CopierExistingProject(
            recorded,
            SnapshotSourceSame(ManagedVerified()),  # pyright: ignore[reportArgumentType]  intentional wrong-condition-type negative test
            snapshot,
        )
        raise AssertionError("expected TypeError")
    except TypeError:
        pass


def test_unsupported_git_target_rejects_out_of_vocabulary_reasons() -> None:
    try:
        _ = UnsupportedGitTarget("bogus")  # pyright: ignore[reportArgumentType]  intentional out-of-vocabulary negative test
        raise AssertionError("expected TypeError")
    except TypeError:
        pass


def test_recognized_scaffold_rejects_out_of_vocabulary_generations() -> None:
    try:
        _ = RecognizedScaffold(
            "other",  # pyright: ignore[reportArgumentType]  intentional out-of-vocabulary negative test
            NoSnapshotCleanup(),
            EmptyManifestFree(),
            (),
        )
        raise AssertionError("expected TypeError")
    except TypeError:
        pass


def test_recovery_without_journal_is_a_typed_noop() -> None:
    state = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    assert isinstance(
        decide_project(Recover(RecoverOptions()), state), NoRecoveryNeeded
    )


def test_recovery_dispatches_all_journal_phases_and_blockers() -> None:
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
        assert isinstance(decision, decision_type)

    unknown_phase = JournalPending(
        worktree().context,
        ValidatedJournal(
            "apply",
            TargetIdentity(b"/tmp/project", 1, 2, "target"),
            cast(JournalPhase, "UNKNOWN"),  # pyright: ignore[reportInvalidCast]  intentional out-of-vocabulary phase
        ),
    )
    assert isinstance(
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
    assert isinstance(
        decide_project(Recover(RecoverOptions()), mismatch), RefuseRecovery
    )
    for state in (
        TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE)),
        StateRootInvalid(worktree().context, OrphanTransactionState("orphan")),
        StalePendingWrite(worktree().context, PendingIdentity("digest")),
    ):
        decision = decide_project(Recover(RecoverOptions()), state)
        assert isinstance(decision, (RefuseRecovery, DiscardStalePending))

    state_root_decision = decide_project(
        Recover(RecoverOptions()),
        StateRootInvalid(worktree().context, OrphanTransactionState("orphan")),
    )
    assert isinstance(state_root_decision, RefuseRecovery)
    assert state_root_decision.error == TransactionError(
        TransactionErrorKind.INVALID_STATE_ROOT,
        subject="state root evidence",
    )

    # A canonical template source needs no recovery: the design maps it
    # to ``NoRecoveryNeeded`` rather than a refusal.
    assert isinstance(
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
        assert isinstance(decide_project(Apply(ApplyOptions()), state), RefuseMutation)


def test_apply_decision_handles_all_existing_state_families() -> None:
    scaffold = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB,
            CleanupContractValid(CleanupContract((), (), "fingerprint")),
            EmptyManifestFree(),
            (),
        ),
    )
    assert isinstance(decide_project(Apply(ApplyOptions()), scaffold), InitialInstall)
    no_cleanup_scaffold = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    assert isinstance(
        decide_project(Apply(ApplyOptions()), no_cleanup_scaffold), InitialInstall
    )
    for observation in (
        UnsupportedManifestFree(EmptyManifestFree(), ()),
        InvalidManifest("invalid", ()),
    ):
        assert isinstance(
            decide_project(
                Apply(ApplyOptions()), ProjectAvailable(worktree(), observation)
            ),
            RefuseMutation,
        )
    invalid_manifest_decision = decide_project(
        Apply(ApplyOptions()),
        ProjectAvailable(worktree(), InvalidManifest("invalid", ())),
    )
    assert isinstance(invalid_manifest_decision, RefuseMutation)
    assert invalid_manifest_decision.error == ContractError(
        ContractErrorKind.INVALID_MANIFEST, "invalid"
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
        assert isinstance(decision, RefuseMutation)
        assert isinstance(decision.error, TransitionError)
        assert decision.error.kind == expected_kind

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
    assert isinstance(decision, RefuseMutation)
    assert isinstance(decision.error, TransitionError)
    assert decision.error.kind == TransitionErrorKind.OPERATION_UNAVAILABLE

    drifted_snapshot = ProjectAvailable(
        worktree(),
        ExistingProject(
            SnapshotExistingProject(
                RecordedProjectState(GenerationPath.GITHUB),
                SnapshotSourceSame(ManagedDrift(PathDelta((RepoPath("managed.txt"),)))),
                TargetSnapshot(()),
            )
        ),
    )
    assert isinstance(
        decide_project(Apply(ApplyOptions()), drifted_snapshot), RefuseMutation
    )

    drifted_copier = ProjectAvailable(
        worktree(),
        ExistingProject(
            CopierExistingProject(
                RecordedProjectState(GenerationPath.COPIER),
                CopierSourceSame(ManagedDrift(PathDelta((RepoPath("managed.txt"),)))),
                TargetSnapshot(()),
            )
        ),
    )
    assert isinstance(
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
    assert isinstance(
        decide_project(Apply(ApplyOptions()), changed_copier), RefuseMutation
    )


def test_project_actions_cover_add_restore_and_reconcile_families() -> None:
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
    assert isinstance(
        decide_project(Add(AddOptions(("capability",))), copier_same),
        AddCapabilities,
    )
    assert isinstance(
        decide_project(PlanAdd(AddOptions(("capability",))), copier_same),
        CompileCandidate,
    )
    assert isinstance(
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
    assert isinstance(
        decide_project(Restore(RestoreOptions()), snapshot_same), RestoreManaged
    )
    assert isinstance(
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
    assert isinstance(
        decide_project(Reconcile(ReconcileOptions()), copier_changed),
        ReconcileTemplate,
    )
    assert isinstance(
        decide_project(PlanReconcile(ReconcileOptions()), copier_changed),
        CompileCandidate,
    )

    assert isinstance(decide_project(Add(AddOptions()), snapshot_same), AddCapabilities)
    assert isinstance(
        decide_project(Restore(RestoreOptions()), copier_changed), RefuseMutation
    )
    assert isinstance(
        decide_project(Reconcile(ReconcileOptions()), snapshot_same), RefuseMutation
    )


def test_plan_apply_on_a_supported_scaffold_compiles() -> None:
    scaffold = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    assert isinstance(
        decide_project(PlanApply(ApplyPlanOptions()), scaffold), CompileCandidate
    )


def test_add_and_restore_cover_every_copier_condition_branch() -> None:
    scaffold = ProjectAvailable(
        worktree(),
        RecognizedScaffold(
            GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
        ),
    )
    # Non-ExistingProject observations fall through to the refusal arm.
    assert isinstance(decide_project(Add(AddOptions()), scaffold), RefuseMutation)
    assert isinstance(
        decide_project(Restore(RestoreOptions()), scaffold), RefuseMutation
    )
    drift = CopierSourceSame(ManagedDrift(PathDelta((RepoPath("managed.txt"),))))
    drift_state = ProjectAvailable(
        worktree(),
        ExistingProject(
            CopierExistingProject(
                RecordedProjectState(GenerationPath.COPIER),
                drift,
                TargetSnapshot(()),
            )
        ),
    )
    drift_decision = decide_project(Add(AddOptions()), drift_state)
    assert isinstance(drift_decision, RefuseMutation)
    assert isinstance(drift_decision.error, TransitionError)
    assert drift_decision.error.kind == TransitionErrorKind.MANAGED_DRIFT

    for condition in (
        CopierConflicted(PathDelta((RepoPath(".rej"),))),
        CopierSourceChanged(SourceDelta((RepoPath("source.txt"),)), ManagedVerified()),
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
        assert isinstance(decision, RefuseMutation)
        assert isinstance(decision.error, TransitionError)
        assert decision.error.kind == TransitionErrorKind.OPERATION_UNAVAILABLE


def test_context_of_and_is_protected_cover_every_state_family() -> None:
    context = worktree().context
    scaffold = RecognizedScaffold(
        GenerationPath.GITHUB, NoSnapshotCleanup(), EmptyManifestFree(), ()
    )
    journal = ValidatedJournal("apply", context.target, JournalPhase.PLANNED)
    assert (
        context_of(TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE)))
        is None
    )
    assert context_of(StalePendingWrite(context, PendingIdentity("0" * 64))) == context
    assert context_of(JournalPending(context, journal)) == context
    assert (
        context_of(JournalAtDifferentTarget(context, journal, context.target))
        == context
    )
    assert context_of(StateRootInvalid(context, InvalidJournal("bad"))) == context
    protected = ProtectedTargetAvailable(worktree(protected=True).context, scaffold)
    assert context_of(protected) == worktree(protected=True).context
    assert is_protected(protected)
    assert not is_protected(
        TargetUnavailable(UnsupportedGitTarget(TargetReason.NOT_WORKTREE))
    )
    assert not is_protected(ProjectAvailable(worktree(), scaffold))


def test_coherent_observation_retries_and_returns_stable_second_pair() -> None:
    passes = iter(
        [
            StableRawProjectObservation("a", b"first"),
            StableRawProjectObservation("b", b"changed"),
            StableRawProjectObservation("c", b"stable"),
            StableRawProjectObservation("c", b"stable"),
        ]
    )
    result = collect_coherent_observation(lambda: next(passes))
    assert result == Ok(StableRawProjectObservation("c", b"stable"))


def test_three_unstable_pairs_return_concurrent_target_change() -> None:
    values = iter(
        StableRawProjectObservation(str(index), bytes([index])) for index in range(6)
    )
    result = collect_coherent_observation(lambda: next(values))
    assert isinstance(result, Err)
    assert result.error.kind == ObservationErrorKind.CONCURRENT_TARGET_CHANGE


def test_remote_normalization_matches_supported_github_forms() -> None:
    forms = (
        "https://github.com/knirski/rygor.git",
        "ssh://git@github.com:22/knirski/rygor.git",
        "git@github.com:knirski/rygor",
    )
    assert {normalize_remote(form) for form in forms} == {"github.com/knirski/rygor"}
    assert isinstance(target_protection_for_remotes(forms), CanonicalTemplateSource)


def test_cleanup_contract_requires_exact_disjoint_declared_paths() -> None:
    result = validate_cleanup_contract(
        CleanupContract(
            lifecycle_paths=(RepoPath("scripts/bootstrap.py"),),
            cleanup_paths=(RepoPath("pyproject.toml"),),
            fingerprint="fingerprint",
        ),
        (RepoPath("pyproject.toml"),),
    )
    assert isinstance(result, Ok)
    invalid = validate_cleanup_contract(
        CleanupContract(
            lifecycle_paths=(RepoPath("pyproject.toml"),),
            cleanup_paths=(RepoPath("pyproject.toml"),),
            fingerprint="fingerprint",
        ),
        (RepoPath("pyproject.toml"),),
    )
    assert isinstance(invalid, Err)
