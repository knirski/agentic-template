"""Immutable command intents used by the bootstrap decision core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scripts.bootstrap.paths import RepoPath


class GenerationPath(StrEnum):
    GITHUB = "github"
    COPIER = "copier"


@dataclass(frozen=True, slots=True)
class InitOptions:
    output: RepoPath


@dataclass(frozen=True, slots=True)
class StatusOptions:
    explain: bool = False


@dataclass(frozen=True, slots=True)
class ApplyPlanOptions:
    bundle_digest: str = ""


@dataclass(frozen=True, slots=True)
class AddOptions:
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RestoreOptions:
    paths: tuple[RepoPath, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconcileOptions:
    overwrite_drift: bool = False
    plan_digest: str = ""


@dataclass(frozen=True, slots=True)
class ApplyOptions:
    leave_maintenance_artifacts: bool = False
    bundle_digest: str = ""


@dataclass(frozen=True, slots=True)
class RecoverOptions:
    target: RepoPath | None = None


@dataclass(frozen=True, slots=True)
class InitBundle:
    options: InitOptions


@dataclass(frozen=True, slots=True)
class InspectStatus:
    options: StatusOptions


@dataclass(frozen=True, slots=True)
class PlanApply:
    options: ApplyPlanOptions


@dataclass(frozen=True, slots=True)
class PlanAdd:
    options: AddOptions


@dataclass(frozen=True, slots=True)
class PlanRestore:
    options: RestoreOptions


@dataclass(frozen=True, slots=True)
class PlanReconcile:
    options: ReconcileOptions


@dataclass(frozen=True, slots=True)
class Apply:
    options: ApplyOptions


@dataclass(frozen=True, slots=True)
class Add:
    options: AddOptions


@dataclass(frozen=True, slots=True)
class Restore:
    options: RestoreOptions


@dataclass(frozen=True, slots=True)
class Reconcile:
    options: ReconcileOptions


@dataclass(frozen=True, slots=True)
class Recover:
    options: RecoverOptions


type ProjectIntent = (
    InspectStatus
    | PlanApply
    | PlanAdd
    | PlanRestore
    | PlanReconcile
    | Apply
    | Add
    | Restore
    | Reconcile
    | Recover
)
type Intent = InitBundle | ProjectIntent
