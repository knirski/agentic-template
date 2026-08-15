"""In-process unit tests for the strict bundle decoder.

The CLI end-to-end suite reaches ``decode_bundle_input`` only through the
happy path; these tests pin every bounded rejection branch directly.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast

from scripts.bootstrap.bundles import DecodedBundle, decode_bundle_input
from scripts.bootstrap.errors import InputErrorKind
from scripts.bootstrap.result import Err, Ok

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


def _write_bundle(
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


class DecodeBundleInputTests(unittest.TestCase):
    def test_decode_accepts_a_complete_bundle(self) -> None:
        json_path = _write_bundle(_valid_bundle())
        match decode_bundle_input(json_path):
            case Ok(decoded):
                self.assertIsInstance(decoded, DecodedBundle)
                self.assertEqual(decoded.bundle.project.name, "example")
                self.assertEqual(set(decoded.content), {p for p in decoded.content})
                self.assertTrue(decoded.bundle_digest)
            case Err(error):
                self.fail(f"expected success, got {error}")

    def test_decode_rejects_a_missing_bundle_file(self) -> None:
        missing = os.path.join(tempfile.mkdtemp(), "bootstrap.json")
        match decode_bundle_input(missing):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.MISSING_INPUT)
            case Ok(_):
                self.fail("expected MISSING_INPUT")

    def test_decode_rejects_an_oversized_bundle(self) -> None:
        json_path = _write_bundle(_valid_bundle(), payload=b"x" * (_MAX_FILE_BYTES + 1))
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.INPUT_LIMIT_EXCEEDED)
            case Ok(_):
                self.fail("expected INPUT_LIMIT_EXCEEDED")

    def test_decode_rejects_invalid_json(self) -> None:
        json_path = _write_bundle(_valid_bundle(), payload=b"{not json")
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.INVALID_JSON)
            case Ok(_):
                self.fail("expected INVALID_JSON")

    def test_decode_rejects_non_dict_json(self) -> None:
        json_path = _write_bundle(_valid_bundle(), payload=b"[1, 2]")
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.SCHEMA_VIOLATION)
            case Ok(_):
                self.fail("expected SCHEMA_VIOLATION")

    def test_decode_rejects_schema_violations(self) -> None:
        document = _valid_bundle()
        document["schema_version"] = 2
        json_path = _write_bundle(document)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.SCHEMA_VIOLATION)
                self.assertIn("unsupported bootstrap schema version", error.subject)
            case Ok(_):
                self.fail("expected SCHEMA_VIOLATION")

    def test_decode_rejects_missing_content_files(self) -> None:
        json_path = _write_bundle(_valid_bundle(), files={"content/readme.md": b"x"})
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.MISSING_INPUT)
            case Ok(_):
                self.fail("expected MISSING_INPUT")

    def test_decode_rejects_non_file_content(self) -> None:
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
        match decode_bundle_input(str(json_path)):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.WRONG_KIND)
            case Ok(_):
                self.fail("expected WRONG_KIND")

    def test_decode_rejects_invalid_utf8_content(self) -> None:
        files = dict(_DEFAULT_FILES)
        files["content/prd.md"] = b"\xff\xfe\x00"
        json_path = _write_bundle(_valid_bundle(), files=files)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.INVALID_ENCODING)
            case Ok(_):
                self.fail("expected INVALID_ENCODING")

    def test_decode_rejects_duplicate_declared_paths(self) -> None:
        document = _valid_bundle()
        content = cast(dict[str, object], document["content"])
        content["readme"] = {"mode": "file", "path": "content/prd.md"}
        json_path = _write_bundle(document)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.MARKER_COLLISION)
            case Ok(_):
                self.fail("expected MARKER_COLLISION")

    def test_decode_rejects_missing_license_files(self) -> None:
        document = _valid_bundle()
        document["licensing"] = {
            "mode": "private",
            "path": "content/license.txt",
        }
        json_path = _write_bundle(document)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.MISSING_INPUT)
            case Ok(_):
                self.fail("expected MISSING_INPUT")

    def test_decode_rejects_license_paths_colliding_with_slots(self) -> None:
        document = _valid_bundle()
        document["licensing"] = {
            "mode": "private",
            "path": "content/prd.md",
        }
        json_path = _write_bundle(document)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.MARKER_COLLISION)
            case Ok(_):
                self.fail("expected MARKER_COLLISION")

    def test_decode_rejects_unresolvable_profiles(self) -> None:
        document = _valid_bundle()
        document["profile"] = {
            "id": "custom",
            "capabilities": ["no-such-capability"],
        }
        json_path = _write_bundle(document)
        match decode_bundle_input(json_path):
            case Err(error):
                self.assertEqual(error.kind, InputErrorKind.SCHEMA_VIOLATION)
                self.assertIn("unknown_capability", error.subject)
            case Ok(_):
                self.fail("expected SCHEMA_VIOLATION")


if __name__ == "__main__":
    _ = unittest.main()
