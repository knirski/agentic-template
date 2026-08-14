"""Generation-path recognition and maintenance-cleanup classification.

Covers T12 scaffold classification: ``recognize_generation`` two-way recognition
for absent manifests, strict ``decode_cleanup_inventory`` decoding, and
``classify_cleanup`` absent/invalid inventory outcomes.
"""

from __future__ import annotations

import unittest

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import MANIFEST_PATH
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.result import Err, Ok
from scripts.bootstrap.scaffold import (
    CLEANUP_SCHEMA_VERSION,
    MAINTENANCE_INVENTORY_PATH,
    SEED_ONCE_PATHS,
    CleanupEntryObservation,
    classify_cleanup,
    decode_cleanup_inventory,
    recognize_generation,
)
from scripts.bootstrap.state import (
    CleanupContractMismatch,
    CleanupContractValid,
    NoSnapshotCleanup,
)

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


class ScaffoldRecognitionTests(unittest.TestCase):
    def test_seed_once_observations_require_exact_slot_paths(self) -> None:
        with self.assertRaises(ValueError):
            _ = recognize_generation(copier_answers=None, seed_once={}, scaffold={})

    def test_scaffold_missing_a_seed_path_is_not_recognized(self) -> None:
        scaffold = _scaffold()
        _ = scaffold.pop(next(iter(scaffold)))
        self.assertIsNone(
            recognize_generation(
                copier_answers=None,
                seed_once=_seed_once(),
                scaffold=scaffold,
            )
        )

    def test_copier_scaffold_is_recognized_when_seeds_match(self) -> None:
        self.assertIs(
            recognize_generation(
                copier_answers=b"answers",
                seed_once=_seed_once(missing=RepoPath("README.md")),
                scaffold=_scaffold(),
            ),
            GenerationPath.COPIER,
        )

    def test_copier_scaffold_is_rejected_when_a_seed_differs(self) -> None:
        self.assertIsNone(
            recognize_generation(
                copier_answers=b"answers",
                seed_once=_seed_once(changed=RepoPath("README.md")),
                scaffold=_scaffold(),
            )
        )

    def test_github_scaffold_is_recognized_when_all_seeds_match(self) -> None:
        self.assertIs(
            recognize_generation(
                copier_answers=None,
                seed_once=_seed_once(),
                scaffold=_scaffold(),
            ),
            GenerationPath.GITHUB,
        )

    def test_github_scaffold_is_rejected_when_a_seed_is_absent(self) -> None:
        self.assertIsNone(
            recognize_generation(
                copier_answers=None,
                seed_once=_seed_once(missing=RepoPath("README.md")),
                scaffold=_scaffold(),
            )
        )


class CleanupInventoryTests(unittest.TestCase):
    def test_invalid_json_is_rejected(self) -> None:
        match decode_cleanup_inventory(b"{not json"):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("invalid JSON inventory decoded")

    def test_deeply_nested_inventory_is_rejected(self) -> None:
        payload = b"[" * 10000 + b"0" + b"]" * 10000
        match decode_cleanup_inventory(payload):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("deeply nested inventory decoded")

    def test_wrong_document_shape_is_rejected(self) -> None:
        match decode_cleanup_inventory(canonical_json({"schema_version": 1})):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("wrong-shape inventory decoded")

    def test_wrong_schema_version_is_rejected(self) -> None:
        payload = canonical_json({"schema_version": 2, "entries": []})
        match decode_cleanup_inventory(payload):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("future schema version decoded")

    def test_entries_not_a_list_is_rejected(self) -> None:
        payload = canonical_json({"schema_version": 1, "entries": {}})
        match decode_cleanup_inventory(payload):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("non-list entries decoded")

    def test_entry_with_extra_keys_is_rejected(self) -> None:
        payload = _inventory([_entry(extra=1)])
        match decode_cleanup_inventory(payload):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("extra-key entry decoded")

    def test_entry_field_violations_are_rejected(self) -> None:
        bad_path_entry: dict[str, object] = {
            "path": 5,
            "kind": "file",
            "sha256": DIGEST,
        }
        for entry in (
            _entry(kind="symlink"),
            _entry(digest="zzz"),
            bad_path_entry,
        ):
            with self.subTest(entry=entry):
                match decode_cleanup_inventory(_inventory([entry])):
                    case Err(error):
                        self.assertIsInstance(error, CleanupContractMismatch)
                    case Ok(_):
                        self.fail(f"invalid entry decoded: {entry}")

    def test_unsafe_entry_path_is_rejected(self) -> None:
        match decode_cleanup_inventory(_inventory([_entry(path="..")])):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("unsafe entry path decoded")

    def test_duplicate_entry_paths_are_rejected(self) -> None:
        payload = _inventory([_entry(), _entry()])
        match decode_cleanup_inventory(payload):
            case Err(error):
                self.assertIsInstance(error, CleanupContractMismatch)
            case Ok(_):
                self.fail("duplicate entry paths decoded")

    def test_administrative_paths_are_rejected(self) -> None:
        for path in (MANIFEST_PATH.value, MAINTENANCE_INVENTORY_PATH.value):
            with self.subTest(path=path):
                match decode_cleanup_inventory(_inventory([_entry(path=path)])):
                    case Err(error):
                        self.assertIsInstance(error, CleanupContractMismatch)
                    case Ok(_):
                        self.fail(f"administrative path decoded: {path}")

    def test_valid_inventory_decodes_sorted(self) -> None:
        payload = _inventory([_entry(path="z.txt"), _entry(path="a.txt")])
        match decode_cleanup_inventory(payload):
            case Ok(inventory):
                self.assertEqual(
                    tuple(entry[0].value for entry in inventory.entries),
                    ("a.txt", "z.txt"),
                )
            case Err(error):
                self.fail(f"valid inventory rejected: {error}")


class CleanupClassificationTests(unittest.TestCase):
    def test_absent_inventory_is_no_cleanup(self) -> None:
        self.assertIsInstance(
            classify_cleanup(inventory=None, observed={}), NoSnapshotCleanup
        )

    def test_invalid_inventory_is_a_mismatch(self) -> None:
        self.assertIsInstance(
            classify_cleanup(inventory=b"{", observed={}), CleanupContractMismatch
        )

    def test_matching_inventory_is_a_valid_contract(self) -> None:
        path = RepoPath("docs/api")
        inventory = _inventory([_entry(path=path.value, digest=DIGEST)])
        observed = {path: CleanupEntryObservation(path, True, "directory", DIGEST)}
        result = classify_cleanup(inventory=inventory, observed=observed)
        self.assertIsInstance(result, CleanupContractValid)
        if isinstance(result, CleanupContractValid):
            self.assertEqual(result.contract.cleanup_paths, (path,))


if __name__ == "__main__":
    _ = unittest.main()
