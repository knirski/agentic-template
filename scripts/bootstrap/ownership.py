"""Pure source-ownership and maintenance-cleanup checks."""

from __future__ import annotations

from scripts.bootstrap.paths import RepoPath, path_byte_key, sorted_paths
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import CleanupContract, CleanupContractMismatch

__all__ = ["CleanupContract", "CleanupContractMismatch", "validate_cleanup_contract"]


def _sorted_unique(paths: tuple[RepoPath, ...]) -> tuple[RepoPath, ...]:
    return sorted_paths(set(paths))


def validate_cleanup_contract(
    contract: CleanupContract,
    observed_cleanup_paths: tuple[RepoPath, ...],
) -> Result[CleanupContract, CleanupContractMismatch]:
    """Require exact, disjoint cleanup ownership before deletion is authorized."""

    lifecycle = _sorted_unique(contract.lifecycle_paths)
    cleanup = _sorted_unique(contract.cleanup_paths)
    observed = _sorted_unique(observed_cleanup_paths)
    if set(lifecycle) & set(cleanup) or cleanup != observed:
        paths = tuple(
            sorted(
                (set(lifecycle) & set(cleanup)) | (set(cleanup) ^ set(observed)),
                key=path_byte_key,
            )
        )
        return Err(CleanupContractMismatch(paths))
    normalized = CleanupContract(lifecycle, cleanup, contract.fingerprint)
    return Ok(normalized)
