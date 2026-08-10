"""Pure generated-lifecycle source baseline derivation.

The source baseline records the path-level identity of every generated-lifecycle source entry
plus one aggregate fingerprint. GitHub snapshots additionally bind the reachable baseline commit
used for targeted repair; Copier projects record no commit because Copier supplies their lineage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, assert_never

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.errors import ContractError, ContractErrorKind
from scripts.bootstrap.identity import PosixMode, tagged_digest
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.paths import RepoPath, parse_path
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.vocabulary import COMMIT_SHA, SHA256


@dataclass(frozen=True, slots=True, order=True)
class LifecycleSourceEntry:
    path: RepoPath
    kind: Literal["file", "directory"]
    mode: PosixMode
    sha256: str


def _source_error(subject: str) -> ContractError:
    return ContractError(ContractErrorKind.SOURCE_CONTRACT_INVALID, subject)


def _sorted_entries(
    entries: tuple[LifecycleSourceEntry, ...],
) -> tuple[LifecycleSourceEntry, ...]:
    return tuple(sorted(entries, key=lambda entry: entry.path.value.encode("utf-8")))


def _validate_entries(
    entries: tuple[LifecycleSourceEntry, ...],
) -> Result[tuple[LifecycleSourceEntry, ...], ContractError]:
    seen_paths: set[str] = set()
    for entry in entries:
        if entry.path.value in seen_paths:
            return Err(_source_error(entry.path.value))
        seen_paths.add(entry.path.value)
        if not isinstance(parse_path(entry.path.value), Ok):
            return Err(_source_error(entry.path.value))
        if entry.kind not in ("file", "directory"):
            return Err(_source_error(entry.path.value))
        match entry.kind:
            case "file":
                if entry.mode not in (PosixMode.FILE, PosixMode.EXECUTABLE):
                    return Err(_source_error(entry.path.value))
            case "directory":
                if entry.mode != PosixMode.DIRECTORY:
                    return Err(_source_error(entry.path.value))
            case _:  # pragma: no cover
                return assert_never(entry.kind)  # pragma: no cover
        if SHA256.fullmatch(entry.sha256) is None:
            return Err(_source_error(entry.path.value))
    return Ok(_sorted_entries(entries))


def template_source_fingerprint(
    entries: tuple[LifecycleSourceEntry, ...],
) -> str:
    """Return the tagged aggregate fingerprint over canonical sorted source entries."""
    payload = canonical_json(
        [
            {
                "path": entry.path.value,
                "kind": entry.kind,
                "mode": entry.mode.value,
                "sha256": entry.sha256,
            }
            for entry in _sorted_entries(entries)
        ]
    )
    return tagged_digest(b"template-source", payload)


@dataclass(frozen=True, slots=True)
class GitHubSourceBaseline:
    kind: Literal["github"]
    fingerprint: str
    entries: tuple[LifecycleSourceEntry, ...]
    snapshot_commit: str


@dataclass(frozen=True, slots=True)
class CopierSourceBaseline:
    kind: Literal["copier"]
    fingerprint: str
    entries: tuple[LifecycleSourceEntry, ...]


type SourceBaseline = GitHubSourceBaseline | CopierSourceBaseline


def derive_source_baseline(
    generation: GenerationPath,
    entries: tuple[LifecycleSourceEntry, ...],
    *,
    snapshot_commit: str | None = None,
) -> Result[SourceBaseline, ContractError]:
    """Derive the tagged source baseline for the generation path from validated entries."""
    match _validate_entries(entries):
        case Err(error):
            return Err(error)
        case Ok(sorted_entries):
            pass
    fingerprint = template_source_fingerprint(sorted_entries)
    match generation:
        case GenerationPath.GITHUB:
            if snapshot_commit is None or COMMIT_SHA.fullmatch(snapshot_commit) is None:
                return Err(_source_error("snapshot_commit"))
            return Ok(
                GitHubSourceBaseline(
                    kind="github",
                    fingerprint=fingerprint,
                    entries=sorted_entries,
                    snapshot_commit=snapshot_commit,
                )
            )
        case GenerationPath.COPIER:
            if snapshot_commit is not None:
                return Err(_source_error("snapshot_commit"))
            return Ok(
                CopierSourceBaseline(
                    kind="copier",
                    fingerprint=fingerprint,
                    entries=sorted_entries,
                )
            )
        case _:  # pragma: no cover
            return assert_never(generation)  # pragma: no cover
