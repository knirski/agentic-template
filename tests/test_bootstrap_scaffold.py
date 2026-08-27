"""Generation-path recognition and maintenance-cleanup classification.

Covers T12 scaffold classification: ``recognize_generation`` two-way recognition
for absent manifests, strict ``decode_cleanup_inventory`` decoding, and
``classify_cleanup`` absent/invalid inventory outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from scripts.bootstrap.canonical_json import StrictJsonValue, canonical_json
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import MANIFEST_PATH
from scripts.bootstrap.observation import (
    _scaffold_bytes,  # pyright: ignore[reportPrivateUsage]  intentional scaffold fixture access
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.scaffold import (
    CLEANUP_SCHEMA_VERSION,
    MAINTENANCE_INVENTORY_PATH,
    SEED_ONCE_PATHS,
    SOURCE_OWNERSHIP_SCHEMA_VERSION,
    CleanupEntryObservation,
    classify_cleanup,
    decode_cleanup_inventory,
    decode_source_ownership,
    recognize_generation,
)
from scripts.bootstrap.state import (
    CleanupContractMismatch,
    CleanupContractValid,
    NoSnapshotCleanup,
)
from tests.fixtures import assert_err, assert_ok

DIGEST = "0" * 64


def _scaffold() -> dict[RepoPath, bytes]:
    return {path: b"content" for path in SEED_ONCE_PATHS}


def _seed_once(
    *, missing: RepoPath | None = None, changed: RepoPath | None = None
) -> dict[RepoPath, bytes | None]:
    seed: dict[RepoPath, bytes | None] = {path: b"content" for path in SEED_ONCE_PATHS}
    if missing is not None:
        seed[missing] = None
    if changed is not None:
        seed[changed] = b"other"
    return seed


def _inventory(entries: list[dict[str, object]]) -> bytes:
    return canonical_json(
        {"schema_version": CLEANUP_SCHEMA_VERSION, "entries": entries}
    )


def _entry(
    path: str = "docs/api",
    *,
    kind: str = "directory",
    digest: str = DIGEST,
    **extra: object,
) -> dict[str, object]:
    return {"path": path, "kind": kind, "sha256": digest, **extra}


def _source_payload(
    *,
    lifecycle_paths: object | None = None,
    snapshot_cleanup_paths: object | None = None,
) -> bytes:
    return canonical_json(
        {
            "schema_version": SOURCE_OWNERSHIP_SCHEMA_VERSION,
            "lifecycle_paths": cast(
                StrictJsonValue, [] if lifecycle_paths is None else lifecycle_paths
            ),
            "snapshot_cleanup_paths": cast(
                StrictJsonValue,
                [] if snapshot_cleanup_paths is None else snapshot_cleanup_paths,
            ),
        }
    )


def test_tracked_source_is_a_recognizable_github_scaffold() -> None:
    root = Path(__file__).resolve().parent.parent
    seed_once = {
        path: (
            (root / path.value).read_bytes() if (root / path.value).is_file() else None
        )
        for path in SEED_ONCE_PATHS
    }
    assert (
        recognize_generation(
            copier_answers=None,
            seed_once=seed_once,
            scaffold=_scaffold_bytes(str(root)),
        )
        is GenerationPath.GITHUB
    )


def test_seed_once_observations_require_exact_slot_paths() -> None:
    with pytest.raises(ValueError):
        recognize_generation(copier_answers=None, seed_once={}, scaffold={})


def test_scaffold_missing_a_seed_path_is_not_recognized() -> None:
    scaffold = _scaffold()
    _ = scaffold.pop(next(iter(scaffold)))
    assert (
        recognize_generation(
            copier_answers=None,
            seed_once=_seed_once(),
            scaffold=scaffold,
        )
        is None
    )


def test_copier_scaffold_is_recognized_when_seeds_match() -> None:
    assert (
        recognize_generation(
            copier_answers=b"answers",
            seed_once=_seed_once(missing=RepoPath("README.md")),
            scaffold=_scaffold(),
        )
        is GenerationPath.COPIER
    )


def test_copier_scaffold_is_rejected_when_a_seed_differs() -> None:
    assert (
        recognize_generation(
            copier_answers=b"answers",
            seed_once=_seed_once(changed=RepoPath("README.md")),
            scaffold=_scaffold(),
        )
        is None
    )


def test_github_scaffold_is_recognized_when_all_seeds_match() -> None:
    assert (
        recognize_generation(
            copier_answers=None,
            seed_once=_seed_once(),
            scaffold=_scaffold(),
        )
        is GenerationPath.GITHUB
    )


def test_github_scaffold_is_rejected_when_a_seed_is_absent() -> None:
    assert (
        recognize_generation(
            copier_answers=None,
            seed_once=_seed_once(missing=RepoPath("README.md")),
            scaffold=_scaffold(),
        )
        is None
    )


def test_invalid_json_is_rejected() -> None:
    error = assert_err(
        decode_cleanup_inventory(b"{not json"), "invalid JSON inventory decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_deeply_nested_inventory_is_rejected() -> None:
    payload = b"[" * 10000 + b"0" + b"]" * 10000
    error = assert_err(
        decode_cleanup_inventory(payload), "deeply nested inventory decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_wrong_document_shape_is_rejected() -> None:
    error = assert_err(
        decode_cleanup_inventory(canonical_json({"schema_version": 1})),
        "wrong-shape inventory decoded",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_wrong_schema_version_is_rejected() -> None:
    payload = canonical_json({"schema_version": 2, "entries": []})
    error = assert_err(
        decode_cleanup_inventory(payload), "future schema version decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_entries_not_a_list_is_rejected() -> None:
    payload = canonical_json({"schema_version": 1, "entries": {}})
    error = assert_err(decode_cleanup_inventory(payload), "non-list entries decoded")
    assert isinstance(error, CleanupContractMismatch)


def test_entry_with_extra_keys_is_rejected() -> None:
    payload = _inventory([_entry(extra=1)])
    error = assert_err(decode_cleanup_inventory(payload), "extra-key entry decoded")
    assert isinstance(error, CleanupContractMismatch)


@pytest.mark.parametrize(
    "entry",
    [
        _entry(kind="symlink"),
        _entry(digest="zzz"),
        {"path": 5, "kind": "file", "sha256": DIGEST},
    ],
    ids=["bad-kind", "bad-digest", "bad-path"],
)
def test_entry_field_violations_are_rejected(entry: dict[str, object]) -> None:
    error = assert_err(
        decode_cleanup_inventory(_inventory([entry])),
        f"invalid entry decoded: {entry}",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_unsafe_entry_path_is_rejected() -> None:
    error = assert_err(
        decode_cleanup_inventory(_inventory([_entry(path="..")])),
        "unsafe entry path decoded",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_duplicate_entry_paths_are_rejected() -> None:
    payload = _inventory([_entry(), _entry()])
    error = assert_err(
        decode_cleanup_inventory(payload), "duplicate entry paths decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


@pytest.mark.parametrize(
    "path",
    [MANIFEST_PATH.value, MAINTENANCE_INVENTORY_PATH.value],
    ids=["manifest", "maintenance"],
)
def test_administrative_paths_are_rejected(path: str) -> None:
    error = assert_err(
        decode_cleanup_inventory(_inventory([_entry(path=path)])),
        f"administrative path decoded: {path}",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_valid_inventory_decodes_sorted() -> None:
    payload = _inventory([_entry(path="z.txt"), _entry(path="a.txt")])
    inventory = assert_ok(decode_cleanup_inventory(payload))
    assert tuple(entry[0].value for entry in inventory.entries) == ("a.txt", "z.txt")


def test_wrong_document_shape_is_rejected_ownership() -> None:
    error = assert_err(
        decode_source_ownership(canonical_json({"schema_version": 1})),
        "wrong-shape ownership decoded",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_wrong_schema_version_is_rejected_ownership() -> None:
    payload = canonical_json(
        {
            "schema_version": 2,
            "lifecycle_paths": [],
            "snapshot_cleanup_paths": [],
        }
    )
    error = assert_err(
        decode_source_ownership(payload), "future schema version decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_non_list_paths_are_rejected() -> None:
    payload = _source_payload(  # type: ignore[arg-type]
        lifecycle_paths="tests"
    )
    error = assert_err(decode_source_ownership(payload), "non-list paths decoded")
    assert isinstance(error, CleanupContractMismatch)


@pytest.mark.parametrize(
    "paths",
    [["tests", 5], [".."], ["tests", "tests"]],
    ids=["non-list-entry", "unsafe", "duplicate"],
)
def test_invalid_path_entries_are_rejected(paths: list[object]) -> None:
    payload = _source_payload(lifecycle_paths=paths)  # type: ignore[arg-type]
    error = assert_err(
        decode_source_ownership(payload),
        f"invalid paths decoded: {paths}",
    )
    assert isinstance(error, CleanupContractMismatch)


@pytest.mark.parametrize(
    "path",
    [
        MANIFEST_PATH.value,
        MAINTENANCE_INVENTORY_PATH.value,
        ".rygor/state.json",
        ".git/config",
    ],
    ids=["manifest", "maintenance", "state-root", "git-config"],
)
def test_administrative_paths_are_rejected_ownership(path: str) -> None:
    payload = _source_payload(lifecycle_paths=[path])
    error = assert_err(
        decode_source_ownership(payload),
        f"administrative path decoded: {path}",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_valid_ownership_decodes_sorted() -> None:
    payload = _source_payload(lifecycle_paths=["z.txt", "a.txt"])
    ownership = assert_ok(decode_source_ownership(payload))
    assert tuple(path.value for path in ownership.lifecycle_paths) == ("a.txt", "z.txt")


def test_overlapping_ownership_sets_are_rejected() -> None:
    payload = _source_payload(
        lifecycle_paths=["docs/api"], snapshot_cleanup_paths=["docs/api"]
    )
    error = assert_err(
        decode_source_ownership(payload), "overlapping ownership decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_nested_ownership_sets_are_rejected() -> None:
    payload = _source_payload(
        lifecycle_paths=["docs"], snapshot_cleanup_paths=["docs/api"]
    )
    error = assert_err(decode_source_ownership(payload), "nested ownership decoded")
    assert isinstance(error, CleanupContractMismatch)


def test_case_colliding_paths_are_rejected() -> None:
    payload = _source_payload(lifecycle_paths=["Docs/API", "docs/api"])
    error = assert_err(
        decode_source_ownership(payload), "case-colliding ownership decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


@pytest.mark.parametrize(
    "path",
    [
        *SEED_ONCE_PATHS,
        RepoPath("LICENSE"),
        RepoPath("NOTICE.md"),
        RepoPath("LICENSES/Apache-2.0.txt"),
    ],
    ids=lambda p: p.value if isinstance(p, RepoPath) else str(p),
)
def test_seed_and_legal_paths_are_rejected(path: RepoPath) -> None:
    payload = _source_payload(lifecycle_paths=[path.value])
    error = assert_err(
        decode_source_ownership(payload),
        f"seed or legal path decoded: {path.value}",
    )
    assert isinstance(error, CleanupContractMismatch)


def test_case_variant_nested_paths_are_rejected_across_namespaces() -> None:
    payload = _source_payload(
        lifecycle_paths=["Docs"], snapshot_cleanup_paths=["docs/api"]
    )
    error = assert_err(
        decode_source_ownership(payload), "case-variant nested ownership decoded"
    )
    assert isinstance(error, CleanupContractMismatch)


def test_absent_inventory_is_no_cleanup() -> None:
    assert isinstance(
        classify_cleanup(inventory=None, observed={}, declared_cleanup_paths=()),
        NoSnapshotCleanup,
    )


def test_invalid_inventory_is_a_mismatch() -> None:
    assert isinstance(
        classify_cleanup(inventory=b"{", observed={}, declared_cleanup_paths=()),
        CleanupContractMismatch,
    )


def test_matching_inventory_is_a_valid_contract() -> None:
    path = RepoPath("docs/api")
    inventory = _inventory([_entry(path=path.value, digest=DIGEST)])
    observed = {path: CleanupEntryObservation(path, True, "directory", DIGEST)}
    result = classify_cleanup(
        inventory=inventory,
        observed=observed,
        declared_cleanup_paths=(path,),
    )
    assert isinstance(result, CleanupContractValid)
    if isinstance(result, CleanupContractValid):
        assert result.contract.cleanup_paths == (path,)


@pytest.mark.parametrize(
    "declared",
    [(RepoPath("tests"),), (RepoPath("docs/api"), RepoPath("tests"))],
    ids=["missing-extra", "extra-missing"],
)
def test_declared_set_disagreement_is_a_mismatch(
    declared: tuple[RepoPath, ...],
) -> None:
    path = RepoPath("docs/api")
    inventory = _inventory([_entry(path=path.value, digest=DIGEST)])
    observed = {path: CleanupEntryObservation(path, True, "directory", DIGEST)}
    result = classify_cleanup(
        inventory=inventory,
        observed=observed,
        declared_cleanup_paths=declared,
    )
    assert isinstance(result, CleanupContractMismatch)
    if isinstance(result, CleanupContractMismatch):
        assert RepoPath("tests") in result.paths
