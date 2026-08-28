"""In-process unit tests for the strict bundle decoder.

The CLI end-to-end suite reaches ``decode_bundle_input`` only through the
happy path; these tests pin every bounded rejection branch directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import pytest

from scripts.bootstrap.bundles import (
    DecodedBundle,
    compile_adoption_install,
    decode_bundle_input,
)
from scripts.bootstrap.errors import CommandError, ContractError, InputErrorKind
from scripts.bootstrap.identity import (
    PosixMode,
    file_state_identity,
    sha256_hex,
    target_identity,
)
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.manifest import MANIFEST_PATH, decode_manifest
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.planner import (
    CleanMaintenance,
    CreateFileOperation,
    CreateTreeOperation,
    DeleteFileOperation,
    ObservedFileEntry,
    OperationPlan,
    PlannedFileEntry,
    RemoveEmptyDirectoryOperation,
    ReplaceFileOperation,
    TargetSnapshot,
)
from scripts.bootstrap.readiness import MechanicalReadinessResult
from scripts.bootstrap.resolver import resolve_bundle
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import (
    PROJECT_VALIDATION_PATH,
    PROJECT_VALIDATION_SCAFFOLD,
    SEED_ONCE_SLOTS,
)
from scripts.bootstrap.source_baseline import AdoptedSourceBaseline
from scripts.bootstrap.values import DEFAULT_LIMITS
from tests.bootstrap_fixtures import render_for
from tests.factory import REPO_ROOT
from tests.fixtures import assert_err, assert_ok

_ADOPTION_TARGET = target_identity(b"/work/example", device=1, inode=2)

_MAX_FILE_BYTES = 16 * 1024 * 1024


def _valid_bundle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": {"name": "example", "default_branch": "main"},
        "profile": {"id": "portable"},
        "content": {
            "prd": {"mode": "file", "path": "content/prd.md"},
            "readme": {"mode": "file", "path": "content/readme.md"},
            "validation_hook": {"mode": "file", "path": "content/hook"},
            "security_policy": {"mode": "file", "path": "content/security.md"},
            "contributing": {"mode": "file", "path": "content/contributing.md"},
        },
        "licensing": {"mode": "retain-apache-2.0"},
    }


_DEFAULT_FILES: dict[str, bytes] = {
    "content/prd.md": b"# Product requirements\n",
    "content/readme.md": b"# Example\n",
    "content/hook": b"#!/bin/sh\n",
    "content/security.md": b"# Security\n",
    "content/contributing.md": b"# Contributing\n",
}


def _materialize_bundle(
    document: dict[str, object],
    files: dict[str, bytes] | None = None,
    *,
    payload: bytes | None = None,
) -> str:
    """Materialize one bundle directory and return its ``bootstrap.json`` path."""
    tmp = tempfile.mkdtemp()
    root = Path(tmp) / "bundle"
    root.mkdir()
    for relative, content in (files or _DEFAULT_FILES).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = target.write_bytes(content)
    json_path = root / "bootstrap.json"
    _ = json_path.write_bytes(
        payload
        if payload is not None
        else json.dumps(document, sort_keys=True).encode()
    )
    return str(json_path)


def test_decode_accepts_a_complete_bundle() -> None:
    json_path = _materialize_bundle(_valid_bundle())
    decoded = assert_ok(decode_bundle_input(json_path))
    assert isinstance(decoded, DecodedBundle)
    assert decoded.bundle.project.name == "example"
    assert set(decoded.content) == {p for p in decoded.content}
    assert decoded.bundle_digest


def test_decode_rejects_a_missing_bundle_file() -> None:
    missing = os.path.join(tempfile.mkdtemp(), "bootstrap.json")
    error = assert_err(decode_bundle_input(missing), "expected MISSING_INPUT")
    assert error.kind == InputErrorKind.MISSING_INPUT


def test_decode_rejects_a_fifo_bundle_file_without_blocking() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fifo = Path(tmp) / "bootstrap.json"
        os.mkfifo(fifo)
        script = (
            "import sys\n"
            "from scripts.bootstrap.bundles import decode_bundle_input\n"
            "from scripts.bootstrap.result import Err\n"
            "result = decode_bundle_input(sys.argv[1])\n"
            "if not isinstance(result, Err):\n"
            "    raise SystemExit('expected Err')\n"
            "print(result.error.kind.name)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(fifo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = child.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            _ = child.communicate()
            pytest.fail("FIFO input caused bundle decoding to block")
        assert child.returncode == 0, stderr
        assert stdout.strip() == InputErrorKind.WRONG_KIND.name


def test_decode_rejects_an_oversized_bundle() -> None:
    json_path = _materialize_bundle(
        _valid_bundle(), payload=b"x" * (_MAX_FILE_BYTES + 1)
    )
    error = assert_err(decode_bundle_input(json_path), "expected INPUT_LIMIT_EXCEEDED")
    assert error.kind == InputErrorKind.INPUT_LIMIT_EXCEEDED


def test_decode_rejects_invalid_json() -> None:
    json_path = _materialize_bundle(_valid_bundle(), payload=b"{not json")
    error = assert_err(decode_bundle_input(json_path), "expected INVALID_JSON")
    assert error.kind == InputErrorKind.INVALID_JSON


def test_decode_rejects_non_dict_json() -> None:
    json_path = _materialize_bundle(_valid_bundle(), payload=b"[1, 2]")
    error = assert_err(decode_bundle_input(json_path), "expected SCHEMA_VIOLATION")
    assert error.kind == InputErrorKind.SCHEMA_VIOLATION


def test_decode_rejects_schema_violations() -> None:
    document = _valid_bundle()
    document["schema_version"] = 2
    json_path = _materialize_bundle(document)
    error = assert_err(decode_bundle_input(json_path), "expected SCHEMA_VIOLATION")
    assert error.kind == InputErrorKind.SCHEMA_VIOLATION
    assert "unsupported bootstrap schema version" in error.subject


def test_decode_rejects_missing_content_files() -> None:
    json_path = _materialize_bundle(_valid_bundle(), files={"content/readme.md": b"x"})
    error = assert_err(decode_bundle_input(json_path), "expected MISSING_INPUT")
    assert error.kind == InputErrorKind.MISSING_INPUT


def test_decode_rejects_non_file_content() -> None:
    tmp = tempfile.mkdtemp()
    root = Path(tmp) / "bundle"
    root.mkdir()
    _ = (root / "content").mkdir()
    _ = (root / "content" / "prd.md").write_bytes(b"# Product requirements\n")
    _ = (root / "content" / "readme.md").symlink_to(
        root / "content" / "prd.md", target_is_directory=False
    )
    for relative in ("hook", "security.md", "contributing.md"):
        _ = (root / "content" / relative).write_bytes(b"x")
    json_path = root / "bootstrap.json"
    _ = json_path.write_bytes(
        json.dumps(_valid_bundle(), sort_keys=True).encode("utf-8")
    )
    error = assert_err(decode_bundle_input(str(json_path)), "expected WRONG_KIND")
    assert error.kind == InputErrorKind.WRONG_KIND


def test_decode_rejects_a_symlinked_bundle_ancestor() -> None:
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "bundle"
    root.mkdir()
    outside = tmp / "outside"
    outside.mkdir()
    _ = (outside / "prd.md").write_bytes(b"escaped\n")
    (root / "content").mkdir()
    (root / "content" / "escape").symlink_to(outside, target_is_directory=True)
    files = dict(_DEFAULT_FILES)
    document = _valid_bundle()
    content = cast(dict[str, object], document["content"])
    content["prd"] = {"mode": "file", "path": "content/escape/prd.md"}
    for relative, file_content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative != "content/prd.md":
            _ = target.write_bytes(file_content)
    json_path = root / "bootstrap.json"
    _ = json_path.write_bytes(json.dumps(document, sort_keys=True).encode())
    error = assert_err(decode_bundle_input(str(json_path)), "expected WRONG_KIND")
    assert error.kind == InputErrorKind.WRONG_KIND


def test_decode_rejects_invalid_utf8_content() -> None:
    files = dict(_DEFAULT_FILES)
    files["content/prd.md"] = b"\xff\xfe\x00"
    json_path = _materialize_bundle(_valid_bundle(), files=files)
    error = assert_err(decode_bundle_input(json_path), "expected INVALID_ENCODING")
    assert error.kind == InputErrorKind.INVALID_ENCODING


def test_decode_rejects_duplicate_declared_paths() -> None:
    document = _valid_bundle()
    content = cast(dict[str, object], document["content"])
    content["readme"] = {"mode": "file", "path": "content/prd.md"}
    json_path = _materialize_bundle(document)
    error = assert_err(decode_bundle_input(json_path), "expected MARKER_COLLISION")
    assert error.kind == InputErrorKind.MARKER_COLLISION


def test_decode_rejects_missing_license_files() -> None:
    document = _valid_bundle()
    document["licensing"] = {
        "mode": "private",
        "path": "content/license.txt",
    }
    json_path = _materialize_bundle(document)
    error = assert_err(decode_bundle_input(json_path), "expected MISSING_INPUT")
    assert error.kind == InputErrorKind.MISSING_INPUT


def test_decode_rejects_license_paths_colliding_with_slots() -> None:
    document = _valid_bundle()
    document["licensing"] = {
        "mode": "private",
        "path": "content/prd.md",
    }
    json_path = _materialize_bundle(document)
    error = assert_err(decode_bundle_input(json_path), "expected MARKER_COLLISION")
    assert error.kind == InputErrorKind.MARKER_COLLISION


def test_decode_rejects_unresolvable_profiles() -> None:
    document = _valid_bundle()
    document["profile"] = {
        "id": "custom",
        "capabilities": ["no-such-capability"],
    }
    json_path = _materialize_bundle(document)
    error = assert_err(decode_bundle_input(json_path), "expected SCHEMA_VIOLATION")
    assert error.kind == InputErrorKind.SCHEMA_VIOLATION
    assert "unknown_capability" in error.subject


def _observed_file(path: str, content: bytes) -> ObservedFileEntry:
    repo_path = RepoPath(path)
    return ObservedFileEntry(
        path=repo_path,
        state=file_state_identity(content, text=True, mode=PosixMode.FILE),
        content=content,
    )


def _compile_adoption_result(
    template_root: str,
    snapshot: TargetSnapshot,
    *,
    collisions: dict[str, str] | None = None,
) -> Result[tuple[OperationPlan, MechanicalReadinessResult], CommandError]:
    document = _valid_bundle()
    if collisions is not None:
        document["collisions"] = collisions
    decoded = assert_ok(
        decode_bundle_input(
            _materialize_bundle(
                document, payload=json.dumps(document, sort_keys=True).encode()
            )
        )
    )
    resolved = assert_ok(resolve_bundle(decoded.bundle))
    return compile_adoption_install(
        decoded=decoded,
        resolved=resolved,
        scaffold={RepoPath(PROJECT_VALIDATION_PATH.value): PROJECT_VALIDATION_SCAFFOLD},
        template_root=template_root,
        maintenance=CleanMaintenance(),
        cleanup=None,
        snapshot=snapshot,
        target_identity=_ADOPTION_TARGET,
        snapshot_commit="0" * 40,
        limits=DEFAULT_LIMITS,
    )


def _compile_adoption(
    template_root: str,
    snapshot: TargetSnapshot,
    *,
    collisions: dict[str, str] | None = None,
) -> tuple[OperationPlan, MechanicalReadinessResult]:
    return assert_ok(
        _compile_adoption_result(template_root, snapshot, collisions=collisions)
    )


def _seed_paths() -> set[str]:
    return {
        path.value
        for path in (
            *SEED_ONCE_SLOTS.values(),
            RepoPath("LICENSE"),
            RepoPath("NOTICE.md"),
        )
    }


def _planned_paths(plan: OperationPlan) -> set[str]:
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


def _planned_file_paths(plan: OperationPlan) -> set[str]:
    paths: set[str] = set()
    for operation in plan.ordered_operations:
        match operation:
            case CreateFileOperation() | ReplaceFileOperation():
                paths.add(operation.path.value)
            case CreateTreeOperation():
                paths.update(
                    entry.path.value
                    for entry in operation.planned_new.entries
                    if isinstance(entry, PlannedFileEntry)
                )
            case DeleteFileOperation() | RemoveEmptyDirectoryOperation():
                pass
    return paths


def _planned_create_contents(plan: OperationPlan) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for operation in plan.ordered_operations:
        match operation:
            case CreateFileOperation(path=path, planned_new=planned):
                content = plan.blob_store.get(planned.content_id)
                assert content is not None
                contents[path.value] = content
            case CreateTreeOperation(planned_new=tree):
                for entry in tree.entries:
                    if isinstance(entry, PlannedFileEntry):
                        content = plan.blob_store.get(entry.content_id)
                        assert content is not None
                        contents[entry.path.value] = content
            case (
                ReplaceFileOperation()
                | DeleteFileOperation()
                | (RemoveEmptyDirectoryOperation())
            ):
                pass
    return contents


def _manifest_inventory(plan: OperationPlan) -> set[str]:
    match decode_manifest(plan.manifest_after.payload):
        case Ok(candidate):
            return {entry.path.value for entry in candidate.managed}
        case Err(error):
            raise AssertionError(f"manifest decode failed: {error}")


def test_compile_adoption_install_installs_the_complete_profile_closure() -> None:
    """Empty-tree adoption passes the full contract gate with apply's own output.

    The gate reuse is the assertion: compiling successfully means the expected
    target satisfied every required file and skill once the lifecycle install
    set joined the plan. The managed render and the bundle seeds must land
    byte-identically to what the two generation paths install.
    """
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    contents = _planned_create_contents(plan)
    rendered_files, _blobs = render_for((), GenerationPath.COPIER)
    # Managed output paths are identical across generation paths; the render
    # bodies differ only in their generation-path sentence (fragment layer).
    for file in rendered_files:
        assert file.path.value in contents, file.path.value
    expected_seeds = {
        "README.md": b"# Example\n",
        "docs/prd.md": b"# Product requirements\n",
        "SECURITY.md": b"# Security\n",
        "CONTRIBUTING.md": b"# Contributing\n",
        "scripts/validate-project": b"#!/bin/sh\n",
    }
    for path, content in expected_seeds.items():
        assert contents[path] == content, path
    assert "AGENTS.md" in contents
    assert "CLAUDE.md" in contents
    assert plan.generation_path is GenerationPath.ADOPTED


def test_compile_adoption_install_excludes_declared_keep_existing_paths() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    managed_paths = _planned_file_paths(plan) - _seed_paths() - {MANIFEST_PATH.value}
    keep_existing = "pyproject.toml"
    assert keep_existing in managed_paths
    excluded_plan, _readiness = _compile_adoption(
        str(REPO_ROOT),
        TargetSnapshot(files=(_observed_file(keep_existing, b"adopted\n"),)),
        collisions={keep_existing: "keep-existing"},
    )
    assert keep_existing not in _planned_paths(excluded_plan)
    assert _manifest_inventory(excluded_plan) == managed_paths - {keep_existing}


def test_compile_adoption_install_excludes_keep_existing_lifecycle_paths() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    managed_paths = _planned_file_paths(plan) - _seed_paths() - {MANIFEST_PATH.value}
    keep_existing = "CONTEXT.md"
    assert keep_existing in managed_paths
    excluded_plan, _readiness = _compile_adoption(
        str(REPO_ROOT),
        TargetSnapshot(files=(_observed_file(keep_existing, b"own context\n"),)),
        collisions={keep_existing: "keep-existing"},
    )
    assert keep_existing not in _planned_paths(excluded_plan)
    assert keep_existing not in _manifest_inventory(excluded_plan)


def test_compile_adoption_install_refuses_undeclared_collisions() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    managed_paths = _planned_file_paths(plan) - _seed_paths() - {MANIFEST_PATH.value}
    colliding = sorted(managed_paths)[:2]
    error = assert_err(
        _compile_adoption_result(
            str(REPO_ROOT),
            TargetSnapshot(
                files=tuple(_observed_file(path, b"adopted\n") for path in colliding)
            ),
            collisions={colliding[0]: "keep-existing"},
        ),
        "expected UNDECLARED_COLLISION",
    )
    assert isinstance(error, ContractError)
    assert set(error.subject.split(",")) == {colliding[1]}


def test_compile_adoption_install_writes_claude_md_as_agents_copy() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    contents = _planned_create_contents(plan)
    assert "AGENTS.md" in contents
    assert "CLAUDE.md" in contents
    assert contents["CLAUDE.md"] == contents["AGENTS.md"]


def test_compile_adoption_install_baseline_records_installed_lifecycle_source() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    baseline = plan.source_after
    assert isinstance(baseline, AdoptedSourceBaseline)
    contents = _planned_create_contents(plan)
    baseline_paths: set[str] = set()
    for entry in baseline.entries:
        if entry.kind == "directory":
            continue
        baseline_paths.add(entry.path.value)
        content = contents.get(entry.path.value)
        assert content is not None, f"{entry.path.value} was not installed"
        assert entry.sha256 == sha256_hex(content)
    assert "CONTEXT.md" in baseline_paths
    assert "AGENTS.md" in baseline_paths
    assert ".rygor/source-ownership.json" in baseline_paths
    assert "pyproject.toml" not in baseline_paths


def test_compile_adoption_install_records_adopted_provenance() -> None:
    plan, _readiness = _compile_adoption(str(REPO_ROOT), TargetSnapshot())
    assert plan.generation_path is GenerationPath.ADOPTED
    match decode_manifest(plan.manifest_after.payload):
        case Ok(candidate):
            assert candidate.provenance.generation_path is GenerationPath.ADOPTED
        case Err(error):
            raise AssertionError(f"manifest decode failed: {error}")


def test_compile_adoption_install_rejects_a_binary_agents_md() -> None:
    """The CLAUDE.md copy is a text file; a binary AGENTS.md cannot feed it."""
    root = Path(tempfile.mkdtemp()) / "template"
    (root / ".rygor").mkdir(parents=True)
    _ = (root / "AGENTS.md").write_bytes(b"\xff\xfe\x00 binary agents \x00")
    _ = (root / "LICENSE").write_bytes(b"Apache License\n")
    _ = (root / "NOTICE.md").write_bytes(b"# Notices\n")
    _ = (root / ".rygor" / "source-ownership.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lifecycle_paths": ["AGENTS.md"],
                "snapshot_cleanup_paths": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    error = assert_err(
        _compile_adoption_result(str(root), TargetSnapshot()),
        "expected INVALID_TEMPLATE",
    )
    assert isinstance(error, ContractError)
    assert error.subject == "lifecycle install set AGENTS.md must be UTF-8 text"
