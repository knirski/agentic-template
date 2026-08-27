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

from scripts.bootstrap.bundles import DecodedBundle, decode_bundle_input
from scripts.bootstrap.errors import InputErrorKind
from tests.fixtures import assert_err, assert_ok

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
    error = assert_err(
        decode_bundle_input(json_path), "expected INPUT_LIMIT_EXCEEDED"
    )
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
    json_path = _materialize_bundle(
        _valid_bundle(), files={"content/readme.md": b"x"}
    )
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
