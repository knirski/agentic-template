"""Tests for the candidate manifest, complete initial planner, and plan digest."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from types import MappingProxyType
from typing import Literal

from scripts.bootstrap.blobs import ContentId, VerifiedBlobStore
from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.identity import (
    DirectoryState,
    FileEntry,
    PosixMode,
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
    ManifestAdditions,
    ManifestAnswers,
    ManifestErrorKind,
    ProfileSelection,
    ProjectFacts,
    ProvenanceRecord,
    build_candidate_manifest,
    decode_manifest,
    encode_manifest,
    manifest_checksum,
    manifest_document,
)
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.plan_digest import (
    ReceiptErrorKind,
    build_receipt,
    decode_receipt,
    encode_receipt,
    plan_receipt_digest,
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
    ExpectedGatePass,
    ExpectedGateRefusal,
    FileState,
    MaintenanceDecision,
    ObservedDirectoryEntry,
    ObservedFileEntry,
    OperationPlan,
    PlanInvariantErrorKind,
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
from scripts.bootstrap.render import ManagedFile, ManagedInventoryEntry, SlotContent
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.source_baseline import (
    CopierSourceBaseline,
    GitHubSourceBaseline,
    LifecycleSourceEntry,
)
from scripts.bootstrap.state import CleanupContract
from scripts.bootstrap.template_contract import REQUIRED_FILES, REQUIRED_SKILLS

SLOT_CONTENTS: dict[str, bytes] = {
    "readme": b"# Example\n\nReal project description.\n",
    "prd": b"<!-- agentic-template:placeholder:prd -->\n# Product\n",
    "security_policy": b"<!-- agentic-template:placeholder:security -->\n",
    "contributing": b"<!-- agentic-template:placeholder:contributing -->\n",
    "validation_hook": b"#!/usr/bin/env python3\nagentic-template:unconfigured:validate-project\n",
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
SOURCE_PYPROJECT = b'[project]\nname = "agentic-template"\n'
INVENTORY = b'{"schema_version": 1, "entries": []}\n'
TARGET = target_identity(b"/work/example", device=1, inode=2)


def slot_paths() -> dict[str, RepoPath]:
    return {rule.slot: rule.path for rule in SLOT_PLACEHOLDER_RULES}


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
    skip = {rule.path.value for rule in SLOT_PLACEHOLDER_RULES} | {
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
        observed_directory(RepoPath(".agentic-template")),
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
    )
    return blobs, result


def get_plan(result: Result[OperationPlan, CompileError]) -> OperationPlan:
    assert isinstance(result, Ok), f"expected a compiled plan, got {result}"
    return result.value


def github_plan() -> OperationPlan:
    _, result = compile_fixture()
    return get_plan(result)


def github_snapshot() -> TargetSnapshot:
    return fixture_github_snapshot(licensing_mode="retain-apache-2.0")


class TestManifest:
    def _github_manifest_value(self) -> CandidateManifest:
        provenance = ProvenanceRecord(
            generation_path=GenerationPath.GITHUB,
            maintenance=MaintenanceRecord(status="clean"),
            source_baseline=GitHubSourceBaseline(
                kind="github",
                fingerprint=sha256_hex(b"source"),
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
        assert b"<!-- agentic-template:placeholder:prd -->" not in encoded
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
        document["managed"] = [dict(managed_entry[0]), dict(managed_entry[0])]
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

    def test_retain_mode_records_no_license_digest(self) -> None:
        assert self._github_manifest_value().answers.licensing.content_sha256 is None


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
        op_paths = set()
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
        assert {tree.root.value for tree in trees} == {"docs", ".agentic-template"}
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
        assert by_path["docs/prd.md"].startswith(
            b"<!-- agentic-template:placeholder:prd -->"
        )
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
        assert {tree.root.value for tree in trees} == {"docs", ".agentic-template"}
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

    def test_file_slot_rejects_marker_in_planned_bytes(self) -> None:
        marked_readme = b"<!-- agentic-template:placeholder:readme -->\n"
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

    def test_cleanup_managed_collision_is_refused(self) -> None:
        cleanup = replace(
            fixture_cleanup(),
            cleanup_paths=(*CLEANUP_PATHS, RepoPath("docs/template-updates.md")),
        )
        _, result = compile_fixture(cleanup=cleanup)
        match result:
            case Err(error):
                assert error.kind is CompileErrorKind.PATH_COLLISION
            case Ok(_):
                raise AssertionError("cleanup/managed collision compiled")

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


class TestPlanDigest:
    def test_receipt_round_trip_and_digest_re_derivation(self) -> None:
        receipt = build_receipt(github_plan())
        match decode_receipt(encode_receipt(receipt)):
            case Ok(decoded):
                assert decoded == receipt
            case Err(error):
                raise AssertionError(f"receipt decode failed: {error}")
        assert plan_receipt_digest(receipt) == plan_receipt_digest(decoded)

    def test_receipt_contains_no_adopter_legal_or_generated_bytes(self) -> None:
        receipt = build_receipt(github_plan())
        encoded = encode_receipt(receipt)
        assert b"Adopter" not in encoded
        assert b"agentic-template:placeholder" not in encoded
        assert b"agentic-template:unconfigured" not in encoded
        assert b"Apache License" not in encoded
        assert b"def test_a" not in encoded
        operations = receipt["operations"]
        assert isinstance(operations, list)
        for operation in operations:
            assert isinstance(operation, dict)
            planned_new = operation.get("planned_new")
            if isinstance(planned_new, dict):
                assert set(planned_new) == {
                    "kind",
                    "mode",
                    "normalized_sha256",
                    "raw_sha256",
                    "size",
                    "content_id",
                }

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


class TestExpectedTarget:
    def test_expected_readiness_matches_predicted_placeholder_findings(self) -> None:
        plan = github_plan()
        predicted = plan.gate_specification.expected_placeholder
        assert predicted == predicted_placeholder_findings(fixture_answers().slots)
        match apply_plan(github_snapshot(), plan):
            case Ok(expected):
                pass
            case Err(error):
                raise AssertionError(f"apply_plan failed: {error}")
        evaluated = evaluate_slot_readiness(expected)
        assert evaluated.findings == predicted
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
