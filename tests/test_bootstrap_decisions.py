from __future__ import annotations

import unittest

from scripts.bootstrap.decisions import (
    DescribeStatus,
    InitialInstall,
    NoRecoveryNeeded,
    RefuseMutation,
    RefusePlan,
    RefuseRecovery,
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
    Apply,
    ApplyOptions,
    ApplyPlanOptions,
    GenerationPath,
    InitBundle,
    InitOptions,
    InspectStatus,
    PlanApply,
    Recover,
    RecoverOptions,
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
    CopierExistingProject,
    CopierSourceSame,
    EmptyManifestFree,
    ManagedVerified,
    NoSnapshotCleanup,
    OrdinaryProject,
    OutputAvailable,
    ProjectAvailable,
    ProtectedTargetAvailable,
    RecognizedScaffold,
    RecordedProjectState,
    SnapshotExistingProject,
    SnapshotSourceSame,
    SupportedWorktree,
    TargetSnapshot,
    TargetUnavailable,
    UnsupportedGitTarget,
    WorktreeContext,
)


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
            RecognizedScaffold("github", NoSnapshotCleanup(), EmptyManifestFree(), ()),
        )
        decision = decide_project(InspectStatus(StatusOptions()), state)
        self.assertIsInstance(decision, DescribeStatus)

    def test_protected_target_refuses_mutation_but_allows_status(self) -> None:
        state = ProjectAvailable(
            worktree(protected=True),
            RecognizedScaffold("github", NoSnapshotCleanup(), EmptyManifestFree(), ()),
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
            RecognizedScaffold("github", NoSnapshotCleanup(), EmptyManifestFree(), ()),
        )
        decision = decide_project(PlanApply(ApplyPlanOptions()), state)
        self.assertIsInstance(decision, RefusePlan)

    def test_unsupported_target_is_refused_and_recovery_is_noop(self) -> None:
        state = TargetUnavailable(UnsupportedGitTarget("not_a_worktree"))
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
            worktree(), RecognizedScaffold("github", mismatch, EmptyManifestFree(), ())
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

    def test_planning_refusal_stays_in_the_planning_decision_family(self) -> None:
        state = TargetUnavailable(UnsupportedGitTarget("not_a_worktree"))
        decision = decide_project(PlanApply(ApplyPlanOptions()), state)
        self.assertIsInstance(decision, RefusePlan)

    def test_generation_specific_project_constructors_reject_crossed_conditions(
        self,
    ) -> None:
        snapshot = TargetSnapshot(())
        recorded = RecordedProjectState(GenerationPath.GITHUB)
        with self.assertRaises(TypeError):
            SnapshotExistingProject(
                recorded,
                CopierSourceSame(ManagedVerified()),  # ty: ignore[invalid-argument-type]
                snapshot,
            )
        with self.assertRaises(TypeError):
            CopierExistingProject(
                recorded,
                SnapshotSourceSame(ManagedVerified()),  # ty: ignore[invalid-argument-type]
                snapshot,
            )

    def test_recovery_without_journal_is_a_typed_noop(self) -> None:
        state = ProjectAvailable(
            worktree(),
            RecognizedScaffold("github", NoSnapshotCleanup(), EmptyManifestFree(), ()),
        )
        self.assertIsInstance(
            decide_project(Recover(RecoverOptions()), state), NoRecoveryNeeded
        )


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
    unittest.main()
