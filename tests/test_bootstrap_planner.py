"""Tests for the candidate manifest, complete initial planner, and plan digest."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Literal, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.identity import (
    DirectoryState,
    FileEntry,
    FileState,
    PosixMode,
    content_identity,
    file_state_identity,
    sha256_hex,
    tagged_digest,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import (
    MANIFEST_PATH,
    CandidateManifest,
    LicensingRecord,
    MaintenanceRecord,
    ManagedInventory,
    ManagedInventoryEntry,
    ManifestAdditions,
    ManifestAnswers,
    ManifestErrorKind,
    ProfileSelection,
    ProjectFacts,
    ProvenanceRecord,
    SlotContent,
    build_candidate_manifest,
    decode_manifest,
    encode_manifest,
    manifest_checksum,
    manifest_document,
    path_within_limits,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import (
    ReceiptErrorKind,
    build_receipt,
    decode_receipt,
    encode_receipt,
    plan_receipt_digest,
    reconstruct_plan,
)
from scripts.bootstrap.planner import (
    MAINTENANCE_INVENTORY_PATH,
    SLOT_PLACEHOLDER_RULES,
    CleanMaintenance,
    CompileError,
    CompileErrorKind,
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    DirectoryAbsent,
    ExpectedGatePass,
    ExpectedGateRefusal,
    MaintenanceDecision,
    ObservedDirectoryEntry,
    ObservedFileEntry,
    OperationPlan,
    PlanInvariantErrorKind,
    PlannedDirectoryEntry,
    PlannedFileEntry,
    PlannedFilePresent,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    RetainMaintenance,
    SeedOnceInput,
    TargetSnapshot,
    apply_plan,
    compile_initial_plan,
    evaluate_expected,
    evaluate_slot_readiness,
    legal_output_paths,
    predicted_placeholder_findings,
)
from scripts.bootstrap.readiness import (
    Finding,
    Repository,
)
from scripts.bootstrap.render import (
    ManagedFile,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import (
    PROJECT_VALIDATION_PATH,
    PROJECT_VALIDATION_SCAFFOLD,
    SEED_ONCE_PATHS,
    SEED_ONCE_SLOTS,
)
from scripts.bootstrap.source_baseline import (
    AdoptedSourceBaseline,
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
    template_source_fingerprint,
)
from scripts.bootstrap.state import CleanupContract
from scripts.bootstrap.template_contract import REQUIRED_FILES, REQUIRED_SKILLS
from scripts.bootstrap.values import DEFAULT_LIMITS, ResourceLimits

SLOT_CONTENTS: dict[str, bytes] = {
    "readme": b"# Example\n\nReal project description.\n",
    "prd": b"<!-- rygor:placeholder:prd -->\n# Product\n",
    "security_policy": b"<!-- rygor:placeholder:security -->\n",
    "contributing": b"<!-- rygor:placeholder:contributing -->\n",
    "validation_hook": b"#!/usr/bin/env python3\nrygor:unconfigured:validate-project\n",
    "project_validation": PROJECT_VALIDATION_SCAFFOLD,
}
APACHE_TEXT = b"Apache License\nVersion 2.0, January 2004\n"
LEGAL_CONTENTS: dict[str, dict[str, bytes]] = {
    "retain-apache-2.0": {
        "LICENSE": APACHE_TEXT,
        "NOTICE.md": b"# Notices\n\nBundled skills are covered by their upstream licences.\n",
    },
    "provided-project-license": {
        "LICENSE": b"Adopter license text.\n",
        "NOTICE.md": b"# Notices\n\nBundled skills are covered by their upstream licences.\n",
        "LICENSES/Apache-2.0.txt": APACHE_TEXT,
    },
    "private": {
        "LICENSE": b"Private project terms.\n",
        "NOTICE.md": b"# Notices\n\nBundled skills are covered by their upstream licences.\n",
        "LICENSES/Apache-2.0.txt": APACHE_TEXT,
    },
}
MANAGED_CONTENTS: tuple[tuple[str, Literal["text", "binary"], bytes], ...] = (
    ("pyproject.toml", "text", b'[project]\nname = "example"\n'),
    (".github/workflows/ci.yml", "text", b"name: ci\njobs: {}\n"),
    ("docs/template-updates.md", "text", b"# Template updates\n"),
)
CLEANUP_PATHS = (RepoPath("tests"), RepoPath("uv.lock"), RepoPath("docs/specs"))
SOURCE_CI = b"name: source-ci\njobs: {}\n"
SOURCE_PYPROJECT = b'[project]\nname = "rygor"\n'
INVENTORY = b'{"schema_version": 1, "entries": []}\n'
TARGET = target_identity(b"/work/example", device=1, inode=2)


def slot_paths() -> dict[str, RepoPath]:
    return dict(SEED_ONCE_SLOTS)


def intern_all(
    store: VerifiedBlobStore, contents: dict[str, bytes]
) -> tuple[VerifiedBlobStore, dict[str, ContentId]]:
    content_ids: dict[str, ContentId] = {}
    for key, content in contents.items():
        match store.intern(content):
            case Ok((content_id, updated)):
                content_ids[key] = content_id
                store = updated
            case Err(error):
                raise AssertionError(f"intern failed: {error}")
    return store, content_ids


def fixture_answers(
    *,
    licensing_mode: str = "retain-apache-2.0",
    file_slots: tuple[str, ...] = ("readme",),
    profile_requested: tuple[str, ...] = (),
) -> ManifestAnswers:
    slots: dict[str, SlotContent] = {}
    for rule in SLOT_PLACEHOLDER_RULES:
        if rule.slot in file_slots:
            slots[rule.slot] = SlotContent(
                mode="file", content_sha256=sha256_hex(SLOT_CONTENTS[rule.slot])
            )
        else:
            slots[rule.slot] = SlotContent(mode="scaffold", content_sha256=None)
    slots["project_validation"] = SlotContent(mode="scaffold", content_sha256=None)
    legal = LEGAL_CONTENTS[licensing_mode]
    return ManifestAnswers(
        project=ProjectFacts(name="example", default_branch="main"),
        profile=ProfileSelection(id="portable", requested=profile_requested),
        settings=MappingProxyType({}),
        licensing=LicensingRecord(
            mode=licensing_mode,
            content_sha256=(
                None
                if licensing_mode == "retain-apache-2.0"
                else sha256_hex(legal["LICENSE"])
            ),
        ),
        slots=MappingProxyType(slots),
    )


def fixture_seed_bytes(licensing_mode: str) -> dict[str, bytes]:
    contents = {
        rule.path.value: SLOT_CONTENTS[rule.slot] for rule in SLOT_PLACEHOLDER_RULES
    }
    contents[PROJECT_VALIDATION_PATH.value] = PROJECT_VALIDATION_SCAFFOLD
    contents.update(LEGAL_CONTENTS[licensing_mode])
    return contents


def fixture_seed_once(
    store: VerifiedBlobStore, licensing_mode: str
) -> tuple[VerifiedBlobStore, tuple[SeedOnceInput, ...]]:
    contents = fixture_seed_bytes(licensing_mode)
    store, content_ids = intern_all(store, contents)
    inputs: list[SeedOnceInput] = []
    for path_value, _content in contents.items():
        kind = "binary" if path_value == "scripts/validate-project" else "text"
        mode = (
            PosixMode.EXECUTABLE
            if path_value == "scripts/validate-project"
            else PosixMode.FILE
        )
        inputs.append(
            SeedOnceInput(
                path=RepoPath(path_value),
                kind=kind,
                mode=mode,
                content_id=content_ids[path_value],
            )
        )
    return store, tuple(
        sorted(inputs, key=lambda seed: seed.path.value.encode("utf-8"))
    )


def observed_file(
    path: RepoPath, content: bytes, *, mode: PosixMode = PosixMode.FILE
) -> ObservedFileEntry:
    return ObservedFileEntry(
        path=path,
        state=file_state_identity(content, text=True, mode=mode),
        content=content,
    )


def observed_directory(
    path: RepoPath, children: tuple[tuple[RepoPath, bytes], ...] = ()
) -> ObservedDirectoryEntry:
    entries = tuple(
        FileEntry(child_path, content, PosixMode.FILE)
        for child_path, content in children
    )
    return ObservedDirectoryEntry(
        path=path, state=DirectoryState(PosixMode.DIRECTORY, entries)
    )


def fixture_source_entries() -> tuple[LifecycleSourceEntry, ...]:
    return (
        LifecycleSourceEntry(
            path=RepoPath("scripts/bootstrap/__init__.py"),
            kind="file",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"present\n"),
        ),
        LifecycleSourceEntry(
            path=RepoPath("scripts/bootstrap/render.py"),
            kind="file",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"present\n"),
        ),
    )


def fixture_cleanup() -> CleanupContract:
    return CleanupContract(
        lifecycle_paths=(
            RepoPath("scripts/bootstrap/__init__.py"),
            RepoPath("scripts/bootstrap/render.py"),
        ),
        cleanup_paths=CLEANUP_PATHS,
        fingerprint=sha256_hex(b"cleanup"),
    )


def fixture_managed() -> tuple[ManagedFile, ...]:
    return tuple(
        sorted(
            (
                ManagedFile(
                    path=RepoPath(path), kind=kind, mode=PosixMode.FILE, content=content
                )
                for path, kind, content in MANAGED_CONTENTS
            ),
            key=lambda file: file.path.value.encode("utf-8"),
        )
    )


def _contract_entries() -> tuple[ObservedFileEntry, ...]:
    """Observed lifecycle files; seed and managed paths are supplied by their own classes."""
    skip = {path.value for path in SEED_ONCE_PATHS} | {
        path for path, _kind, _content in MANAGED_CONTENTS
    }
    files: list[ObservedFileEntry] = []
    for path in REQUIRED_FILES:
        if path in skip:
            continue
        files.append(observed_file(RepoPath(path), b"present\n"))
    for skill in REQUIRED_SKILLS:
        path = f".agents/skills/{skill}/SKILL.md"
        files.append(
            observed_file(
                RepoPath(path),
                f"---\nname: {skill}\ndescription: valid\n---\n".encode(),
            )
        )
    return tuple(files)


def _sorted_snapshot(
    files: tuple[ObservedFileEntry, ...],
    directories: tuple[ObservedDirectoryEntry, ...],
) -> TargetSnapshot:
    return TargetSnapshot(
        files=tuple(sorted(files, key=lambda entry: entry.path.value.encode("utf-8"))),
        directories=tuple(
            sorted(directories, key=lambda entry: entry.path.value.encode("utf-8"))
        ),
    )


def fixture_github_snapshot(*, licensing_mode: str) -> TargetSnapshot:
    """Observed GitHub scaffold: seed scaffolds, cleanup targets, and lifecycle files."""
    seed_contents = fixture_seed_bytes(licensing_mode)
    files: list[ObservedFileEntry] = [
        observed_file(
            RepoPath(path_value),
            content,
            mode=(
                PosixMode.EXECUTABLE
                if path_value == "scripts/validate-project"
                else PosixMode.FILE
            ),
        )
        for path_value, content in seed_contents.items()
    ]
    for path_value, _kind, content in MANAGED_CONTENTS:
        observed = (
            SOURCE_PYPROJECT
            if path_value == "pyproject.toml"
            else SOURCE_CI
            if path_value == ".github/workflows/ci.yml"
            else content
        )
        files.append(observed_file(RepoPath(path_value), observed))
    files.append(observed_file(RepoPath("uv.lock"), b"lockfile\n"))
    files.append(observed_file(RepoPath("tests/test_a.py"), b"def test_a(): pass\n"))
    files.append(
        observed_file(RepoPath("tests/sub/test_b.py"), b"def test_b(): pass\n")
    )
    files.append(observed_file(RepoPath("docs/specs/archive.md"), b"# Archived spec\n"))
    files.append(observed_file(MAINTENANCE_INVENTORY_PATH, INVENTORY))
    files.extend(_contract_entries())
    directories = [
        observed_directory(RepoPath(".rygor")),
        observed_directory(RepoPath("docs")),
        observed_directory(RepoPath("docs/agents")),
        observed_directory(RepoPath(".github")),
        observed_directory(RepoPath(".github/workflows")),
        observed_directory(RepoPath("scripts")),
        observed_directory(RepoPath("scripts/bootstrap")),
        observed_directory(
            RepoPath("tests"),
            (
                (RepoPath("tests/test_a.py"), b"def test_a(): pass\n"),
                (RepoPath("tests/sub"), b""),
            ),
        ),
        observed_directory(
            RepoPath("tests/sub"),
            ((RepoPath("tests/sub/test_b.py"), b"def test_b(): pass\n"),),
        ),
        observed_directory(
            RepoPath("docs/specs"),
            ((RepoPath("docs/specs/archive.md"), b"# Archived spec\n"),),
        ),
    ]
    return _sorted_snapshot(tuple(files), tuple(directories))


def fixture_copier_snapshot() -> TargetSnapshot:
    """Observed Copier target: lifecycle files only; seed and managed paths are absent."""
    directories = [
        observed_directory(RepoPath("scripts")),
        observed_directory(RepoPath("scripts/bootstrap")),
        observed_directory(RepoPath(".github")),
        observed_directory(RepoPath(".github/workflows")),
        observed_directory(RepoPath("docs/agents")),
    ]
    return _sorted_snapshot(_contract_entries(), tuple(directories))


def compile_fixture(
    *,
    generation: GenerationPath = GenerationPath.GITHUB,
    answers: ManifestAnswers | None = None,
    additions: ManifestAdditions | None = None,
    snapshot: TargetSnapshot | None = None,
    cleanup: CleanupContract | None = None,
    maintenance: MaintenanceDecision | None = None,
    seed_once: tuple[SeedOnceInput, ...] | None = None,
    managed: tuple[ManagedFile, ...] | None = None,
    blobs: VerifiedBlobStore | None = None,
    snapshot_commit: str | None = "0" * 40,
    limits: ResourceLimits | None = None,
    collisions: Mapping[str, Literal["keep-existing", "replace"]] | None = None,
    lifecycle: tuple[ManagedFile, ...] | None = None,
) -> tuple[VerifiedBlobStore, Result[OperationPlan, CompileError]]:
    """Return (input blob store, compile result) for a fixture with optional overrides."""
    licensing_mode = (
        answers.licensing.mode if answers is not None else "retain-apache-2.0"
    )
    seed_store = VerifiedBlobStore.empty()
    if seed_once is None:
        seed_store, seed_once = fixture_seed_once(seed_store, licensing_mode)
    if managed is None:
        managed = fixture_managed()
    if answers is None:
        answers = fixture_answers(licensing_mode=licensing_mode)
    if snapshot is None:
        snapshot = fixture_github_snapshot(licensing_mode=licensing_mode)
    if generation is GenerationPath.GITHUB and cleanup is None:
        cleanup = fixture_cleanup()
    if maintenance is None:
        maintenance = CleanMaintenance()
    if blobs is None:
        blobs = seed_store
    result = compile_initial_plan(
        generation=generation,
        target_identity=TARGET,
        answers=answers,
        additions=additions if additions is not None else ManifestAdditions(),
        seed_once=seed_once,
        managed=managed,
        blobs=blobs,
        source_entries=fixture_source_entries(),
        snapshot_commit=snapshot_commit,
        maintenance=maintenance,
        cleanup=cleanup,
        snapshot=snapshot,
        limits=limits if limits is not None else DEFAULT_LIMITS,
        collisions=collisions,
        lifecycle=lifecycle if lifecycle is not None else (),
    )
    return blobs, result


def get_plan(result: Result[OperationPlan, CompileError]) -> OperationPlan:
    assert isinstance(result, Ok), f"expected a compiled plan, got {result}"
    return result.value


def _operation_by_kind(receipt: dict[str, object], kind: str) -> dict[str, object]:
    operations = receipt["operations"]
    assert isinstance(operations, list)
    operations = cast(list[object], operations)
    for operation in operations:
        assert isinstance(operation, dict)
        operation = cast(dict[str, object], operation)
        if operation.get("kind") == kind:
            return operation
    raise AssertionError(f"no {kind} operation in receipt")


def _copier_receipt() -> dict[str, object]:
    _, result = compile_fixture(
        generation=GenerationPath.COPIER,
        snapshot=fixture_copier_snapshot(),
        cleanup=None,
        snapshot_commit=None,
    )
    return build_receipt(get_plan(result))


def _adopted_receipt() -> dict[str, object]:
    _, result = compile_fixture(
        generation=GenerationPath.ADOPTED,
        snapshot_commit="0" * 40,
    )
    return build_receipt(get_plan(result))


def _set_delete_planned_new(receipt: dict[str, object]) -> None:
    delete = _operation_by_kind(receipt, "delete_file")
    create = _operation_by_kind(receipt, "create_file")
    delete["planned_new"] = create["planned_new"]


def _receipt_with_tree_extra_key() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    planned_new["extra"] = 1
    return receipt


def _receipt_with_tree_expected_old() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    tree["expected_old"] = {}
    return receipt


def _receipt_with_tree_planned_new_type() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    tree["planned_new"] = "x"
    return receipt


def _receipt_with_tree_entry_bad_mode() -> dict[str, object]:
    receipt = _nested_copier_receipt()
    _directory_entry(receipt)["mode"] = 420
    return receipt


def _receipt_with_tree_entry_missing_key() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    entries = planned_new["entries"]
    assert isinstance(entries, list) and entries
    entries = cast(list[object], entries)
    entry = entries[0]
    assert isinstance(entry, dict)
    entry = cast(dict[str, object], entry)
    _ = entry.pop("path")
    return receipt


def _receipt_with_tree_entry_bad_digest() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    entries = planned_new["entries"]
    assert isinstance(entries, list)
    entries = cast(list[object], entries)
    for entry in entries:
        assert isinstance(entry, dict)
        entry = cast(dict[str, object], entry)
        if entry.get("kind") == "file":
            entry["content_id"] = "zzz"
            return receipt
    raise AssertionError("no file entry in tree")


def _receipt_with_tree_extra_op_key() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    tree["extra"] = 1
    return receipt


def _receipt_with_tree_bad_root() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    tree["root"] = ".."
    return receipt


def _receipt_with_tree_bad_sha() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    planned_new["raw_tree_sha256"] = "zzz"
    return receipt


def _receipt_with_tree_entry_not_mapping() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    entries = planned_new["entries"]
    assert isinstance(entries, list) and entries
    entries = cast(list[object], entries)
    entries[0] = "x"
    return receipt


def _nested_copier_receipt() -> dict[str, object]:
    snapshot = fixture_copier_snapshot()
    managed = tuple(
        sorted(
            (
                *fixture_managed(),
                ManagedFile(
                    path=RepoPath("docs/api/ref.md"),
                    kind="text",
                    mode=PosixMode.FILE,
                    content=b"# API\n",
                ),
            ),
            key=lambda file: file.path.value.encode("utf-8"),
        )
    )
    _, result = compile_fixture(
        generation=GenerationPath.COPIER,
        snapshot=snapshot,
        cleanup=None,
        snapshot_commit=None,
        managed=managed,
    )
    return build_receipt(get_plan(result))


def _directory_entry(receipt: dict[str, object]) -> dict[str, object]:
    operations = receipt["operations"]
    assert isinstance(operations, list)
    operations = cast(list[object], operations)
    for tree in operations:
        assert isinstance(tree, dict)
        tree = cast(dict[str, object], tree)
        if tree.get("kind") != "create_tree":
            continue
        planned_new = tree["planned_new"]
        assert isinstance(planned_new, dict)
        planned_new = cast(dict[str, object], planned_new)
        entries = planned_new["entries"]
        assert isinstance(entries, list)
        entries = cast(list[object], entries)
        for entry in entries:
            assert isinstance(entry, dict)
            entry = cast(dict[str, object], entry)
            if entry.get("kind") == "directory":
                return entry
    raise AssertionError("no directory entry in tree")


def _file_entry(receipt: dict[str, object]) -> dict[str, object]:
    operations = receipt["operations"]
    assert isinstance(operations, list)
    operations = cast(list[object], operations)
    for tree in operations:
        assert isinstance(tree, dict)
        tree = cast(dict[str, object], tree)
        if tree.get("kind") != "create_tree":
            continue
        planned_new = tree["planned_new"]
        assert isinstance(planned_new, dict)
        planned_new = cast(dict[str, object], planned_new)
        entries = planned_new["entries"]
        assert isinstance(entries, list)
        entries = cast(list[object], entries)
        for entry in entries:
            assert isinstance(entry, dict)
            entry = cast(dict[str, object], entry)
            if entry.get("kind") == "file":
                return entry
    raise AssertionError("no file entry in tree")


def _receipt_with_tree_dir_entry_bad_path() -> dict[str, object]:
    receipt = _nested_copier_receipt()
    _directory_entry(receipt)["path"] = ".."
    return receipt


def _receipt_with_tree_entry_bad_kind() -> dict[str, object]:
    receipt = _nested_copier_receipt()
    _directory_entry(receipt)["kind"] = "symlink"
    return receipt


def _receipt_with_tree_file_entry_bad_kind() -> dict[str, object]:
    receipt = _nested_copier_receipt()
    _file_entry(receipt)["file_kind"] = "other"
    return receipt


def _receipt_with_tree_dir_entry_missing_mode() -> dict[str, object]:
    receipt = _nested_copier_receipt()
    _ = _directory_entry(receipt).pop("mode")
    return receipt


def _receipt_with_tree_file_entry_bad_path() -> dict[str, object]:
    receipt = _copier_receipt()
    _file_entry(receipt)["path"] = ".."
    return receipt


def _receipt_with_tree_file_entry_missing_id() -> dict[str, object]:
    receipt = _copier_receipt()
    _ = _file_entry(receipt).pop("content_id")
    return receipt


def _receipt_with_remove_empty_extra_key() -> dict[str, object]:
    receipt = build_receipt(github_plan())
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    remove["extra"] = 1
    return receipt


def _receipt_with_remove_empty_bad_path() -> dict[str, object]:
    receipt = build_receipt(github_plan())
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    remove["path"] = ".."
    return receipt


def _receipt_with_remove_empty_old_type() -> dict[str, object]:
    receipt = build_receipt(github_plan())
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    remove["expected_old"] = "x"
    return receipt


def _receipt_with_remove_empty_old_mode_type() -> dict[str, object]:
    receipt = build_receipt(github_plan())
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    expected_old = remove["expected_old"]
    assert isinstance(expected_old, dict)
    expected_old = cast(dict[str, object], expected_old)
    expected_old["mode"] = "x"
    return receipt


def _receipt_with_tree_entry_extra_key() -> dict[str, object]:
    receipt = _copier_receipt()
    tree = _operation_by_kind(receipt, "create_tree")
    planned_new = tree["planned_new"]
    assert isinstance(planned_new, dict)
    planned_new = cast(dict[str, object], planned_new)
    entries = planned_new["entries"]
    assert isinstance(entries, list) and entries
    entries = cast(list[object], entries)
    entry = entries[0]
    assert isinstance(entry, dict)
    entry = cast(dict[str, object], entry)
    entry["extra"] = 1
    return receipt


def _set_remove_empty_planned_new(receipt: dict[str, object]) -> None:
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    remove["planned_new"] = {"mode": 493}


def _set_remove_empty_bad_mode(receipt: dict[str, object]) -> None:
    remove = _operation_by_kind(receipt, "remove_empty_directory")
    expected_old = remove["expected_old"]
    assert isinstance(expected_old, dict)
    expected_old = cast(dict[str, object], expected_old)
    expected_old["mode"] = 0o7777 + 1


def github_plan() -> OperationPlan:
    _, result = compile_fixture()
    return get_plan(result)


def github_snapshot() -> TargetSnapshot:
    return fixture_github_snapshot(licensing_mode="retain-apache-2.0")


def _manifest_answers_missing(document: dict[str, object]) -> object:
    return document.pop("answers")


def _manifest_project_name(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["project"]).__setitem__("name", "bad name")


def _manifest_default_branch(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["project"]).__setitem__(
        "default_branch", "bad branch"
    )


def _manifest_profile_id(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["profile"]).__setitem__("id", "Bad")


def _manifest_profile_requested_unsorted(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["profile"]).__setitem__(
        "requested", ["nix", "cachix-publish"]
    )


def _manifest_settings_capability_id(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["settings"]).__setitem__("Bad", {})


def _manifest_settings_name(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["settings"]).__setitem__(
        "nix", {"bad-name": "x"}
    )


def _manifest_settings_value(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["settings"]).__setitem__(
        "nix", {"cache_name": 5}
    )


def _manifest_licensing_mode(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["licensing"]).__setitem__("mode", "other")


def _manifest_licensing_digest(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["licensing"]).__setitem__(
        "content_sha256", "zzz"
    )


def _manifest_slot_mode(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    slots = cast(dict[str, object], answers["slots"])
    return cast(dict[str, object], slots["readme"]).__setitem__("mode", "other")


def _manifest_slot_digest(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    slots = cast(dict[str, object], answers["slots"])
    return cast(dict[str, object], slots["readme"]).__setitem__("content_sha256", "zzz")


def _manifest_unknown_slot(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["slots"]).__setitem__(
        "unknown", {"mode": "file", "content_sha256": None}
    )


def _manifest_additions_unsorted(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["additions"]).__setitem__(
        "requested", ["nix", "cachix-publish"]
    )


def _manifest_additions_settings(document: dict[str, object]) -> object:
    additions = cast(dict[str, object], document["additions"])
    return cast(dict[str, object], additions["settings"]).__setitem__("Bad", {})


def _manifest_generation_path(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["provenance"]).__setitem__(
        "generation_path", "other"
    )


def _manifest_maintenance_status(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["maintenance"]).__setitem__(
        "status", "other"
    )


def _manifest_retained_paths_unsafe(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["maintenance"]).__setitem__(
        "retained_paths", [".."]
    )


def _manifest_baseline_kind(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "kind", "other"
    )


def _manifest_baseline_fingerprint(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "fingerprint", "zzz"
    )


def _manifest_baseline_fingerprint_mismatch(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    baseline = cast(dict[str, object], provenance["source_baseline"])
    return baseline.__setitem__("fingerprint", "0" * 64)


def _manifest_baseline_entries_unsorted(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    baseline = cast(dict[str, object], provenance["source_baseline"])
    entries = cast(list[object], baseline["entries"])
    return baseline.__setitem__("entries", list(reversed(entries)))


def _manifest_baseline_entries_unsafe_path(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "entries",
        [
            {
                "path": "..",
                "kind": "file",
                "mode": 420,
                "sha256": "0" * 64,
            }
        ],
    )


def _manifest_baseline_missing_snapshot_commit(
    document: dict[str, object],
) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    baseline = cast(dict[str, object], provenance["source_baseline"])
    return baseline.pop("snapshot_commit")


def _manifest_baseline_bad_snapshot_commit(
    document: dict[str, object],
) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "snapshot_commit", "zzz"
    )


def _manifest_baseline_kind_mismatch(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "kind", "copier"
    )


def _manifest_managed_unsorted(document: dict[str, object]) -> object:
    return document.__setitem__(
        "managed",
        [
            {"path": "z.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
            {"path": "a.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
        ],
    )


def _manifest_managed_case_collision(document: dict[str, object]) -> object:
    return document.__setitem__(
        "managed",
        [
            {"path": "A.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
            {"path": "a.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
        ],
    )


def _manifest_profile_requested_not_list(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["profile"]).__setitem__("requested", "x")


def _manifest_project_name_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["project"]).__setitem__("name", 5)


def _manifest_profile_id_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["profile"]).__setitem__("id", 5)


def _manifest_licensing_mode_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["licensing"]).__setitem__("mode", 5)


def _manifest_licensing_digest_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["licensing"]).__setitem__(
        "content_sha256", 5
    )


def _manifest_slot_mode_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    slots = cast(dict[str, object], answers["slots"])
    return cast(dict[str, object], slots["readme"]).__setitem__("mode", 5)


def _manifest_slot_digest_not_string(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    slots = cast(dict[str, object], answers["slots"])
    return cast(dict[str, object], slots["readme"]).__setitem__("content_sha256", 5)


def _manifest_slot_not_mapping(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["slots"]).__setitem__("readme", "x")


def _manifest_settings_not_mapping(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return answers.__setitem__("settings", "x")


def _manifest_settings_values_not_mapping(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["settings"]).__setitem__("nix", "x")


def _manifest_project_not_mapping(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return answers.__setitem__("project", "x")


def _manifest_licensing_not_mapping(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return answers.__setitem__("licensing", "x")


def _manifest_additions_requested_not_list(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["additions"]).__setitem__("requested", "x")


def _manifest_generation_path_not_string(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["provenance"]).__setitem__(
        "generation_path", 5
    )


def _manifest_maintenance_not_mapping(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["provenance"]).__setitem__(
        "maintenance", "x"
    )


def _manifest_retained_paths_not_list(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["maintenance"]).__setitem__(
        "retained_paths", "x"
    )


def _manifest_baseline_not_mapping(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["provenance"]).__setitem__(
        "source_baseline", "x"
    )


def _manifest_baseline_entries_not_list(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "entries", "x"
    )


def _manifest_managed_not_list(document: dict[str, object]) -> object:
    return document.__setitem__("managed", "x")


def _manifest_managed_entry_path_not_string(document: dict[str, object]) -> object:
    return document.__setitem__(
        "managed",
        [
            {"path": 5, "kind": "text", "mode": 420, "sha256": "0" * 64},
        ],
    )


def _manifest_managed_duplicate_entries(document: dict[str, object]) -> object:
    return document.__setitem__(
        "managed",
        [
            {"path": "a.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
            {"path": "a.txt", "kind": "text", "mode": 420, "sha256": "0" * 64},
        ],
    )


def _manifest_answers_extra_key(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["answers"]).__setitem__("junk_key", True)


def _manifest_project_extra_key(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["project"]).__setitem__("junk_key", True)


def _manifest_profile_extra_key(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["profile"]).__setitem__("junk_key", True)


def _manifest_licensing_extra_key(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    return cast(dict[str, object], answers["licensing"]).__setitem__("junk_key", True)


def _manifest_slot_content_extra_key(document: dict[str, object]) -> object:
    answers = cast(dict[str, object], document["answers"])
    slots = cast(dict[str, object], answers["slots"])
    return cast(dict[str, object], slots["readme"]).__setitem__("junk_key", True)


def _manifest_additions_extra_key(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["additions"]).__setitem__("junk_key", True)


def _manifest_provenance_extra_key(document: dict[str, object]) -> object:
    return cast(dict[str, object], document["provenance"]).__setitem__("junk_key", True)


def _manifest_maintenance_extra_key(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["maintenance"]).__setitem__(
        "junk_key", True
    )


def _manifest_baseline_extra_key(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    return cast(dict[str, object], provenance["source_baseline"]).__setitem__(
        "junk_key", True
    )


def _manifest_managed_entry_extra_key(document: dict[str, object]) -> object:
    return document.__setitem__(
        "managed",
        [
            {
                "path": "a.txt",
                "kind": "text",
                "mode": 420,
                "sha256": "0" * 64,
                "junk_key": True,
            }
        ],
    )


def _manifest_source_entry_extra_key(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    baseline = cast(dict[str, object], provenance["source_baseline"])
    entries = cast(list[object], baseline["entries"])
    entry = cast(dict[str, object], entries[0])
    return entries.__setitem__(0, {**entry, "junk_key": True})


def _manifest_directory_entry_with_file_mode(document: dict[str, object]) -> object:
    provenance = cast(dict[str, object], document["provenance"])
    baseline = cast(dict[str, object], provenance["source_baseline"])
    entries = cast(list[object], baseline["entries"])
    entry = cast(dict[str, object], entries[0])
    return entries.__setitem__(0, {**entry, "kind": "directory", "mode": 420})


class TestManifest:
    def _github_manifest_value(self) -> CandidateManifest:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.GITHUB,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=GitHubSourceBaseline(
                kind="github",
                fingerprint=template_source_fingerprint(fixture_source_entries()),
                entries=fixture_source_entries(),
                snapshot_commit="0" * 40,
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                return manifest
            case Err(error):
                raise AssertionError(f"manifest build failed: {error}")

    def _copier_manifest_value(self) -> CandidateManifest:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.COPIER,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=CopierSourceBaseline(
                kind="copier",
                fingerprint=template_source_fingerprint(fixture_source_entries()),
                entries=fixture_source_entries(),
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                return manifest
            case Err(error):
                raise AssertionError(f"copier manifest build failed: {error}")

    def _adopted_manifest_value(self) -> CandidateManifest:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.ADOPTED,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=AdoptedSourceBaseline(
                kind="adopted",
                fingerprint=template_source_fingerprint(fixture_source_entries()),
                entries=fixture_source_entries(),
                snapshot_commit="0" * 40,
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                return manifest
            case Err(error):
                raise AssertionError(f"adopted manifest build failed: {error}")

    def test_adopted_manifest_round_trip_preserves_the_baseline_kind(self) -> None:
        manifest = self._adopted_manifest_value()
        encoded = encode_manifest(manifest)
        match decode_manifest(encoded):
            case Ok(decoded):
                assert decoded == manifest
                assert encode_manifest(decoded) == encoded
            case Err(error):
                raise AssertionError(f"adopted manifest decode failed: {error}")

    def test_copier_manifest_round_trip_preserves_the_baseline_kind(self) -> None:
        manifest = self._copier_manifest_value()
        encoded = encode_manifest(manifest)
        match decode_manifest(encoded):
            case Ok(decoded):
                assert decoded == manifest
                assert encode_manifest(decoded) == encoded
            case Err(error):
                raise AssertionError(f"copier manifest decode failed: {error}")

    def test_round_trip_preserves_typed_values(self) -> None:
        manifest = self._github_manifest_value()
        encoded = encode_manifest(manifest)
        match decode_manifest(encoded):
            case Ok(decoded):
                assert decoded == manifest
                assert encode_manifest(decoded) == encoded
            case Err(error):
                raise AssertionError(f"manifest decode failed: {error}")

    def test_checksum_is_tagged_and_excludes_the_checksum_field(self) -> None:
        manifest = self._github_manifest_value()
        document = manifest_document(manifest)
        checksum = manifest_checksum(document)
        assert checksum == tagged_digest(b"manifest", canonical_json(document))
        assert checksum != tagged_digest(b"other", canonical_json(document))
        with_checksum = {**document, "checksum": "0" * 64}
        assert (
            manifest_checksum(
                {key: item for key, item in with_checksum.items() if key != "checksum"}
            )
            == checksum
        )

    def test_tampered_checksum_is_rejected(self) -> None:
        encoded = bytearray(encode_manifest(self._github_manifest_value()))
        marker = b'"checksum":"'
        index = encoded.find(marker) + len(marker)
        assert index > len(marker)
        encoded[index] = ord("0") if encoded[index] != ord("0") else ord("1")
        match decode_manifest(bytes(encoded)):
            case Err(error):
                assert error.kind is ManifestErrorKind.CHECKSUM_MISMATCH
            case Ok(_):
                raise AssertionError("tampered checksum decoded")

    def test_tampered_field_is_rejected(self) -> None:
        encoded = bytearray(encode_manifest(self._github_manifest_value()))
        marker = b'"example"'
        index = encoded.find(marker)
        assert index >= 0
        encoded[index + 1] = ord("X")
        match decode_manifest(bytes(encoded)):
            case Err(error):
                assert error.kind is ManifestErrorKind.CHECKSUM_MISMATCH
            case Ok(_):
                raise AssertionError("tampered field decoded")

    def test_manifest_rejects_a_valid_but_wrong_source_fingerprint(self) -> None:
        provenance = replace(
            self._github_manifest_value().provenance,
            source_baseline=replace(
                self._github_manifest_value().provenance.source_baseline,
                fingerprint="0" * 64,
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("wrong source fingerprint accepted")

    def test_manifest_rejects_unsorted_source_entries(self) -> None:
        entries = fixture_source_entries()
        provenance = replace(
            self._github_manifest_value().provenance,
            source_baseline=replace(
                self._github_manifest_value().provenance.source_baseline,
                entries=tuple(reversed(entries)),
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("unsorted source entries accepted")

    def test_unknown_schema_version_fails_before_any_write(self) -> None:
        encoded = bytearray(encode_manifest(self._github_manifest_value()))
        index = encoded.find(b'"schema_version":1')
        assert index >= 0
        encoded[index + len('"schema_version":')] = ord("2")
        match decode_manifest(bytes(encoded)):
            case Err(error):
                assert error.kind is ManifestErrorKind.UNSUPPORTED_SCHEMA_VERSION
            case Ok(_):
                raise AssertionError("future schema version decoded")

    def test_invalid_json_is_rejected(self) -> None:
        match decode_manifest(b"{not json"):
            case Err(error):
                assert error.kind is ManifestErrorKind.INVALID_JSON
            case Ok(_):
                raise AssertionError("invalid JSON decoded")

    def test_shape_violations_are_rejected(self) -> None:
        provenance = self._github_manifest_value().provenance
        bad_answers = replace(
            fixture_answers(),
            project=ProjectFacts(name="bad name", default_branch="main"),
        )
        match build_candidate_manifest(
            answers=bad_answers,
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("invalid project name accepted")

        bad_additions = ManifestAdditions(requested=("nix", "cachix-publish"))
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=bad_additions,
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("unsorted additions accepted")

    def test_build_rejects_overlapping_answers_and_additions_settings(self) -> None:
        provenance = self._github_manifest_value().provenance
        answers = replace(
            fixture_answers(), settings=MappingProxyType({"nix": {"cache_name": "a"}})
        )
        additions = ManifestAdditions(
            settings=MappingProxyType({"nix": {"cache_name": "b"}})
        )
        match build_candidate_manifest(
            answers=answers,
            additions=additions,
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
                assert error.subject == "settings.nix"
            case Ok(_):
                raise AssertionError("overlapping capability settings accepted")

    def test_decode_rejects_overlapping_answers_and_additions_settings(self) -> None:
        document = manifest_document(self._github_manifest_value())
        answers = cast(dict[str, object], document["answers"])
        answers["settings"] = {"nix": {"cache_name": "a"}}
        additions = cast(dict[str, object], document["additions"])
        additions["settings"] = {"nix": {"cache_name": "b"}}
        encoded = canonical_json({**document, "checksum": manifest_checksum(document)})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("overlapping capability settings decoded")

    def test_manifest_rejects_unsafe_managed_paths(self) -> None:
        provenance = self._github_manifest_value().provenance
        unsafe = ManagedInventoryEntry(
            path=RepoPath("../escape"),
            kind="text",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"x"),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(unsafe,),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("unsafe managed path accepted")

    def test_manifest_rejects_unsafe_retained_paths(self) -> None:
        provenance = replace(
            self._github_manifest_value().provenance,
            maintenance=MaintenanceRecord(
                status="retained", retained_paths=(RepoPath(".."),)
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("unsafe retained path accepted")

    def test_manifest_rejects_unsafe_baseline_entries(self) -> None:
        provenance = replace(
            self._github_manifest_value().provenance,
            source_baseline=replace(
                self._github_manifest_value().provenance.source_baseline,
                entries=(
                    LifecycleSourceEntry(
                        path=RepoPath(".."),
                        kind="file",
                        mode=PosixMode.FILE,
                        sha256=sha256_hex(b"x"),
                    ),
                ),
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("unsafe baseline entry accepted")

    def test_manifest_never_contains_adopter_or_legal_prose(self) -> None:
        provenance = self._github_manifest_value().provenance
        answers = fixture_answers(licensing_mode="provided-project-license")
        match build_candidate_manifest(
            answers=answers,
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                pass
            case Err(error):
                raise AssertionError(f"manifest build failed: {error}")
        encoded = encode_manifest(manifest)
        assert b"Adopter license text" not in encoded
        assert b"<!-- rygor:placeholder:prd -->" not in encoded
        assert b"Apache License" not in encoded
        assert manifest.answers.licensing.content_sha256 == sha256_hex(
            LEGAL_CONTENTS["provided-project-license"]["LICENSE"]
        )

    def test_decode_rejects_duplicate_managed_entries(self) -> None:
        entry = ManagedInventoryEntry(
            path=RepoPath("pyproject.toml"),
            kind="text",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"x"),
        )
        provenance = self._github_manifest_value().provenance
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(entry,),
        ):
            case Ok(manifest):
                pass
            case Err(error):
                raise AssertionError(f"manifest build failed: {error}")
        document = manifest_document(manifest)
        managed_entry = document["managed"]
        assert isinstance(managed_entry, list) and managed_entry
        managed_entry = cast(list[object], managed_entry)
        duplicate = cast(dict[str, object], managed_entry[0])
        document["managed"] = [dict(duplicate), dict(duplicate)]
        document["managed"] = [
            dict(document["managed"][0]),
            dict(document["managed"][0]),
        ]
        encoded = canonical_json({**document, "checksum": manifest_checksum(document)})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("duplicate managed entries decoded")

    def test_oversized_manifest_is_rejected(self) -> None:
        data = b" " * (16 * 1024 * 1024 + 1)
        match decode_manifest(data):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("oversized manifest decoded")

    @pytest.mark.parametrize(
        ("answers"),
        [
            pytest.param(
                replace(
                    fixture_answers(),
                    licensing=LicensingRecord(mode="other", content_sha256=None),
                ),
                id="licensing mode",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    licensing=LicensingRecord(
                        mode="retain-apache-2.0", content_sha256="zzz"
                    ),
                ),
                id="licensing digest",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    slots=MappingProxyType(
                        {
                            **{
                                rule.slot: SlotContent(
                                    mode="scaffold", content_sha256=None
                                )
                                for rule in SLOT_PLACEHOLDER_RULES
                            },
                            "unknown": SlotContent(
                                mode="scaffold", content_sha256=None
                            ),
                        }
                    ),
                ),
                id="unknown slot",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    slots=MappingProxyType(
                        {
                            **{
                                rule.slot: SlotContent(
                                    mode="scaffold", content_sha256=None
                                )
                                for rule in SLOT_PLACEHOLDER_RULES
                            },
                            "readme": SlotContent(mode="other", content_sha256=None),
                        }
                    ),
                ),
                id="slot mode",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    slots=MappingProxyType(
                        {
                            **{
                                rule.slot: SlotContent(
                                    mode="scaffold", content_sha256=None
                                )
                                for rule in SLOT_PLACEHOLDER_RULES
                            },
                            "readme": SlotContent(mode="file", content_sha256="zzz"),
                        }
                    ),
                ),
                id="slot digest",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    settings=MappingProxyType(
                        {"Bad": MappingProxyType[str, str | bool]({})}
                    ),
                ),
                id="settings capability",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    settings=MappingProxyType(
                        {"nix": MappingProxyType({"bad-name": "x"})}
                    ),
                ),
                id="settings name",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    settings=MappingProxyType(
                        {"nix": MappingProxyType({"cache_name": 5})}
                    ),
                ),
                id="settings value",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    profile=ProfileSelection(id="Bad", requested=()),
                ),
                id="profile id",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    profile=ProfileSelection(id="portable", requested=("Bad",)),
                ),
                id="profile requested identifier",
            ),
            pytest.param(
                replace(
                    fixture_answers(),
                    project=ProjectFacts(name="bad name", default_branch="main"),
                ),
                id="project name",
            ),
        ],
    )
    def test_build_rejects_invalid_answers(self, answers: ManifestAnswers) -> None:
        provenance = self._github_manifest_value().provenance
        match build_candidate_manifest(
            answers=answers,
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("invalid answers built")

    @pytest.mark.parametrize(
        ("provenance"),
        [
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.COPIER,
                    maintenance=MaintenanceRecord(status="clean"),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint=sha256_hex(b"source"),
                        entries=fixture_source_entries(),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="generation baseline mismatch",
            ),
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.GITHUB,
                    maintenance=MaintenanceRecord(
                        status=cast(
                            Literal["clean", "retained"],
                            "other",  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                        )
                    ),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint=sha256_hex(b"source"),
                        entries=fixture_source_entries(),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="maintenance status",
            ),
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.GITHUB,
                    maintenance=MaintenanceRecord(
                        status="retained",
                        retained_paths=(RepoPath("b"), RepoPath("a")),
                    ),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint=sha256_hex(b"source"),
                        entries=fixture_source_entries(),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="retained paths unsorted",
            ),
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.GITHUB,
                    maintenance=MaintenanceRecord(status="clean"),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint="zzz",
                        entries=fixture_source_entries(),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="baseline fingerprint",
            ),
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.GITHUB,
                    maintenance=MaintenanceRecord(status="clean"),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint=sha256_hex(b"source"),
                        entries=(
                            LifecycleSourceEntry(
                                path=RepoPath("a.py"),
                                kind="file",
                                mode=PosixMode.FILE,
                                sha256=sha256_hex(b"a"),
                            ),
                            LifecycleSourceEntry(
                                path=RepoPath("a.py"),
                                kind="file",
                                mode=PosixMode.FILE,
                                sha256=sha256_hex(b"a"),
                            ),
                        ),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="baseline entries duplicate",
            ),
            pytest.param(
                ProvenanceRecord(
                    generation_path=GenerationPath.GITHUB,
                    maintenance=MaintenanceRecord(status="clean"),
                    source_baseline=GitHubSourceBaseline(
                        kind="github",
                        fingerprint=sha256_hex(b"source"),
                        entries=(
                            LifecycleSourceEntry(
                                path=RepoPath("a.py"),
                                kind="file",
                                mode=PosixMode(0o600),
                                sha256=sha256_hex(b"a"),
                            ),
                        ),
                        snapshot_commit="0" * 40,
                    ),
                ),
                id="baseline entry mode",
            ),
        ],
    )
    def test_build_rejects_invalid_provenance(
        self, provenance: ProvenanceRecord
    ) -> None:
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("invalid provenance built")

    def test_build_rejects_invalid_managed(self) -> None:
        provenance = self._github_manifest_value().provenance
        cases: tuple[tuple[str, ManagedInventory], ...] = (
            (
                "duplicate",
                (
                    ManagedInventoryEntry(
                        path=RepoPath("a.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        sha256=sha256_hex(b"a"),
                    ),
                    ManagedInventoryEntry(
                        path=RepoPath("a.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        sha256=sha256_hex(b"a"),
                    ),
                ),
            ),
            (
                "unsorted",
                (
                    ManagedInventoryEntry(
                        path=RepoPath("b.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        sha256=sha256_hex(b"b"),
                    ),
                    ManagedInventoryEntry(
                        path=RepoPath("a.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        sha256=sha256_hex(b"a"),
                    ),
                ),
            ),
            (
                "bad digest",
                (
                    ManagedInventoryEntry(
                        path=RepoPath("a.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        sha256="zzz",
                    ),
                ),
            ),
            (
                "bad mode",
                (
                    ManagedInventoryEntry(
                        path=RepoPath("a.txt"),
                        kind="text",
                        mode=PosixMode(0o600),
                        sha256=sha256_hex(b"a"),
                    ),
                ),
            ),
        )
        for label, managed in cases:
            match build_candidate_manifest(
                answers=fixture_answers(),
                additions=ManifestAdditions(),
                provenance=provenance,
                managed=managed,
            ):
                case Err(error):
                    assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION, label
                case Ok(_):
                    raise AssertionError(f"invalid managed built: {label}")

    def test_decode_rejects_non_object_documents(self) -> None:
        match decode_manifest(b"[1]"):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("non-object manifest decoded")

    def test_decode_rejects_non_sha256_checksum(self) -> None:
        document = manifest_document(self._github_manifest_value())
        encoded = canonical_json({**document, "checksum": "zzz"})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("non-sha256 checksum decoded")

    def test_path_within_limits_component_count(self) -> None:
        assert path_within_limits(RepoPath("/".join(["a"] * 64)))
        assert not path_within_limits(RepoPath("/".join(["a"] * 65)))

    def test_retain_mode_records_no_license_digest(self) -> None:
        assert self._github_manifest_value().answers.licensing.content_sha256 is None

    @pytest.mark.parametrize(
        ("mutate"),
        [
            pytest.param(_manifest_answers_missing, id="answers missing"),
            pytest.param(_manifest_project_name, id="project name"),
            pytest.param(_manifest_default_branch, id="default branch"),
            pytest.param(_manifest_profile_id, id="profile id"),
            pytest.param(
                _manifest_profile_requested_unsorted,
                id="profile requested unsorted",
            ),
            pytest.param(_manifest_settings_capability_id, id="settings capability id"),
            pytest.param(_manifest_settings_name, id="settings name"),
            pytest.param(_manifest_settings_value, id="settings value"),
            pytest.param(_manifest_licensing_mode, id="licensing mode"),
            pytest.param(_manifest_licensing_digest, id="licensing digest"),
            pytest.param(_manifest_slot_mode, id="slot mode"),
            pytest.param(_manifest_slot_digest, id="slot digest"),
            pytest.param(_manifest_unknown_slot, id="unknown slot"),
            pytest.param(_manifest_additions_unsorted, id="additions unsorted"),
            pytest.param(_manifest_additions_settings, id="additions settings"),
            pytest.param(_manifest_generation_path, id="generation path"),
            pytest.param(_manifest_maintenance_status, id="maintenance status"),
            pytest.param(_manifest_retained_paths_unsafe, id="retained paths unsafe"),
            pytest.param(_manifest_baseline_kind, id="baseline kind"),
            pytest.param(_manifest_baseline_fingerprint, id="baseline fingerprint"),
            pytest.param(
                _manifest_baseline_fingerprint_mismatch,
                id="baseline fingerprint mismatch",
            ),
            pytest.param(
                _manifest_baseline_entries_unsafe_path,
                id="baseline entries unsafe path",
            ),
            pytest.param(
                _manifest_baseline_missing_snapshot_commit,
                id="baseline missing snapshot commit",
            ),
            pytest.param(_manifest_baseline_kind_mismatch, id="baseline kind mismatch"),
            pytest.param(
                _manifest_baseline_entries_unsorted,
                id="baseline entries unsorted",
            ),
            pytest.param(_manifest_managed_unsorted, id="managed unsorted"),
            pytest.param(_manifest_managed_case_collision, id="managed case collision"),
            pytest.param(
                _manifest_profile_requested_not_list,
                id="profile requested not list",
            ),
            pytest.param(
                _manifest_project_name_not_string, id="project name not string"
            ),
            pytest.param(_manifest_profile_id_not_string, id="profile id not string"),
            pytest.param(
                _manifest_licensing_mode_not_string, id="licensing mode not string"
            ),
            pytest.param(
                _manifest_licensing_digest_not_string,
                id="licensing digest not string",
            ),
            pytest.param(_manifest_slot_mode_not_string, id="slot mode not string"),
            pytest.param(_manifest_slot_digest_not_string, id="slot digest not string"),
            pytest.param(_manifest_slot_not_mapping, id="slot not mapping"),
            pytest.param(_manifest_settings_not_mapping, id="settings not mapping"),
            pytest.param(
                _manifest_settings_values_not_mapping,
                id="settings values not mapping",
            ),
            pytest.param(_manifest_project_not_mapping, id="project not mapping"),
            pytest.param(_manifest_licensing_not_mapping, id="licensing not mapping"),
            pytest.param(
                _manifest_additions_requested_not_list,
                id="additions requested not list",
            ),
            pytest.param(
                _manifest_generation_path_not_string,
                id="generation path not string",
            ),
            pytest.param(
                _manifest_maintenance_not_mapping, id="maintenance not mapping"
            ),
            pytest.param(
                _manifest_retained_paths_not_list, id="retained paths not list"
            ),
            pytest.param(_manifest_baseline_not_mapping, id="baseline not mapping"),
            pytest.param(
                _manifest_baseline_entries_not_list, id="baseline entries not list"
            ),
            pytest.param(_manifest_managed_not_list, id="managed not list"),
            pytest.param(
                _manifest_managed_entry_path_not_string,
                id="managed entry path not string",
            ),
            pytest.param(
                _manifest_managed_duplicate_entries, id="managed duplicate entries"
            ),
            pytest.param(_manifest_answers_extra_key, id="answers extra key"),
            pytest.param(_manifest_project_extra_key, id="project extra key"),
            pytest.param(_manifest_profile_extra_key, id="profile extra key"),
            pytest.param(_manifest_licensing_extra_key, id="licensing extra key"),
            pytest.param(_manifest_slot_content_extra_key, id="slot content extra key"),
            pytest.param(_manifest_additions_extra_key, id="additions extra key"),
            pytest.param(_manifest_provenance_extra_key, id="provenance extra key"),
            pytest.param(_manifest_maintenance_extra_key, id="maintenance extra key"),
            pytest.param(_manifest_baseline_extra_key, id="baseline extra key"),
            pytest.param(
                _manifest_baseline_bad_snapshot_commit,
                id="baseline bad snapshot commit",
            ),
            pytest.param(
                _manifest_managed_entry_extra_key, id="managed entry extra key"
            ),
            pytest.param(_manifest_source_entry_extra_key, id="source entry extra key"),
            pytest.param(
                _manifest_directory_entry_with_file_mode,
                id="directory entry with file mode",
            ),
        ],
    )
    @pytest.mark.parametrize("adopted", [False, True], ids=["github", "adopted"])
    def test_decode_rejects_malformed_documents(
        self,
        mutate: Callable[[dict[str, object]], object],
        adopted: bool,
    ) -> None:
        manifest = (
            self._adopted_manifest_value() if adopted else self._github_manifest_value()
        )
        document = manifest_document(manifest)
        _ = mutate(document)
        encoded = canonical_json({**document, "checksum": manifest_checksum(document)})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("malformed manifest decoded")

    def test_decode_rejects_unknown_top_level_keys(self) -> None:
        document = manifest_document(self._github_manifest_value())
        document["unexpected_field"] = True
        encoded = canonical_json({**document, "checksum": manifest_checksum(document)})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("manifest with unknown top-level key decoded")

    @given(
        licensing_mode=st.sampled_from(
            ("retain-apache-2.0", "provided-project-license", "private")
        ),
        file_slots=st.sampled_from(
            (
                (),
                ("readme",),
                ("readme", "prd", "security_policy", "contributing", "validation_hook"),
            )
        ),
    )
    def test_manifest_round_trip_is_byte_stable(
        self, licensing_mode: str, file_slots: tuple[str, ...]
    ) -> None:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.GITHUB,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=GitHubSourceBaseline(
                kind="github",
                fingerprint=template_source_fingerprint(fixture_source_entries()),
                entries=fixture_source_entries(),
                snapshot_commit="0" * 40,
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(
                licensing_mode=licensing_mode, file_slots=file_slots
            ),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                pass
            case Err(error):
                raise AssertionError(f"manifest build failed: {error}")
        encoded = encode_manifest(manifest)
        match decode_manifest(encoded):
            case Ok(decoded):
                assert decoded == manifest
            case Err(error):
                raise AssertionError(f"manifest round trip failed: {error}")
        assert encode_manifest(decoded) == encoded

    def test_manifest_round_trip_preserves_directory_source_entries(self) -> None:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.GITHUB,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=GitHubSourceBaseline(
                kind="github",
                fingerprint=template_source_fingerprint(
                    (
                        *fixture_source_entries(),
                        LifecycleSourceEntry(
                            path=RepoPath("scripts/bootstrap"),
                            kind="directory",
                            mode=PosixMode.DIRECTORY,
                            sha256=sha256_hex(b"dir"),
                        ),
                    )
                ),
                entries=(
                    LifecycleSourceEntry(
                        path=RepoPath("scripts/bootstrap"),
                        kind="directory",
                        mode=PosixMode.DIRECTORY,
                        sha256=sha256_hex(b"dir"),
                    ),
                    *fixture_source_entries(),
                ),
                snapshot_commit="0" * 40,
            ),
        )
        match build_candidate_manifest(
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            provenance=provenance,
            managed=(),
        ):
            case Ok(manifest):
                pass
            case Err(error):
                raise AssertionError(f"manifest build failed: {error}")
        match decode_manifest(encode_manifest(manifest)):
            case Ok(decoded):
                assert decoded == manifest
            case Err(error):
                raise AssertionError(f"manifest round trip failed: {error}")

    _INJECTION_PATHS: tuple[tuple[str, ...], ...] = (
        ("answers",),
        ("answers", "project"),
        ("answers", "profile"),
        ("answers", "licensing"),
        ("additions",),
        ("provenance",),
        ("provenance", "maintenance"),
        ("provenance", "source_baseline"),
    )

    @given(
        path=st.sampled_from(_INJECTION_PATHS),
        key=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz").map(
            lambda key: "zzz" + key
        ),
    )
    def test_decode_rejects_extra_nested_keys(
        self, path: tuple[str, ...], key: str
    ) -> None:
        document = manifest_document(self._github_manifest_value())
        target: dict[str, object] = document
        for segment in path:
            assert isinstance(target[segment], dict)
            target = cast(dict[str, object], target[segment])
        target[key] = True
        encoded = canonical_json({**document, "checksum": manifest_checksum(document)})
        match decode_manifest(encoded):
            case Err(error):
                assert error.kind is ManifestErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError(f"manifest with extra nested key {path} decoded")


class TestPlanner:
    def test_plan_is_complete_and_expected_target_matches(self) -> None:
        plan = github_plan()
        legal_paths = legal_output_paths("retain-apache-2.0")
        assert legal_paths is not None
        expected_paths = {path.value for path in (*slot_paths().values(), *legal_paths)}
        expected_paths.update(path for path, _kind, _content in MANAGED_CONTENTS)
        expected_paths.add(MANIFEST_PATH.value)
        expected_paths.update(path.value for path in CLEANUP_PATHS)
        snapshot = github_snapshot()
        for root in CLEANUP_PATHS:
            prefix = root.value + "/"
            expected_paths.update(
                entry.path.value
                for entry in (*snapshot.files, *snapshot.directories)
                if entry.path.value.startswith(prefix)
            )
        expected_paths.add(MAINTENANCE_INVENTORY_PATH.value)
        op_paths: set[str] = set()
        for operation in plan.ordered_operations:
            op_paths.add(
                operation.root.value
                if isinstance(operation, CreateTreeOperation)
                else operation.path.value
            )
        assert op_paths == expected_paths

        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        by_path = {file.path.value: file.content for file in expected.files}
        for path_value, _kind, content in MANAGED_CONTENTS:
            assert by_path[path_value] == content
        assert by_path[MANIFEST_PATH.value] == plan.manifest_after.payload
        assert plan.source_before is None
        assert isinstance(plan.source_after, GitHubSourceBaseline)
        assert plan.manifest_before is None
        match decode_manifest(plan.manifest_after.payload):
            case Ok(decoded):
                assert decoded.provenance.generation_path is GenerationPath.GITHUB
                assert isinstance(
                    decoded.provenance.source_baseline, GitHubSourceBaseline
                )
                assert decoded.provenance.maintenance.status == "clean"
                assert plan.manifest_after.digest == manifest_checksum(
                    manifest_document(decoded)
                )
            case Err(error):
                raise AssertionError(f"planned manifest is invalid: {error}")

    def test_apply_plan_rejects_duplicate_replace_operations(self) -> None:
        plan = github_plan()
        replaces = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, ReplaceFileOperation)
        ]
        assert replaces
        duplicated = replace(
            plan,
            ordered_operations=(
                replaces[0],
                replaces[0],
                *plan.ordered_operations,
            ),
        )
        match apply_plan(github_snapshot(), duplicated):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("duplicate replace operations applied")

    def test_apply_plan_rejects_duplicate_delete_operations(self) -> None:
        plan = github_plan()
        deletes = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, DeleteFileOperation)
        ]
        assert deletes
        duplicated = replace(
            plan,
            ordered_operations=(
                deletes[0],
                deletes[0],
                *plan.ordered_operations,
            ),
        )
        match apply_plan(github_snapshot(), duplicated):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("duplicate delete operations applied")

    def test_unsafe_seed_and_managed_paths_are_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        unsafe_seed = replace(seed_once[0], path=RepoPath("../escape"))
        _, result = compile_fixture(seed_once=(unsafe_seed,), blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsafe seed path compiled")

        unsafe_managed = replace(fixture_managed()[0], path=RepoPath("../escape"))
        _, result = compile_fixture(managed=(unsafe_managed,))
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsafe managed path compiled")

    def _nested_copier_plan(self) -> OperationPlan:
        """A Copier plan whose docs tree contains a directory entry."""
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/api/ref.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"# API\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=fixture_copier_snapshot(),
            cleanup=None,
            snapshot_commit=None,
            managed=managed,
        )
        return get_plan(result)

    def test_apply_plan_rejects_duplicate_tree_entries(self) -> None:
        snapshot = fixture_copier_snapshot()
        plan = self._nested_copier_plan()
        operations = list(plan.ordered_operations)
        index = next(
            index
            for index, operation in enumerate(plan.ordered_operations)
            if isinstance(operation, CreateTreeOperation)
            and operation.root.value == "docs"
        )
        tree = operations[index]
        assert isinstance(tree, CreateTreeOperation)
        entries = tree.planned_new.entries
        for duplicate in (entries[0], entries[1]):
            operations[index] = replace(
                tree,
                planned_new=replace(tree.planned_new, entries=(*entries, duplicate)),
            )
            duplicated = replace(plan, ordered_operations=tuple(operations))
            match apply_plan(snapshot, duplicated):
                case Err(error):
                    assert error.kind is PlanInvariantErrorKind.DUPLICATE_PATH
                case Ok(_):
                    raise AssertionError("duplicate tree entry applied")

    def test_apply_plan_rejects_a_missing_tree_entry_blob(self) -> None:
        snapshot = fixture_copier_snapshot()
        plan = self._nested_copier_plan()
        operations = list(plan.ordered_operations)
        index = next(
            index
            for index, operation in enumerate(plan.ordered_operations)
            if isinstance(operation, CreateTreeOperation)
            and operation.root.value == "docs"
        )
        tree = operations[index]
        assert isinstance(tree, CreateTreeOperation)
        file_entry = next(
            entry
            for entry in tree.planned_new.entries
            if isinstance(entry, PlannedFileEntry)
        )
        operations[index] = replace(
            tree,
            planned_new=replace(
                tree.planned_new,
                entries=tuple(
                    replace(entry, content_id=ContentId("0" * 64))
                    if entry is file_entry
                    else entry
                    for entry in tree.planned_new.entries
                ),
            ),
        )
        missing = replace(plan, ordered_operations=tuple(operations))
        match apply_plan(snapshot, missing):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.MISSING_BLOB
            case Ok(_):
                raise AssertionError("tree entry with a missing blob applied")

    def test_apply_plan_rejects_removing_directory_with_remaining_files(self) -> None:
        plan = github_plan()
        remove = RemoveEmptyDirectoryOperation(
            path=RepoPath(".rygor"),
            expected_old=DirectoryState(PosixMode.DIRECTORY, ()),
            planned_new=DirectoryAbsent(),
        )
        augmented = replace(plan, ordered_operations=(*plan.ordered_operations, remove))
        match apply_plan(github_snapshot(), augmented):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("directory with remaining files was removed")

    def test_apply_plan_rejects_duplicate_remove_directory_operations(self) -> None:
        plan = github_plan()
        removes = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, RemoveEmptyDirectoryOperation)
        ]
        assert removes
        duplicated = replace(
            plan,
            ordered_operations=(
                *plan.ordered_operations,
                removes[0],
                removes[0],
            ),
        )
        match apply_plan(github_snapshot(), duplicated):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("duplicate remove-directory operations applied")

    def test_apply_plan_rejects_remove_directory_with_mismatched_precondition(
        self,
    ) -> None:
        plan = github_plan()
        removes = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, RemoveEmptyDirectoryOperation)
        ]
        assert removes
        tampered = replace(removes[0], expected_old=DirectoryState(PosixMode.FILE, ()))
        augmented = replace(
            plan,
            ordered_operations=tuple(
                tampered if operation is removes[0] else operation
                for operation in plan.ordered_operations
            ),
        )
        match apply_plan(github_snapshot(), augmented):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("remove with mismatched precondition applied")

    def test_compilation_is_deterministic(self) -> None:
        assert github_plan() == github_plan()
        assert build_receipt(github_plan()) == build_receipt(github_plan())

    def test_ordering_creates_before_deletes_and_inventory_last(self) -> None:
        operations = github_plan().ordered_operations
        kinds = [
            (
                "delete"
                if isinstance(
                    operation, (DeleteFileOperation, RemoveEmptyDirectoryOperation)
                )
                else "replace"
                if isinstance(operation, ReplaceFileOperation)
                else "create"
            )
            for operation in operations
        ]
        first_delete = next(
            index for index, kind in enumerate(kinds) if kind == "delete"
        )
        assert all(kind != "delete" for kind in kinds[:first_delete])
        assert all(kind == "delete" for kind in kinds[first_delete:])
        assert isinstance(operations[-1], DeleteFileOperation)
        assert operations[-1].path == MAINTENANCE_INVENTORY_PATH
        delete_paths = [
            operation.path.value
            for operation in operations
            if isinstance(operation, DeleteFileOperation)
        ]
        assert delete_paths[:-1] == sorted(delete_paths[:-1])
        removes = [
            operation.path.value.split("/")
            for operation in operations
            if isinstance(operation, RemoveEmptyDirectoryOperation)
        ]
        depths = [len(parts) for parts in removes]
        assert depths == sorted(depths, reverse=True)

    def test_new_hierarchies_share_one_create_tree_per_root(self) -> None:
        snapshot = fixture_copier_snapshot()
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
        )
        plan = get_plan(result)
        trees = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
        ]
        assert {tree.root.value for tree in trees} == {"docs", ".rygor"}
        docs_tree = next(tree for tree in trees if tree.root.value == "docs")
        tree_paths = {entry.path.value for entry in docs_tree.planned_new.entries}
        assert tree_paths == {"docs/prd.md", "docs/template-updates.md"}
        assert isinstance(plan.source_after, CopierSourceBaseline)
        assert all(
            not isinstance(operation, DeleteFileOperation)
            for operation in plan.ordered_operations
        )
        # Every planned path must be emitted exactly once, and the plan must overlay.
        counts: Counter[str] = Counter()
        for operation in plan.ordered_operations:
            if isinstance(operation, CreateTreeOperation):
                counts.update(
                    entry.path.value for entry in operation.planned_new.entries
                )
            else:
                counts[operation.path.value] += 1
        assert all(count == 1 for count in counts.values())
        match apply_plan(snapshot, plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"copier plan did not overlay: {error}")
        by_path = {file.path.value: file.content for file in expected.files}
        assert by_path["docs/prd.md"].startswith(b"<!-- rygor:placeholder:prd -->")
        assert by_path[MANIFEST_PATH.value] == plan.manifest_after.payload

    def test_one_tree_roots_each_wholly_new_hierarchy_at_its_highest_absent_directory(
        self,
    ) -> None:
        """Outputs at different depths under one missing directory share one tree."""
        snapshot = fixture_copier_snapshot()
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/api/ref.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"# API\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
            managed=managed,
        )
        plan = get_plan(result)
        trees = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
        ]
        assert {tree.root.value for tree in trees} == {"docs", ".rygor"}
        docs_tree = next(tree for tree in trees if tree.root.value == "docs")
        file_paths = {
            entry.path.value
            for entry in docs_tree.planned_new.entries
            if isinstance(entry, PlannedFileEntry)
        }
        assert file_paths == {
            "docs/prd.md",
            "docs/template-updates.md",
            "docs/api/ref.md",
        }
        assert any(
            entry.path.value == "docs/api" for entry in docs_tree.planned_new.entries
        )

    def test_output_inside_an_observed_directory_is_not_tree_grouped(self) -> None:
        snapshot = fixture_copier_snapshot()
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/agents/extra.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"# Extra\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
            managed=managed,
        )
        plan = get_plan(result)
        tree_entries = {
            entry.path.value
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
            for entry in operation.planned_new.entries
        }
        assert "docs/agents/extra.md" not in tree_entries
        assert any(
            isinstance(operation, CreateFileOperation)
            and operation.path.value == "docs/agents/extra.md"
            for operation in plan.ordered_operations
        )
        match apply_plan(snapshot, plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"plan did not overlay: {error}")
        assert any(file.path.value == "docs/agents/extra.md" for file in expected.files)

    def test_output_below_observed_directory_roots_tree_at_first_absent_dir(
        self,
    ) -> None:
        snapshot = fixture_copier_snapshot()
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/agents/x/y.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"# Deep\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
            managed=managed,
        )
        plan = get_plan(result)
        trees = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
        ]
        assert {tree.root.value for tree in trees} == {
            "docs",
            "docs/agents/x",
            ".rygor",
        }
        deep_tree = next(tree for tree in trees if tree.root.value == "docs/agents/x")
        assert {entry.path.value for entry in deep_tree.planned_new.entries} == {
            "docs/agents/x/y.md"
        }
        match apply_plan(snapshot, plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"plan did not overlay: {error}")
        assert any(file.path.value == "docs/agents/x/y.md" for file in expected.files)
        assert any(
            entry.path.value == "docs/agents/x" for entry in expected.directories
        )

    def test_retain_maintenance_deletes_nothing_and_records_paths(self) -> None:
        plan = get_plan(
            compile_fixture(maintenance=RetainMaintenance(paths=CLEANUP_PATHS))[1]
        )
        assert all(
            not isinstance(operation, DeleteFileOperation)
            for operation in plan.ordered_operations
        )
        match decode_manifest(plan.manifest_after.payload):
            case Ok(decoded):
                assert decoded.provenance.maintenance.status == "retained"
                assert decoded.provenance.maintenance.retained_paths == tuple(
                    sorted(CLEANUP_PATHS, key=lambda path: path.value.encode("utf-8"))
                )
            case Err(error):
                raise AssertionError(f"planned manifest is invalid: {error}")

    def test_scaffold_slot_requires_its_marker_in_planned_bytes(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        clean_prd = b"# Product\n"
        store, _ = intern_all(store, {"clean-prd": clean_prd})
        without_marker = tuple(
            replace(
                seed,
                content_id=ContentId.from_bytes(clean_prd)
                if seed.path.value == "docs/prd.md"
                else seed.content_id,
            )
            for seed in seed_once
        )
        _, result = compile_fixture(seed_once=without_marker, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("scaffold without marker compiled")

    def test_non_utf8_text_blob_returns_a_compile_error(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        bad = b"\xff\xfe not utf8"
        store, _ = intern_all(store, {"bad": bad})
        bad_seed = tuple(
            replace(seed, content_id=ContentId.from_bytes(bad))
            if seed.path.value == "README.md"
            else seed
            for seed in seed_once
        )
        _, result = compile_fixture(seed_once=bad_seed, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
                assert error.subject == "README.md"
            case Ok(_):
                raise AssertionError("non-UTF-8 text blob compiled")

    def test_nested_planned_outputs_are_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"a file named docs\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("nested planned outputs compiled")

    def test_nested_planned_outputs_with_interleaving_sibling_are_refused(
        self,
    ) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"a file named docs\n",
                    ),
                    ManagedFile(
                        path=RepoPath("docs.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"a sibling file\n",
                    ),
                    ManagedFile(
                        path=RepoPath("docs/x"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"# Nested\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=fixture_copier_snapshot(),
            cleanup=None,
            snapshot_commit=None,
            managed=managed,
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
                assert error.subject == "docs"
            case Ok(_):
                raise AssertionError(
                    "nested planned outputs with interleaving sibling compiled"
                )

    def test_planned_path_beyond_limits_is_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("a" * 1100),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"x\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("over-long path compiled")

    def test_invalid_licensing_mode_is_refused(self) -> None:
        answers = replace(
            fixture_answers(),
            licensing=LicensingRecord(mode="other", content_sha256=None),
        )
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        _, result = compile_fixture(
            answers=answers,
            seed_once=seed_once,
            blobs=store,
            snapshot=github_snapshot(),
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("invalid licensing mode compiled")

    def test_blob_limits_are_enforced_on_the_plan_store(self) -> None:
        _, result = compile_fixture(limits=ResourceLimits(max_file_bytes=4))
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PLAN_LIMIT_EXCEEDED
            case Ok(_):
                raise AssertionError("oversized blob interned into the plan")

    def test_unsafe_snapshot_path_is_refused(self) -> None:
        snapshot = _sorted_snapshot(
            (*github_snapshot().files, observed_file(RepoPath(".."), b"x\n")),
            github_snapshot().directories,
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsafe snapshot path compiled")

    def test_unsorted_snapshot_directories_are_refused(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            directories=tuple(reversed(snapshot.directories)),
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsorted snapshot directories compiled")

    def test_unsorted_seed_inputs_are_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        _, result = compile_fixture(seed_once=tuple(reversed(seed_once)), blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsorted seed inputs compiled")

    def test_missing_seed_blob_is_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        missing = tuple(
            replace(
                seed,
                content_id=ContentId.from_bytes(b"absent bytes"),
            )
            if seed.path.value == "README.md"
            else seed
            for seed in seed_once
        )
        _, result = compile_fixture(seed_once=missing, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.MISSING_BLOB
            case Ok(_):
                raise AssertionError("missing seed blob compiled")

    def test_invalid_seed_mode_is_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        invalid = tuple(
            replace(seed, mode=PosixMode(0o600))
            if seed.path.value == "README.md"
            else seed
            for seed in seed_once
        )
        _, result = compile_fixture(seed_once=invalid, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("invalid seed mode compiled")

    def test_missing_declared_seed_path_is_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        reduced = tuple(seed for seed in seed_once if seed.path.value != "LICENSE")
        _, result = compile_fixture(seed_once=reduced, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("missing declared seed path compiled")

    def test_retain_without_cleanup_contract_is_refused(self) -> None:
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=fixture_copier_snapshot(),
            cleanup=None,
            snapshot_commit=None,
            maintenance=RetainMaintenance(paths=()),
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_MAINTENANCE
            case Ok(_):
                raise AssertionError("retain without a cleanup contract compiled")

    def test_provided_project_license_compiles_with_apache_preservation(self) -> None:
        answers = fixture_answers(licensing_mode="provided-project-license")
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "provided-project-license"
        )
        _, result = compile_fixture(answers=answers, seed_once=seed_once, blobs=store)
        plan = get_plan(result)
        paths: set[str] = set()
        for operation in plan.ordered_operations:
            if isinstance(operation, CreateTreeOperation):
                paths.update(
                    entry.path.value for entry in operation.planned_new.entries
                )
            else:
                paths.add(operation.path.value)
        assert "LICENSES/Apache-2.0.txt" in paths
        match decode_manifest(plan.manifest_after.payload):
            case Ok(decoded):
                assert decoded.answers.licensing.content_sha256 == sha256_hex(
                    LEGAL_CONTENTS["provided-project-license"]["LICENSE"]
                )
            case Err(error):
                raise AssertionError(f"planned manifest is invalid: {error}")

    def test_invalid_managed_kind_is_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/extra.md"),
                        kind=cast(  # pyright: ignore[reportInvalidCast]  intentional invalid-value negative test
                            Literal["text", "binary"], "other"
                        ),
                        mode=PosixMode.FILE,
                        content=b"x\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("invalid managed kind compiled")

    def test_non_utf8_managed_content_is_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("docs/extra.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"\xff\xfe not utf8",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("non-UTF-8 managed content compiled")

    def test_unsorted_managed_is_refused(self) -> None:
        _, result = compile_fixture(managed=tuple(reversed(fixture_managed())))
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unsorted managed compiled")

    def test_unknown_slot_id_is_refused(self) -> None:
        answers = replace(
            fixture_answers(),
            slots=MappingProxyType(
                {
                    **{
                        rule.slot: SlotContent(mode="scaffold", content_sha256=None)
                        for rule in SLOT_PLACEHOLDER_RULES
                    },
                    "unknown": SlotContent(mode="scaffold", content_sha256=None),
                }
            ),
        )
        _, result = compile_fixture(answers=answers)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("unknown slot id compiled")

    def test_planned_file_below_an_observed_file_is_refused(self) -> None:
        snapshot = fixture_copier_snapshot()
        snapshot = _sorted_snapshot(
            (*snapshot.files, observed_file(RepoPath("docs"), b"a file\n")),
            snapshot.directories,
        )
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("planned file below an observed file compiled")

    def test_invalid_source_entries_are_refused(self) -> None:
        entry = LifecycleSourceEntry(
            path=RepoPath("scripts/bootstrap/render.py"),
            kind="file",
            mode=PosixMode.FILE,
            sha256=sha256_hex(b"a"),
        )
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        result = compile_initial_plan(
            generation=GenerationPath.GITHUB,
            target_identity=TARGET,
            answers=fixture_answers(),
            additions=ManifestAdditions(),
            seed_once=seed_once,
            managed=fixture_managed(),
            blobs=store,
            source_entries=(entry, entry),
            snapshot_commit="0" * 40,
            maintenance=CleanMaintenance(),
            cleanup=fixture_cleanup(),
            snapshot=github_snapshot(),
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_SOURCE_BASELINE
            case Ok(_):
                raise AssertionError("duplicate source entries compiled")

    def test_invalid_manifest_values_are_refused(self) -> None:
        additions = ManifestAdditions(settings=MappingProxyType({"Bad": {}}))
        _, result = compile_fixture(additions=additions)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_MANIFEST
            case Ok(_):
                raise AssertionError("invalid manifest values compiled")

    def test_operation_limits_are_enforced(self) -> None:
        _, result = compile_fixture(limits=ResourceLimits(max_operations=4))
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PLAN_LIMIT_EXCEEDED
            case Ok(_):
                raise AssertionError("over-limit plan compiled")

    def test_file_slot_rejects_marker_in_planned_bytes(self) -> None:
        marked_readme = b"<!-- rygor:placeholder:readme -->\n"
        answers = replace(
            fixture_answers(),
            slots=MappingProxyType(
                {
                    **{
                        rule.slot: SlotContent(mode="scaffold", content_sha256=None)
                        for rule in SLOT_PLACEHOLDER_RULES
                    },
                    "readme": SlotContent(
                        mode="file", content_sha256=sha256_hex(marked_readme)
                    ),
                }
            ),
        )
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        store, _ = intern_all(store, {"marked-readme": marked_readme})
        marked = tuple(
            replace(
                seed,
                content_id=ContentId.from_bytes(marked_readme)
                if seed.path.value == "README.md"
                else seed.content_id,
            )
            for seed in seed_once
        )
        _, result = compile_fixture(answers=answers, seed_once=marked, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("marker-bearing file slot compiled")

    def test_file_slot_declaring_a_wrong_digest_is_refused(self) -> None:
        answers = replace(
            fixture_answers(file_slots=("readme",)),
            slots=MappingProxyType(
                {
                    **fixture_answers(file_slots=("readme",)).slots,
                    "readme": SlotContent(mode="file", content_sha256="0" * 64),
                }
            ),
        )
        _, result = compile_fixture(answers=answers)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("file slot with a wrong declared digest compiled")

    def test_licensing_declaring_a_wrong_digest_is_refused(self) -> None:
        answers = replace(
            fixture_answers(licensing_mode="provided-project-license"),
            licensing=LicensingRecord(
                mode="provided-project-license", content_sha256="0" * 64
            ),
        )
        _, result = compile_fixture(answers=answers)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("licensing with a wrong declared digest compiled")


class TestCollisionsAndCleanup:
    def test_seed_managed_collision_is_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("README.md"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"managed readme\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PATH_COLLISION
            case Ok(_):
                raise AssertionError("seed/managed collision compiled")

    def test_manifest_path_collision_is_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=MANIFEST_PATH,
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"not a manifest\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PATH_COLLISION
            case Ok(_):
                raise AssertionError("manifest collision compiled")

    def test_cleanup_managed_path_is_replaced_not_deleted(self) -> None:
        # A declared cleanup path that is exactly a managed output path is a
        # replacement: the managed file overwrites the source bytes and the
        # cleanup delete is skipped, keeping one operation per path.
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(*CLEANUP_PATHS, RepoPath("pyproject.toml")),
        )
        plan = get_plan(compile_fixture(cleanup=cleanup)[1])
        pyproject_ops = [
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, (CreateFileOperation, ReplaceFileOperation))
            and operation.path.value == "pyproject.toml"
        ]
        assert len(pyproject_ops) == 1
        operation = pyproject_ops[0]
        assert isinstance(operation, ReplaceFileOperation)
        assert operation.expected_old.identity is not None
        assert (
            operation.expected_old.identity.normalized_sha256
            == content_identity(SOURCE_PYPROJECT, text=True).normalized_sha256
        )
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                by_path = {file.path.value: file for file in expected.files}
                assert (
                    by_path["pyproject.toml"].content
                    == b'[project]\nname = "example"\n'
                )
            case Err(error):
                raise AssertionError(f"unexpected overlay failure: {error}")
        delete_paths = [
            operation.path.value
            for operation in plan.ordered_operations
            if isinstance(operation, DeleteFileOperation)
        ]
        assert "pyproject.toml" not in delete_paths

    def test_cleanup_nested_managed_path_is_refused(self) -> None:
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(*CLEANUP_PATHS, RepoPath("docs")),
        )
        _, result = compile_fixture(cleanup=cleanup)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PATH_COLLISION
            case Ok(_):
                raise AssertionError("nested cleanup/managed paths compiled")

    def test_cleanup_disagreement_when_observed_path_is_missing(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=tuple(
                entry for entry in snapshot.files if entry.path.value != "uv.lock"
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError("missing cleanup path compiled")

    def test_cleanup_disagreement_when_inventory_is_missing(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=tuple(
                entry
                for entry in snapshot.files
                if entry.path.value != MAINTENANCE_INVENTORY_PATH.value
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError("missing inventory compiled")

    def test_retain_mismatch_is_refused(self) -> None:
        _, result = compile_fixture(
            maintenance=RetainMaintenance(paths=(RepoPath("tests"),))
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_MAINTENANCE
            case Ok(_):
                raise AssertionError("partial retain compiled")

    def test_retain_maintenance_still_enforces_cleanup_path_limits(self) -> None:
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(RepoPath("tests"), RepoPath("a" * 1100)),
        )
        _, result = compile_fixture(
            maintenance=RetainMaintenance(paths=cleanup.cleanup_paths),
            cleanup=cleanup,
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError("over-limit retained path compiled")

    def test_case_colliding_managed_paths_are_refused(self) -> None:
        managed = tuple(
            sorted(
                (
                    *fixture_managed(),
                    ManagedFile(
                        path=RepoPath("README.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"lower\n",
                    ),
                    ManagedFile(
                        path=RepoPath("readme.txt"),
                        kind="text",
                        mode=PosixMode.FILE,
                        content=b"upper\n",
                    ),
                ),
                key=lambda file: file.path.value.encode("utf-8"),
            )
        )
        _, result = compile_fixture(managed=managed)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("case-colliding managed paths compiled")

    def test_case_colliding_snapshot_paths_are_refused(self) -> None:
        snapshot = github_snapshot()
        snapshot = _sorted_snapshot(
            (
                *snapshot.files,
                observed_file(RepoPath("README.txt"), b"lower\n"),
                observed_file(RepoPath("readme.txt"), b"upper\n"),
            ),
            snapshot.directories,
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("case-colliding snapshot paths compiled")

    def test_case_colliding_seed_paths_are_refused(self) -> None:
        store, seed_once = fixture_seed_once(
            VerifiedBlobStore.empty(), "retain-apache-2.0"
        )
        lowered = tuple(
            replace(seed, path=RepoPath(seed.path.value.lower()))
            if seed.path.value == "README.md"
            else seed
            for seed in seed_once
        )
        _, result = compile_fixture(seed_once=lowered, blobs=store)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("case-colliding seed paths compiled")

    def test_manifest_present_at_target_is_refused(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=(
                *snapshot.files,
                observed_file(MANIFEST_PATH, b'{"schema_version": 1}\n'),
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("pre-existing manifest compiled")

    def test_planned_file_at_observed_directory_is_refused(self) -> None:
        snapshot = github_snapshot()
        snapshot = _sorted_snapshot(
            tuple(entry for entry in snapshot.files if entry.path.value != "README.md"),
            (
                *snapshot.directories,
                observed_directory(RepoPath("README.md")),
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
            case Ok(_):
                raise AssertionError("planned file over observed directory compiled")

    def test_nested_cleanup_paths_are_refused(self) -> None:
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(RepoPath("tests"), RepoPath("tests/sub")),
        )
        _, result = compile_fixture(cleanup=cleanup)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError("nested cleanup paths compiled")

    def test_nested_cleanup_paths_with_interleaving_sibling_are_refused(
        self,
    ) -> None:
        snapshot = github_snapshot()
        files = (
            *snapshot.files,
            observed_file(RepoPath("tests.txt"), b"tests sibling\n"),
        )
        snapshot = _sorted_snapshot(files, snapshot.directories)
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(
                RepoPath("tests"),
                RepoPath("tests.txt"),
                RepoPath("tests/sub"),
            ),
        )
        _, result = compile_fixture(snapshot=snapshot, cleanup=cleanup)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError(
                    "nested cleanup paths with interleaving sibling compiled"
                )

    def test_cleanup_listing_the_inventory_is_refused(self) -> None:
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(*CLEANUP_PATHS, MAINTENANCE_INVENTORY_PATH),
        )
        _, result = compile_fixture(cleanup=cleanup)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.CLEANUP_DISAGREEMENT
            case Ok(_):
                raise AssertionError("cleanup listing the inventory compiled")


def _receipt_extra_top_level_key(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("extra", 1)


def _receipt_plan_schema(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("plan_schema", 2)


def _receipt_operation_kind_field(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("operation_kind", "rotate")


def _receipt_target_binding(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("target_binding", "zzz")


def _receipt_generation_path(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("generation_path", "other")


def _receipt_baseline_kind(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__("kind", "other")


def _receipt_baseline_fingerprint(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__(
        "fingerprint", "zzz"
    )


def _receipt_baseline_entries_unsafe_path(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__(
        "entries",
        [
            {
                "path": "..",
                "kind": "file",
                "mode": 420,
                "sha256": "0" * 64,
            }
        ],
    )


def _receipt_manifest_before(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("manifest_before", "zzz")


def _receipt_manifest_after_null(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("manifest_after", None)


def _receipt_gate_missing_key(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["gate_specification"]).pop(
        "artifact_verification"
    )


def _receipt_gate_severity(receipt: dict[str, object]) -> object:
    gate = cast(dict[str, object], receipt["gate_specification"])
    placeholders = cast(list[object], gate["expected_placeholder"])
    return cast(dict[str, object], placeholders[0]).__setitem__("severity", "urgent")


def _receipt_gate_subject_path(receipt: dict[str, object]) -> object:
    gate = cast(dict[str, object], receipt["gate_specification"])
    placeholders = cast(list[object], gate["expected_placeholder"])
    return cast(dict[str, object], placeholders[0]).__setitem__("subject_at", "..")


def _receipt_operation_extra_key(receipt: dict[str, object]) -> object:
    operations = cast(list[object], receipt["operations"])
    return cast(dict[str, object], operations[0]).__setitem__("extra", 1)


def _receipt_operation_kind(receipt: dict[str, object]) -> object:
    operations = cast(list[object], receipt["operations"])
    return cast(dict[str, object], operations[0]).__setitem__("kind", "rewind")


def _receipt_create_missing_planned_new(receipt: dict[str, object]) -> object:
    operations = cast(list[object], receipt["operations"])
    return cast(dict[str, object], operations[0]).__setitem__("planned_new", None)


def _receipt_first_operation(receipt: dict[str, object]) -> dict[str, object]:
    operations = cast(list[object], receipt["operations"])
    return cast(dict[str, object], operations[0])


def _receipt_planned_content_id(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["planned_new"]).__setitem__(
        "content_id", "zzz"
    )


def _receipt_planned_size(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["planned_new"]).__setitem__("size", -1)


def _receipt_observed_mode_out_of_domain(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__(
        "mode", 0o7777 + 1
    )


def _receipt_observed_mode_boolean(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__("mode", True)


def _receipt_tree_planned_new_extra_key(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_extra_key())


def _receipt_tree_entry_extra_key(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_extra_key())


def _receipt_expected_old_wrong_type(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return operation.__setitem__("expected_old", "x")


def _receipt_planned_new_wrong_type(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return operation.__setitem__("planned_new", "x")


def _receipt_path_beyond_limits(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return operation.__setitem__("path", "a" * 1100)


def _receipt_tree_expected_old_not_null(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_expected_old())


def _receipt_tree_planned_new_wrong_type(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_planned_new_type())


def _receipt_tree_entry_directory_bad_mode(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_bad_mode())


def _receipt_tree_entry_missing_key(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_missing_key())


def _receipt_gate_operation(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["gate_specification"]).__setitem__(
        "operation", "other"
    )


def _receipt_gate_placeholder_not_list(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["gate_specification"]).__setitem__(
        "expected_placeholder", "x"
    )


def _receipt_source_before_wrong_type(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("source_before", "x")


def _receipt_baseline_entries_not_list(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__("entries", "x")


def _receipt_baseline_entry_missing_key(receipt: dict[str, object]) -> object:
    source_after = cast(dict[str, object], receipt["source_after"])
    entries = cast(list[object], source_after["entries"])
    return cast(dict[str, object], entries[0]).pop("sha256")


def _receipt_baseline_entry_bad_mode(receipt: dict[str, object]) -> object:
    source_after = cast(dict[str, object], receipt["source_after"])
    entries = cast(list[object], source_after["entries"])
    return cast(dict[str, object], entries[0]).__setitem__("mode", 0o7777 + 1)


def _receipt_baseline_kind_copier_with_snapshot(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__(
        "kind", "copier"
    )


def _receipt_baseline_bad_snapshot_commit(receipt: dict[str, object]) -> object:
    return cast(dict[str, object], receipt["source_after"]).__setitem__(
        "snapshot_commit", "zzz"
    )


def _receipt_copier_baseline_with_snapshot_commit(receipt: dict[str, object]) -> object:
    receipt.update(_copier_receipt())
    source_after = cast(dict[str, object], receipt["source_after"])
    source_after["snapshot_commit"] = "0" * 40
    return receipt


def _receipt_gate_not_mapping(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("gate_specification", "x")


def _receipt_gate_finding_not_mapping(receipt: dict[str, object]) -> object:
    gate = cast(dict[str, object], receipt["gate_specification"])
    return gate.__setitem__("expected_placeholder", ["x"])


def _receipt_gate_readiness_rule(receipt: dict[str, object]) -> object:
    gate = cast(dict[str, object], receipt["gate_specification"])
    return gate.__setitem__("readiness_rule", "bogus")


def _receipt_tree_duplicate_entry_path(receipt: dict[str, object]) -> object:
    receipt.update(_nested_copier_receipt())
    operations = receipt["operations"]
    assert isinstance(operations, list)
    for operation in cast(list[object], operations):
        assert isinstance(operation, dict)
        operation = cast(dict[str, object], operation)
        if operation.get("kind") != "create_tree":
            continue
        planned_new = operation["planned_new"]
        assert isinstance(planned_new, dict)
        planned_new = cast(dict[str, object], planned_new)
        entries = planned_new["entries"]
        assert isinstance(entries, list)
        entries = cast(list[object], entries)
        if len(entries) >= 2:
            first = entries[0]
            second = entries[1]
            assert isinstance(first, dict) and isinstance(second, dict)
            second_path = cast(dict[str, object], second)
            second_path["path"] = cast(dict[str, object], first)["path"]
            return receipt
    raise AssertionError("no create_tree with two entries")


def _receipt_baseline_entry_not_mapping(receipt: dict[str, object]) -> object:
    source_after = cast(dict[str, object], receipt["source_after"])
    return cast(list[object], source_after["entries"]).__setitem__(0, "x")


def _receipt_gate_subject_not_string(receipt: dict[str, object]) -> object:
    gate = cast(dict[str, object], receipt["gate_specification"])
    placeholders = cast(list[object], gate["expected_placeholder"])
    return cast(dict[str, object], placeholders[0]).__setitem__("subject_at", 5)


def _receipt_operation_path_not_string(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return operation.__setitem__("path", 5)


def _receipt_operation_not_mapping(receipt: dict[str, object]) -> object:
    return cast(list[object], receipt["operations"]).__setitem__(0, "x")


def _receipt_observed_kind(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__(
        "kind", "other"
    )


def _receipt_planned_new_identity_kind(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["planned_new"]).__setitem__(
        "kind", "other"
    )


def _receipt_delete_expected_old_identity_kind(receipt: dict[str, object]) -> object:
    delete = _operation_by_kind(receipt, "delete_file")
    return cast(dict[str, object], delete["expected_old"]).__setitem__("kind", "other")


def _receipt_observed_normalized_digest(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__(
        "normalized_sha256", "zzz"
    )


def _receipt_tree_entry_file_bad_digest(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_bad_digest())


def _receipt_observed_state_extra_key(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__("extra", 1)


def _receipt_observed_size(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["expected_old"]).__setitem__("size", -1)


def _receipt_operations_not_list(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("operations", "x")


def _receipt_planned_content_id_missing(receipt: dict[str, object]) -> object:
    operation = _receipt_first_operation(receipt)
    return cast(dict[str, object], operation["planned_new"]).pop("content_id")


def _receipt_tree_operation_extra_key(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_extra_op_key())


def _receipt_tree_root_unsafe_path(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_bad_root())


def _receipt_tree_planned_new_bad_sha(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_bad_sha())


def _receipt_tree_entry_not_mapping(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_not_mapping())


def _receipt_tree_dir_entry_unsafe_path(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_dir_entry_bad_path())


def _receipt_tree_entry_unknown_kind(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_entry_bad_kind())


def _receipt_tree_file_entry_bad_kind(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_file_entry_bad_kind())


def _receipt_delete_extra_key(receipt: dict[str, object]) -> object:
    delete = _operation_by_kind(receipt, "delete_file")
    return delete.__setitem__("extra", 1)


def _receipt_delete_unsafe_path(receipt: dict[str, object]) -> object:
    delete = _operation_by_kind(receipt, "delete_file")
    return delete.__setitem__("path", "..")


def _receipt_tree_dir_entry_missing_mode(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_dir_entry_missing_mode())


def _receipt_tree_file_entry_unsafe_path(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_file_entry_bad_path())


def _receipt_tree_file_entry_missing_content_id(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_tree_file_entry_missing_id())


def _receipt_remove_empty_extra_key(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_remove_empty_extra_key())


def _receipt_remove_empty_unsafe_path(receipt: dict[str, object]) -> object:
    return receipt.update(_receipt_with_remove_empty_bad_path())


def _receipt_remove_empty_expected_old_not_mapping(
    receipt: dict[str, object],
) -> object:
    return receipt.update(_receipt_with_remove_empty_old_type())


def _receipt_remove_empty_expected_old_mode_not_int(
    receipt: dict[str, object],
) -> object:
    return receipt.update(_receipt_with_remove_empty_old_mode_type())


def _receipt_source_after_null(receipt: dict[str, object]) -> object:
    return receipt.__setitem__("source_after", None)


# Mutators that must also make ``reconstruct_plan`` fail: every branch of the
# reconstruction decoders rejects the same closed-shape violations the strict
# receipt decoder rejects, except the extra-key and already-stubbed top-level
# fields that reconstruction deliberately does not re-validate.
_RECONSTRUCT_REJECTIONS: tuple[Callable[[dict[str, object]], object], ...] = (
    _receipt_target_binding,
    _receipt_generation_path,
    _receipt_baseline_kind,
    _receipt_baseline_fingerprint,
    _receipt_baseline_entries_unsafe_path,
    _receipt_manifest_before,
    _receipt_manifest_after_null,
    _receipt_gate_severity,
    _receipt_gate_operation,
    _receipt_gate_placeholder_not_list,
    _receipt_gate_not_mapping,
    _receipt_gate_finding_not_mapping,
    _receipt_gate_readiness_rule,
    _receipt_tree_duplicate_entry_path,
    _receipt_gate_subject_not_string,
    _receipt_operation_kind,
    _receipt_operation_path_not_string,
    _receipt_operation_not_mapping,
    _receipt_create_missing_planned_new,
    _receipt_planned_content_id,
    _receipt_planned_content_id_missing,
    _receipt_planned_size,
    _receipt_planned_new_wrong_type,
    _receipt_planned_new_identity_kind,
    _receipt_observed_kind,
    _receipt_observed_mode_out_of_domain,
    _receipt_observed_mode_boolean,
    _receipt_observed_normalized_digest,
    _receipt_observed_state_extra_key,
    _receipt_observed_size,
    _receipt_expected_old_wrong_type,
    _receipt_delete_expected_old_identity_kind,
    _receipt_path_beyond_limits,
    _set_delete_planned_new,
    _receipt_delete_unsafe_path,
    _receipt_source_before_wrong_type,
    _receipt_source_after_null,
    _receipt_baseline_entries_not_list,
    _receipt_baseline_entry_missing_key,
    _receipt_baseline_entry_bad_mode,
    _receipt_baseline_entry_not_mapping,
    _receipt_baseline_kind_copier_with_snapshot,
    _receipt_baseline_bad_snapshot_commit,
    _receipt_copier_baseline_with_snapshot_commit,
    _receipt_operations_not_list,
    _receipt_tree_expected_old_not_null,
    _receipt_tree_planned_new_wrong_type,
    _receipt_tree_root_unsafe_path,
    _receipt_tree_planned_new_bad_sha,
    _receipt_tree_entry_not_mapping,
    _receipt_tree_entry_directory_bad_mode,
    _receipt_tree_entry_missing_key,
    _receipt_tree_entry_unknown_kind,
    _receipt_tree_entry_file_bad_digest,
    _receipt_tree_dir_entry_missing_mode,
    _receipt_tree_dir_entry_unsafe_path,
    _receipt_tree_file_entry_bad_kind,
    _receipt_tree_file_entry_unsafe_path,
    _receipt_tree_file_entry_missing_content_id,
    _set_remove_empty_planned_new,
    _set_remove_empty_bad_mode,
    _receipt_remove_empty_unsafe_path,
    _receipt_remove_empty_expected_old_not_mapping,
    _receipt_remove_empty_expected_old_mode_not_int,
)

# The adopted fixture plan contains only create operations, so mutators that
# target delete_file or remove_empty_directory receipts cannot apply to it.
_ADOPTED_SEED_INCOMPATIBLE_MUTATORS = frozenset(
    {
        _receipt_delete_expected_old_identity_kind,
        _set_delete_planned_new,
        _receipt_delete_unsafe_path,
        _set_remove_empty_planned_new,
        _set_remove_empty_bad_mode,
    }
)


def _adopted_reconstruct_matrix() -> tuple[Callable[[dict[str, object]], object], ...]:
    return tuple(
        mutate
        for mutate in _RECONSTRUCT_REJECTIONS
        if mutate not in _ADOPTED_SEED_INCOMPATIBLE_MUTATORS
    )


class TestPlanDigest:
    def test_receipt_round_trip_and_digest_re_derivation(self) -> None:
        receipt = build_receipt(github_plan())
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"receipt decode failed: {error}")
        assert plan_receipt_digest(receipt) == plan_receipt_digest(decoded)

    def test_copier_receipt_round_trip(self) -> None:
        receipt = _copier_receipt()
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"copier receipt decode failed: {error}")
        assert plan_receipt_digest(receipt) == plan_receipt_digest(decoded)

    def test_adopted_receipt_round_trip(self) -> None:
        receipt = _adopted_receipt()
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"adopted receipt decode failed: {error}")
        assert plan_receipt_digest(receipt) == plan_receipt_digest(decoded)

    def test_receipt_contains_no_adopter_legal_or_generated_bytes(self) -> None:
        receipt = build_receipt(github_plan())
        encoded = encode_receipt(receipt)
        assert b"Adopter" not in encoded
        assert b"rygor:placeholder" not in encoded
        assert b"rygor:unconfigured" not in encoded
        assert b"Apache License" not in encoded
        assert b"def test_a" not in encoded
        operations = receipt["operations"]
        assert isinstance(operations, list)
        operations = cast(list[object], operations)
        for operation in operations:
            assert isinstance(operation, dict)
            operation = cast(dict[str, object], operation)
            planned_new = operation.get("planned_new")
            if isinstance(planned_new, dict):
                planned_new = cast(dict[str, object], planned_new)
                assert set(planned_new) == {
                    "kind",
                    "mode",
                    "normalized_sha256",
                    "raw_sha256",
                    "size",
                    "content_id",
                }

    def test_nested_tree_receipt_round_trip(self) -> None:
        receipt = _nested_copier_receipt()
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"nested tree receipt decode failed: {error}")

    def test_receipt_round_trip_with_a_repository_level_finding(self) -> None:
        plan = github_plan()
        finding = Finding(
            "R",
            Repository(),
            "repository",
            "rule",
            "informational",
            "message",
            "inspect",
        )
        plan = replace(
            plan,
            gate_specification=replace(
                plan.gate_specification,
                expected_placeholder=(finding,),
            ),
        )
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(
                    f"repository finding receipt decode failed: {error}"
                )

    def test_receipt_binds_target_identity(self) -> None:
        plan = github_plan()
        other = replace(
            plan, target_identity=target_identity(b"/work/other", device=1, inode=3)
        )
        assert build_receipt(plan) != build_receipt(other)
        assert plan_receipt_digest(build_receipt(plan)) != plan_receipt_digest(
            build_receipt(other)
        )

    def test_receipt_round_trip_with_observed_mode_outside_install_modes(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=tuple(
                replace(
                    entry,
                    state=file_state_identity(
                        entry.content, text=True, mode=PosixMode(0o600)
                    ),
                )
                if entry.path.value == "uv.lock"
                else entry
                for entry in snapshot.files
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        plan = get_plan(result)
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"receipt decode failed: {error}")

    def test_receipt_round_trip_with_binary_observed_state(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=tuple(
                replace(
                    entry,
                    state=file_state_identity(
                        entry.content, text=False, mode=PosixMode.FILE
                    ),
                )
                if entry.path.value == "uv.lock"
                else entry
                for entry in snapshot.files
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        plan = get_plan(result)
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"receipt decode failed: {error}")

    def test_receipt_round_trip_with_observed_directory_mode_outside_install_modes(
        self,
    ) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            directories=tuple(
                replace(
                    entry,
                    state=DirectoryState(PosixMode(0o700), entry.state.entries),
                )
                if entry.path.value == "tests"
                else entry
                for entry in snapshot.directories
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        plan = get_plan(result)
        receipt = build_receipt(plan)
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"receipt decode failed: {error}")

    def test_tampered_receipt_shape_is_rejected(self) -> None:
        receipt = build_receipt(github_plan())
        encoded = bytearray(encode_receipt(receipt))
        marker = b'"content_id":"'
        index = encoded.find(marker) + len(marker)
        assert index > len(marker)
        encoded[index] = ord("X")
        match decode_receipt(bytes(encoded)):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("tampered receipt shape decoded")

    def test_shape_valid_tamper_changes_the_receipt_digest(self) -> None:
        receipt = build_receipt(github_plan())
        encoded = bytearray(encode_receipt(receipt))
        index = encoded.find(b'"README.md"')
        assert index >= 0
        encoded[index + 1 : index + 10] = b"README.txt"
        match decode_receipt(bytes(encoded)):
            case Ok(decoded):
                assert decoded != receipt
                assert plan_receipt_digest(decoded) != plan_receipt_digest(receipt)
            case Err(error):
                raise AssertionError(f"shape-valid tamper rejected: {error}")

    def test_recompiled_plan_derives_the_same_receipt(self) -> None:
        assert plan_receipt_digest(build_receipt(github_plan())) == plan_receipt_digest(
            build_receipt(github_plan())
        )

    @pytest.mark.parametrize(
        ("mutate"),
        [
            pytest.param(_receipt_extra_top_level_key, id="extra top-level key"),
            pytest.param(_receipt_plan_schema, id="plan schema"),
            pytest.param(_receipt_operation_kind_field, id="operation kind"),
            pytest.param(_receipt_target_binding, id="target binding"),
            pytest.param(_receipt_generation_path, id="generation path"),
            pytest.param(_receipt_baseline_kind, id="baseline kind"),
            pytest.param(_receipt_baseline_fingerprint, id="baseline fingerprint"),
            pytest.param(
                _receipt_baseline_entries_unsafe_path,
                id="baseline entries unsafe path",
            ),
            pytest.param(_receipt_manifest_before, id="manifest before"),
            pytest.param(_receipt_manifest_after_null, id="manifest after null"),
            pytest.param(_receipt_gate_missing_key, id="gate missing key"),
            pytest.param(_receipt_gate_severity, id="gate severity"),
            pytest.param(_receipt_gate_subject_path, id="gate subject path"),
            pytest.param(_receipt_operation_extra_key, id="operation extra key"),
            pytest.param(_receipt_operation_kind, id="operation kind"),
            pytest.param(
                _receipt_create_missing_planned_new, id="create missing planned new"
            ),
            pytest.param(_receipt_planned_content_id, id="planned content id"),
            pytest.param(_receipt_planned_size, id="planned size"),
            pytest.param(
                _receipt_observed_mode_out_of_domain, id="observed mode out of domain"
            ),
            pytest.param(_receipt_observed_mode_boolean, id="observed mode boolean"),
            pytest.param(
                _set_delete_planned_new,
                id="delete with planned new",
            ),
            pytest.param(
                _receipt_tree_planned_new_extra_key, id="tree planned new extra key"
            ),
            pytest.param(_receipt_tree_entry_extra_key, id="tree entry extra key"),
            pytest.param(
                _set_remove_empty_planned_new,
                id="remove empty with planned new",
            ),
            pytest.param(
                _set_remove_empty_bad_mode,
                id="remove empty bad mode",
            ),
            pytest.param(
                _receipt_expected_old_wrong_type, id="expected old wrong type"
            ),
            pytest.param(_receipt_planned_new_wrong_type, id="planned new wrong type"),
            pytest.param(_receipt_path_beyond_limits, id="path beyond limits"),
            pytest.param(
                _receipt_tree_expected_old_not_null, id="tree expected old not null"
            ),
            pytest.param(
                _receipt_tree_planned_new_wrong_type, id="tree planned new wrong type"
            ),
            pytest.param(
                _receipt_tree_entry_directory_bad_mode,
                id="tree entry directory bad mode",
            ),
            pytest.param(_receipt_tree_entry_missing_key, id="tree entry missing key"),
            pytest.param(_receipt_gate_operation, id="gate operation"),
            pytest.param(
                _receipt_gate_placeholder_not_list, id="gate placeholder not list"
            ),
            pytest.param(
                _receipt_source_before_wrong_type, id="source before wrong type"
            ),
            pytest.param(
                _receipt_baseline_entries_not_list, id="baseline entries not list"
            ),
            pytest.param(
                _receipt_baseline_entry_missing_key, id="baseline entry missing key"
            ),
            pytest.param(
                _receipt_baseline_entry_bad_mode, id="baseline entry bad mode"
            ),
            pytest.param(
                _receipt_baseline_kind_copier_with_snapshot,
                id="baseline kind copier with snapshot",
            ),
            pytest.param(
                _receipt_baseline_entry_not_mapping, id="baseline entry not mapping"
            ),
            pytest.param(
                _receipt_gate_subject_not_string, id="gate subject not string"
            ),
            pytest.param(
                _receipt_operation_path_not_string, id="operation path not string"
            ),
            pytest.param(_receipt_operation_not_mapping, id="operation not mapping"),
            pytest.param(_receipt_observed_kind, id="observed kind"),
            pytest.param(
                _receipt_planned_new_identity_kind, id="planned new identity kind"
            ),
            pytest.param(
                _receipt_delete_expected_old_identity_kind,
                id="delete expected old identity kind",
            ),
            pytest.param(
                _receipt_observed_normalized_digest, id="observed normalized digest"
            ),
            pytest.param(
                _receipt_tree_entry_file_bad_digest, id="tree entry file bad digest"
            ),
            pytest.param(
                _receipt_observed_state_extra_key, id="observed state extra key"
            ),
            pytest.param(_receipt_observed_size, id="observed size"),
            pytest.param(_receipt_operations_not_list, id="operations not list"),
            pytest.param(
                _receipt_planned_content_id_missing, id="planned content id missing"
            ),
            pytest.param(
                _receipt_tree_operation_extra_key, id="tree operation extra key"
            ),
            pytest.param(_receipt_tree_root_unsafe_path, id="tree root unsafe path"),
            pytest.param(
                _receipt_tree_planned_new_bad_sha, id="tree planned new bad sha"
            ),
            pytest.param(_receipt_tree_entry_not_mapping, id="tree entry not mapping"),
            pytest.param(
                _receipt_tree_dir_entry_missing_mode,
                id="tree directory entry missing mode",
            ),
            pytest.param(
                _receipt_tree_dir_entry_unsafe_path,
                id="tree directory entry unsafe path",
            ),
            pytest.param(
                _receipt_tree_entry_unknown_kind, id="tree entry unknown kind"
            ),
            pytest.param(
                _receipt_tree_file_entry_bad_kind, id="tree file entry bad kind"
            ),
            pytest.param(_receipt_delete_extra_key, id="delete extra key"),
            pytest.param(_receipt_delete_unsafe_path, id="delete unsafe path"),
            pytest.param(
                _receipt_tree_file_entry_unsafe_path, id="tree file entry unsafe path"
            ),
            pytest.param(
                _receipt_tree_file_entry_missing_content_id,
                id="tree file entry missing content id",
            ),
            pytest.param(
                _receipt_tree_duplicate_entry_path, id="tree duplicate entry path"
            ),
            pytest.param(_receipt_remove_empty_extra_key, id="remove empty extra key"),
            pytest.param(
                _receipt_remove_empty_unsafe_path, id="remove empty unsafe path"
            ),
            pytest.param(
                _receipt_remove_empty_expected_old_not_mapping,
                id="remove empty expected old not mapping",
            ),
            pytest.param(
                _receipt_remove_empty_expected_old_mode_not_int,
                id="remove empty expected old mode not int",
            ),
            pytest.param(_receipt_source_after_null, id="source after null"),
        ],
    )
    def test_decode_rejects_malformed_receipts(
        self, mutate: Callable[[dict[str, object]], object]
    ) -> None:
        receipt = build_receipt(github_plan())
        _ = mutate(receipt)
        match decode_receipt(encode_receipt(receipt)):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("malformed receipt decoded")

    def test_decode_receipt_rejects_invalid_json_and_oversize(self) -> None:
        match decode_receipt(b"{not json"):
            case Err(error):
                assert error.kind is ReceiptErrorKind.INVALID_JSON
            case Ok(_):
                raise AssertionError("invalid JSON receipt decoded")
        match decode_receipt(b" " * (16 * 1024 * 1024 + 1)):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("oversized receipt decoded")
        match decode_receipt(b"[1]"):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("non-object receipt decoded")

    def test_receipt_rejects_generation_kind_mismatch(self) -> None:
        receipt = _copier_receipt()
        source_after = receipt["source_after"]
        assert isinstance(source_after, dict)
        source_after["kind"] = "github"
        source_after["snapshot_commit"] = "0" * 40
        match decode_receipt(encode_receipt(receipt)):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("receipt with mismatched generation kind decoded")

    def test_receipt_rejects_github_generation_with_copier_baseline(self) -> None:
        receipt = build_receipt(github_plan())
        source_after = receipt["source_after"]
        assert isinstance(source_after, dict)
        source_after = cast(dict[str, object], source_after)
        source_after["kind"] = "copier"
        _ = source_after.pop("snapshot_commit")
        match decode_receipt(encode_receipt(receipt)):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError(
                    "receipt with github generation and copier baseline decoded"
                )

    def test_reconstruct_github_plan_preserves_operations_and_identities(self) -> None:
        plan = github_plan()
        match reconstruct_plan(build_receipt(plan), target=plan.target_identity):
            case Ok(reconstructed):
                assert reconstructed.ordered_operations == plan.ordered_operations
                assert reconstructed.source_after == plan.source_after
                assert reconstructed.source_before == plan.source_before
                assert reconstructed.manifest_after.digest == plan.manifest_after.digest
                assert reconstructed.manifest_before == plan.manifest_before
                assert reconstructed.gate_specification.operation == "initial"
                assert [
                    finding.code
                    for finding in reconstructed.gate_specification.expected_placeholder
                ] == [
                    finding.code
                    for finding in plan.gate_specification.expected_placeholder
                ]
            case Err(error):
                raise AssertionError(f"github plan reconstruction failed: {error}")

    def test_reconstruct_copier_plan_preserves_tree_operations(self) -> None:
        match reconstruct_plan(_copier_receipt(), target=TARGET):
            case Ok(reconstructed):
                assert reconstructed.generation_path is GenerationPath.COPIER
                assert any(
                    isinstance(operation, CreateTreeOperation)
                    for operation in reconstructed.ordered_operations
                )
            case Err(error):
                raise AssertionError(f"copier plan reconstruction failed: {error}")

    def test_reconstruct_nested_tree_preserves_directory_entries(self) -> None:
        match reconstruct_plan(_nested_copier_receipt(), target=TARGET):
            case Ok(reconstructed):
                trees = [
                    operation
                    for operation in reconstructed.ordered_operations
                    if isinstance(operation, CreateTreeOperation)
                ]
                assert trees
                assert any(
                    isinstance(entry, PlannedDirectoryEntry)
                    for tree in trees
                    for entry in tree.planned_new.entries
                )
            case Err(error):
                raise AssertionError(f"nested tree reconstruction failed: {error}")

    def test_reconstruct_preserves_a_repository_level_finding(self) -> None:
        plan = github_plan()
        plan = replace(
            plan,
            gate_specification=replace(
                plan.gate_specification,
                expected_placeholder=(
                    Finding(
                        "R",
                        Repository(),
                        "repository",
                        "rule",
                        "informational",
                        "message",
                        "inspect",
                    ),
                ),
            ),
        )
        match reconstruct_plan(build_receipt(plan), target=plan.target_identity):
            case Ok(reconstructed):
                finding = reconstructed.gate_specification.expected_placeholder[0]
                assert finding.code == "R"
                assert isinstance(finding.subject_at, Repository)
            case Err(error):
                raise AssertionError(
                    f"repository finding reconstruction failed: {error}"
                )

    def test_reconstruct_rejects_a_different_target_binding(self) -> None:
        plan = github_plan()
        other = replace(
            plan, target_identity=target_identity(b"/work/other", device=1, inode=3)
        )
        match reconstruct_plan(build_receipt(plan), target=other.target_identity):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("reconstruction bound a different target")

    def test_reconstruct_honors_caller_supplied_path_limits(self) -> None:
        receipt = build_receipt(github_plan())
        tight = replace(DEFAULT_LIMITS, max_path_bytes=8)
        match reconstruct_plan(receipt, target=TARGET, limits=tight):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("tighter path limits ignored")

    @pytest.mark.parametrize("mutate", _RECONSTRUCT_REJECTIONS)
    def test_reconstruct_rejects_malformed_receipts(
        self, mutate: Callable[[dict[str, object]], object]
    ) -> None:
        receipt = build_receipt(github_plan())
        _ = mutate(receipt)
        match reconstruct_plan(receipt, target=TARGET):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("malformed receipt reconstructed")

    _ADOPTED_RECONSTRUCT_REJECTIONS: tuple[
        Callable[[dict[str, object]], object], ...
    ] = _adopted_reconstruct_matrix()

    @pytest.mark.parametrize("mutate", _ADOPTED_RECONSTRUCT_REJECTIONS)
    def test_reconstruct_rejects_malformed_adopted_receipts(
        self, mutate: Callable[[dict[str, object]], object]
    ) -> None:
        receipt = _adopted_receipt()
        _ = mutate(receipt)
        match reconstruct_plan(receipt, target=TARGET):
            case Err(error):
                assert error.kind is ReceiptErrorKind.SCHEMA_VIOLATION
            case Ok(_):
                raise AssertionError("malformed adopted receipt reconstructed")


class TestExpectedTarget:
    def test_expected_readiness_includes_predicted_placeholder_findings(self) -> None:
        plan = github_plan()
        predicted = plan.gate_specification.expected_placeholder
        assert predicted == predicted_placeholder_findings(fixture_answers().slots)
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        evaluated = evaluate_slot_readiness(expected)
        predicted_identities = {finding.identity() for finding in predicted}
        evaluated_identities = {finding.identity() for finding in evaluated.findings}
        assert predicted_identities <= evaluated_identities
        assert {finding.code for finding in predicted} == {
            "READINESS_PRD_MARKER",
            "READINESS_SECURITY_MARKER",
            "READINESS_CONTRIBUTING_MARKER",
            "READINESS_HOOK_SENTINEL",
        }

    def test_file_slots_produce_no_readiness_findings(self) -> None:
        plan = github_plan()
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        evaluated = evaluate_slot_readiness(expected)
        assert all(
            finding.code != "READINESS_README_MARKER" for finding in evaluated.findings
        )

    def test_expected_contract_passes_for_complete_scaffold(self) -> None:
        plan = github_plan()
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        match evaluate_expected(expected):
            case ExpectedGatePass():
                pass
            case ExpectedGateRefusal(failures=failures):
                raise AssertionError(f"contract refused: {failures}")

    def test_expected_contract_refusal_on_missing_required_file(self) -> None:
        snapshot = github_snapshot()
        snapshot = replace(
            snapshot,
            files=tuple(
                entry
                for entry in snapshot.files
                if entry.path.value != "docs/agents/domain.md"
            ),
        )
        _, result = compile_fixture(snapshot=snapshot)
        plan = get_plan(result)
        match apply_plan(snapshot, plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        match evaluate_expected(expected):
            case ExpectedGateRefusal(failures=failures):
                assert any(
                    "missing required file: docs/agents/domain.md" in failure.details
                    for failure in failures
                )
            case ExpectedGatePass():
                raise AssertionError("missing required file passed the contract")

    def test_gate_specification_is_attached_to_the_plan(self) -> None:
        gate = github_plan().gate_specification
        assert gate.operation == "initial"
        assert gate.artifact_verification is True
        assert gate.template_contract is True
        assert gate.readiness_rule.value == "initial-equality"

    def test_apply_plan_rejects_a_changed_snapshot(self) -> None:
        plan = github_plan()
        changed = github_snapshot()
        changed = replace(
            changed,
            files=tuple(
                entry for entry in changed.files if entry.path.value != "README.md"
            ),
        )
        match apply_plan(changed, plan):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("changed snapshot overlaid")

    def test_apply_plan_rejects_a_missing_removal_target(self) -> None:
        plan = github_plan()
        changed = github_snapshot()
        changed = replace(
            changed,
            directories=tuple(
                entry for entry in changed.directories if entry.path.value != "tests"
            ),
        )
        match apply_plan(changed, plan):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("missing removal target overlaid")

    def test_apply_plan_skips_absent_observed_files(self) -> None:
        snapshot = github_snapshot()
        absent = _sorted_snapshot(
            (
                *snapshot.files,
                ObservedFileEntry(
                    path=RepoPath("docs/absent.md"),
                    state=FileState(None, None),
                    content=b"",
                ),
            ),
            snapshot.directories,
        )
        plan = get_plan(compile_fixture(snapshot=absent)[1])
        match apply_plan(absent, plan):
            case Ok(expected):
                assert all(
                    file.path.value != "docs/absent.md" for file in expected.files
                )
            case Err(error):
                raise AssertionError(f"absent observed file broke the overlay: {error}")

    def test_slot_readiness_reports_missing_and_invalid_text_files(self) -> None:
        plan = github_plan()
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        without_readme = replace(
            expected,
            files=tuple(
                file for file in expected.files if file.path.value != "README.md"
            ),
        )
        missing_findings = evaluate_slot_readiness(without_readme).findings
        assert any(
            finding.code == "READINESS_MISSING_FILE" and finding.subject == "README.md"
            for finding in missing_findings
        )
        assert not any(
            finding.code.startswith("READINESS_README_") for finding in missing_findings
        )
        invalid_utf8 = replace(
            expected,
            files=tuple(
                replace(file, content=b"\xff\xfe not utf8")
                if file.path.value == "README.md"
                else file
                for file in expected.files
            ),
        )
        invalid_findings = evaluate_slot_readiness(invalid_utf8).findings
        assert any(
            finding.code == "INTERNAL_READINESS_ERROR"
            and finding.subject == "README.md"
            for finding in invalid_findings
        )
        assert not any(
            finding.code.startswith("READINESS_README_") for finding in invalid_findings
        )
        marked = replace(
            expected,
            files=tuple(
                replace(
                    file,
                    content=b"<!-- rygor:placeholder:readme -->\n",
                )
                if file.path.value == "README.md"
                else file
                for file in expected.files
            ),
        )
        assert any(
            finding.code == "READINESS_README_MARKER"
            for finding in evaluate_slot_readiness(marked).findings
        )

    def test_apply_plan_rejects_a_duplicate_create_over_a_tree_entry(self) -> None:
        snapshot = fixture_copier_snapshot()
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
        )
        plan = get_plan(result)
        tree = next(
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
            and operation.root.value == "docs"
        )
        planned_file = next(
            entry
            for entry in tree.planned_new.entries
            if isinstance(entry, PlannedFileEntry)
        )
        duplicate = CreateFileOperation(
            path=planned_file.path,
            expected_old=FileState(None, None),
            planned_new=PlannedFilePresent(
                identity=planned_file.identity,
                mode=planned_file.mode,
                content_id=planned_file.content_id,
            ),
        )
        tampered = replace(
            plan, ordered_operations=(*plan.ordered_operations, duplicate)
        )
        match apply_plan(snapshot, tampered):
            case Err(error):
                assert error.kind is PlanInvariantErrorKind.UNMATCHED_PRECONDITION
            case Ok(_):
                raise AssertionError("duplicate create over a tree entry overlaid")

    def test_apply_plan_registers_each_tree_root_in_directories(self) -> None:
        snapshot = fixture_copier_snapshot()
        _, result = compile_fixture(
            generation=GenerationPath.COPIER,
            snapshot=snapshot,
            cleanup=None,
            snapshot_commit=None,
        )
        plan = get_plan(result)
        tree_roots = tuple(
            operation.root.value
            for operation in plan.ordered_operations
            if isinstance(operation, CreateTreeOperation)
        )
        assert tree_roots  # the Copier fixture stages wholly new hierarchies
        match apply_plan(snapshot, plan):
            case Ok(expected):
                expected_dirs = {
                    entry.path.value: entry for entry in expected.directories
                }
                for root in tree_roots:
                    assert root in expected_dirs, f"tree root {root} not overlaid"
                    assert expected_dirs[root].mode is PosixMode.DIRECTORY
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")


def _operation_paths(plan: OperationPlan) -> set[str]:
    paths: set[str] = set()
    for operation in plan.ordered_operations:
        match operation:
            case CreateTreeOperation():
                paths.add(operation.root.value)
                paths.update(
                    entry.path.value for entry in operation.planned_new.entries
                )
            case _:
                paths.add(operation.path.value)
    return paths


class TestAdoptionCollisions:
    """Conflict-aware partitioning for adoption installs (US-3/US-4/US-5/US-8)."""

    def _copier_plus(self, *files: ObservedFileEntry) -> TargetSnapshot:
        base = fixture_copier_snapshot()
        return _sorted_snapshot((*base.files, *files), base.directories)

    def _adopted(
        self,
        *,
        snapshot: TargetSnapshot,
        collisions: Mapping[str, str] | None,
    ) -> Result[OperationPlan, CompileError]:
        _, result = compile_fixture(
            generation=GenerationPath.ADOPTED,
            snapshot=snapshot,
            cleanup=None,
            collisions=cast(
                Mapping[str, Literal["keep-existing", "replace"]] | None, collisions
            ),
        )
        return result

    def test_absent_outputs_compile_identically_with_empty_declarations(self) -> None:
        snapshot = fixture_copier_snapshot()
        _, plain = compile_fixture(
            generation=GenerationPath.ADOPTED,
            snapshot=snapshot,
            cleanup=None,
        )
        _, declared = compile_fixture(
            generation=GenerationPath.ADOPTED,
            snapshot=snapshot,
            cleanup=None,
            collisions={},
        )
        assert build_receipt(get_plan(declared)) == build_receipt(get_plan(plain))

    def test_keep_existing_paths_leave_operations_and_inventory(self) -> None:
        managed_path = RepoPath("pyproject.toml")
        snapshot = self._copier_plus(
            observed_file(managed_path, SOURCE_PYPROJECT),
            observed_file(RepoPath("README.md"), b"# My own project\n"),
            observed_file(RepoPath("LICENSE"), b"Custom license text\n"),
        )
        result = self._adopted(
            snapshot=snapshot,
            collisions={
                managed_path.value: "keep-existing",
                "README.md": "keep-existing",
                "LICENSE": "keep-existing",
            },
        )
        plan = get_plan(result)
        touched = _operation_paths(plan)
        assert "pyproject.toml" not in touched
        assert "README.md" not in touched
        assert "LICENSE" not in touched
        match decode_manifest(plan.manifest_after.payload):
            case Ok(candidate):
                inventory = {entry.path.value for entry in candidate.managed}
            case Err(error):
                raise AssertionError(f"manifest decode failed: {error}")
        assert "pyproject.toml" not in inventory
        assert ".github/workflows/ci.yml" in inventory
        assert "docs/template-updates.md" in inventory

    def test_replace_declaration_compiles_with_prior_file_state(self) -> None:
        managed_path = RepoPath("pyproject.toml")
        observed = observed_file(managed_path, SOURCE_PYPROJECT)
        snapshot = self._copier_plus(observed)
        result = self._adopted(
            snapshot=snapshot,
            collisions={managed_path.value: "replace"},
        )
        plan = get_plan(result)
        assert not any(
            isinstance(operation, CreateFileOperation)
            and operation.path == managed_path
            for operation in plan.ordered_operations
        )
        replacement = next(
            operation
            for operation in plan.ordered_operations
            if isinstance(operation, ReplaceFileOperation)
            and operation.path == managed_path
        )
        assert replacement.expected_old == observed.state
        managed_content = next(
            content
            for path, _kind, content in MANAGED_CONTENTS
            if path == managed_path.value
        )
        assert replacement.planned_new.identity.raw_sha256 == sha256_hex(
            managed_content
        )

    def test_undeclared_collisions_refuse_naming_every_offender(self) -> None:
        snapshot = self._copier_plus(
            observed_file(RepoPath("pyproject.toml"), SOURCE_PYPROJECT),
            observed_file(RepoPath("README.md"), b"# Mine\n"),
            observed_file(RepoPath("LICENSE"), b"Custom license\n"),
        )
        result = self._adopted(
            snapshot=snapshot,
            collisions={"README.md": "replace"},
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.UNDECLARED_COLLISION
                assert set(error.subject.split(",")) == {"pyproject.toml", "LICENSE"}
                assert error.subject.split(",") == sorted(
                    error.subject.split(","), key=lambda value: value.encode("utf-8")
                )
            case Ok(_):
                raise AssertionError("undeclared collisions compiled a plan")

    def test_declaration_on_non_colliding_path_is_unmatched(self) -> None:
        # A planned but absent path has no collision to declare.
        result = self._adopted(
            snapshot=fixture_copier_snapshot(),
            collisions={"pyproject.toml": "keep-existing"},
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.UNMATCHED_DECLARATION
                assert error.subject == "pyproject.toml"
            case Ok(_):
                raise AssertionError("an unmatched declaration compiled a plan")
        # A path outside the planned inventory is equally unmatched.
        result = self._adopted(
            snapshot=fixture_copier_snapshot(),
            collisions={"unrelated.txt": "keep-existing"},
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.UNMATCHED_DECLARATION
                assert error.subject == "unrelated.txt"
            case Ok(_):
                raise AssertionError("an unmatched declaration compiled a plan")

    def test_replace_on_legal_path_is_structurally_rejected(self) -> None:
        snapshot = self._copier_plus(observed_file(RepoPath("LICENSE"), b"Custom\n"))
        result = self._adopted(
            snapshot=snapshot,
            collisions={"LICENSE": "replace"},
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.ILLEGAL_REPLACE_TARGET
                assert error.subject == "LICENSE"
            case Ok(_):
                raise AssertionError("legal replace target compiled a plan")

    def test_lifecycle_install_requires_the_declare_policy(self) -> None:
        lifecycle = fixture_managed()
        _, result = compile_fixture(
            generation=GenerationPath.ADOPTED,
            snapshot=fixture_copier_snapshot(),
            cleanup=None,
            lifecycle=lifecycle,
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.INVALID_TARGET
                assert error.subject == "lifecycle"
            case Ok(_):
                raise AssertionError("lifecycle installation without declarations")

    def test_adoption_compilation_is_deterministic(self) -> None:
        snapshot = self._copier_plus(
            observed_file(RepoPath("pyproject.toml"), SOURCE_PYPROJECT)
        )
        collisions: dict[str, str] = {"pyproject.toml": "replace"}
        first = get_plan(self._adopted(snapshot=snapshot, collisions=collisions))
        second = get_plan(self._adopted(snapshot=snapshot, collisions=collisions))
        assert build_receipt(first) == build_receipt(second)
        assert first.ordered_operations == second.ordered_operations

    def test_lifecycle_path_colliding_by_case_with_managed_is_refused(self) -> None:
        lifecycle = (
            ManagedFile(
                path=RepoPath("PYPROJECT.toml"),
                kind="text",
                mode=PosixMode.FILE,
                content=b'[project]\nname = "example"\n',
            ),
        )
        _, result = compile_fixture(
            generation=GenerationPath.ADOPTED,
            snapshot=fixture_copier_snapshot(),
            cleanup=None,
            lifecycle=lifecycle,
            collisions={},
        )
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PATH_COLLISION
                assert error.subject == "PYPROJECT.toml"
            case Ok(_):
                raise AssertionError("a case-variant lifecycle output compiled")
