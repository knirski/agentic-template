"""Pure recovery decisions for interrupted bootstrap transactions.

``recovery_action`` maps every closed journal observation onto exactly one
recovery action family: only ``recover`` may verify and discard a stale
pending write, a ``PLANNED`` journal cleans identity-verified preparation, a
``MUTATING`` journal applies the idempotent rollback reducer, a ``RESTORED``
journal reverifies pre-state and finishes rollback cleanup (never
reinstalling a candidate), and a ``SEALED`` journal verifies the candidate and
finishes cleanup forward (never rolling back).  Invalid, orphan, and
target-mismatched observations refuse recovery and preserve every artifact.

``restored_verification`` and ``sealed_verification`` are the pure
phase-terminal gates: they reuse the rollback and sealed reducers but treat
any non-terminal observation as a third state that must be preserved, so
recovery never overwrites evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, assert_never

from scripts.bootstrap.identity import PosixMode, TargetIdentity
from scripts.bootstrap.journal import PreparationIdentity
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import OperationPlan, TargetSnapshot
from scripts.bootstrap.rollback import (
    AlreadyCandidate,
    AlreadyRestored,
    rollback_steps,
    sealed_steps,
)
from scripts.bootstrap.state import (
    InvalidJournal,
    JournalObservation,
    JournalTargetMismatch,
    NoJournal,
    OrphanTransactionState,
    PendingIdentity,
    RecoveryEvidenceInvalid,
    StaleJournalWrite,
    ValidatedJournal,
)
from scripts.bootstrap.values import JournalPhase


@dataclass(frozen=True, slots=True)
class NothingToRecover:
    pass


@dataclass(frozen=True, slots=True)
class RefuseRecovery:
    reason: (
        InvalidJournal
        | OrphanTransactionState
        | RecoveryEvidenceInvalid
        | JournalTargetMismatch
    )


@dataclass(frozen=True, slots=True)
class DiscardStalePending:
    pending: PendingIdentity


@dataclass(frozen=True, slots=True)
class PlannedCleanup:
    journal: ValidatedJournal


@dataclass(frozen=True, slots=True)
class RollbackInterrupted:
    journal: ValidatedJournal


@dataclass(frozen=True, slots=True)
class FinishRestoredCleanup:
    journal: ValidatedJournal


@dataclass(frozen=True, slots=True)
class FinishSealedCleanup:
    journal: ValidatedJournal


type RecoveryAction = (
    NothingToRecover
    | RefuseRecovery
    | DiscardStalePending
    | PlannedCleanup
    | RollbackInterrupted
    | FinishRestoredCleanup
    | FinishSealedCleanup
)


def recovery_action(
    observation: JournalObservation, target: TargetIdentity
) -> RecoveryAction:
    """Map one closed journal observation onto exactly one recovery action."""

    match observation:
        case NoJournal():
            return NothingToRecover()
        case StaleJournalWrite(pending=pending):
            return DiscardStalePending(pending)
        case ValidatedJournal(operation=_, target=journal_target, phase=phase):
            if journal_target != target:
                return RefuseRecovery(JournalTargetMismatch(observation, target))
            match phase:
                case JournalPhase.PLANNED:
                    return PlannedCleanup(observation)
                case JournalPhase.MUTATING:
                    return RollbackInterrupted(observation)
                case JournalPhase.RESTORED:
                    return FinishRestoredCleanup(observation)
                case JournalPhase.SEALED:
                    return FinishSealedCleanup(observation)
            return assert_never(
                phase
            )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard
        case InvalidJournal() | OrphanTransactionState() | RecoveryEvidenceInvalid():
            return RefuseRecovery(observation)
        case JournalTargetMismatch():
            return RefuseRecovery(observation)
    return assert_never(
        observation
    )  # pragma: no cover  # pyright: ignore[reportUnreachable] — proven exhaustive by recommended mode; kept as a runtime guard


@dataclass(frozen=True, slots=True)
class PreStateIntact:
    pass


@dataclass(frozen=True, slots=True)
class CandidateIntact:
    pass


@dataclass(frozen=True, slots=True)
class ThirdStateFound:
    path: RepoPath


type RestoredVerification = PreStateIntact | ThirdStateFound
type SealedVerification = CandidateIntact | ThirdStateFound


def restored_verification(
    plan: OperationPlan, snapshot: TargetSnapshot
) -> RestoredVerification:
    """Reverify every operation at its exact pre-state without reapplying anything.

    Any observation that is not already the exact pre-state is a third state:
    recovery preserves it and never reinstalls a candidate from a ``RESTORED``
    journal.
    """

    for step in rollback_steps(plan, snapshot):
        if not isinstance(step.decision, AlreadyRestored):
            return ThirdStateFound(step.path)
    return PreStateIntact()


def sealed_verification(
    plan: OperationPlan, snapshot: TargetSnapshot
) -> SealedVerification:
    """Verify every operation at its planned candidate without mutating anything.

    Any observation that is not the exact candidate is a third state: recovery
    preserves it and never rolls back a verified ``SEALED`` candidate.
    """

    for step in sealed_steps(plan, snapshot):
        if not isinstance(step.decision, AlreadyCandidate):
            return ThirdStateFound(step.path)
    return CandidateIntact()


@dataclass(frozen=True, slots=True)
class ObservedArtifact:
    """The bounded observable attributes of one preparation artifact."""

    kind: Literal["file", "directory"]
    raw_sha256: str | None
    mode: PosixMode


def preparation_matches_identity(
    identity: PreparationIdentity,
    *,
    observed_kind: Literal["file", "directory"],
    observed_raw_sha256: str | None,
    observed_mode: PosixMode,
) -> bool:
    """Return whether an observed artifact's kind, digest, and mode match its identity.

    Name derivation, marker token hash, transaction id, operation index, and
    role are validated descriptor-relatively by the shell; this pure check
    closes the kind/digest/mode comparison.
    """

    return (
        identity.expected_kind == observed_kind
        and identity.expected_raw_sha256 == observed_raw_sha256
        and identity.expected_mode == observed_mode
    )


@dataclass(frozen=True, slots=True)
class CleanupMissing:
    pass


@dataclass(frozen=True, slots=True)
class CleanupVerified:
    pass


@dataclass(frozen=True, slots=True)
class CleanupThirdState:
    pass


type CleanupDecision = CleanupMissing | CleanupVerified | CleanupThirdState


def cleanup_step(
    identity: PreparationIdentity, observed: ObservedArtifact | None
) -> CleanupDecision:
    """Decide one crash-resumable cleanup step.

    A missing artifact is already clean (an interrupted cleanup may have
    removed it, or ``git clean`` may have removed disposable adjacent
    staging); a present artifact is removable only when every journaled
    attribute matches its preparation identity.  Anything else is a third
    state that cleanup preserves.
    """

    if observed is None:
        return CleanupMissing()
    if preparation_matches_identity(
        identity,
        observed_kind=observed.kind,
        observed_raw_sha256=observed.raw_sha256,
        observed_mode=observed.mode,
    ):
        return CleanupVerified()
    return CleanupThirdState()
