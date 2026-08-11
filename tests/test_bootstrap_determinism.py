from __future__ import annotations

import unittest

from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.identity import (
    DirectoryEntry,
    DirectoryState,
    FileEntry,
    FileState,
    ManifestIdentity,
    PosixMode,
    SourceIdentity,
    TargetIdentity,
    content_identity,
    directory_tree_hash,
    file_state_hash,
    file_state_identity,
    manifest_identity,
    sha256_hex,
    source_identity,
    tagged_digest,
    target_identity,
    tree_hash,
)
from scripts.bootstrap.paths import RepoPath, normalize_text, parse_path
from scripts.bootstrap.result import Err, Ok


class CanonicalJsonTests(unittest.TestCase):
    def test_serializes_only_the_strict_json_value_domain(self) -> None:
        self.assertEqual(canonical_json({"b": 2, "a": True}), b'{"a":true,"b":2}')
        self.assertEqual(canonical_json(None), b"null")
        for value in (1.5, float("nan"), 2**53 + 1, "\ud800"):
            with self.assertRaises(ValueError):
                canonical_json(value)

    def test_rejects_duplicate_keys_and_non_utf8(self) -> None:
        for payload in (b'{"a":1,"a":2}', b"\xff"):
            with self.assertRaises(ValueError):
                decode_json(payload)

    def test_rejects_documents_beyond_the_maximum_nesting_depth(self) -> None:
        deep = b"[" * 200 + b"0" + b"]" * 200
        with self.assertRaises(ValueError):
            decode_json(deep)
        nested: object = 0
        for _ in range(200):
            nested = [nested]
        with self.assertRaises(ValueError):
            canonical_json(nested)


class PathTests(unittest.TestCase):
    def test_accepts_repository_relative_posix_paths(self) -> None:
        result = parse_path("docs/readme.md")
        self.assertEqual(result, Ok(RepoPath("docs/readme.md")))

    def test_rejects_noncanonical_path_shapes(self) -> None:
        for value in (
            "",
            "/absolute",
            "a//b",
            "a/./b",
            "a/../b",
            r"a\\b",
            "a/",
            "\ud800",
        ):
            self.assertIsInstance(parse_path(value), Err)

    def test_normalizes_mixed_line_endings_to_one_trailing_lf(self) -> None:
        self.assertEqual(normalize_text(b"a\r\nb\rc\n\n"), b"a\nb\nc\n")
        with self.assertRaises(ValueError):
            normalize_text(b"\xff")


class IdentityTests(unittest.TestCase):
    def test_content_identity_distinguishes_raw_and_normalized_bytes(self) -> None:
        identity = content_identity(b"hello\r\n", text=True)
        self.assertEqual(identity.normalized_sha256, sha256_hex(b"hello\n"))
        self.assertEqual(identity.raw_sha256, sha256_hex(b"hello\r\n"))
        self.assertEqual(identity.size, 7)

    def test_tagged_digest_separates_domains(self) -> None:
        self.assertNotEqual(
            tagged_digest(b"one", b"two"), tagged_digest(b"onet", b"wo")
        )

    def test_tagged_digest_frames_kind_length_before_payload(self) -> None:
        self.assertNotEqual(
            tagged_digest(b"a", b"b\npayload"),
            tagged_digest(b"a\nb", b"payload"),
        )

    def test_tree_hash_is_sorted_and_mode_sensitive(self) -> None:
        entries = (
            (RepoPath("b"), b"2", PosixMode.FILE),
            (RepoPath("a"), b"1", PosixMode.FILE),
        )
        actual = tree_hash(b"tree", entries)
        encoded = b"\n".join(
            canonical_json(
                {"path": path.value, "mode": mode.value, "sha256": sha256_hex(content)}
            )
            for path, content, mode in sorted(
                entries, key=lambda item: item[0].value.encode()
            )
        )
        expected = tagged_digest(b"tree", encoded)
        self.assertEqual(actual, expected)
        self.assertNotEqual(
            actual, tree_hash(b"tree", ((RepoPath("a"), b"1", PosixMode.EXECUTABLE),))
        )

    def test_tree_hash_rejects_duplicate_paths(self) -> None:
        with self.assertRaises(ValueError):
            tree_hash(
                b"tree",
                (
                    (RepoPath("a"), b"1", PosixMode.FILE),
                    (RepoPath("a"), b"2", PosixMode.FILE),
                ),
            )

    def test_directory_tree_identity_includes_topology_and_directory_modes(
        self,
    ) -> None:
        file_entry = FileEntry(RepoPath("nested/file"), b"payload", PosixMode.FILE)
        directory_entry = DirectoryEntry(RepoPath("nested"), PosixMode.DIRECTORY)
        identity = directory_tree_hash(
            b"source",
            DirectoryState(
                root_mode=PosixMode.DIRECTORY,
                entries=(file_entry, directory_entry),
            ),
        )
        self.assertEqual(
            identity,
            directory_tree_hash(
                b"source",
                DirectoryState(
                    root_mode=PosixMode.DIRECTORY,
                    entries=(directory_entry, file_entry),
                ),
            ),
        )
        self.assertNotEqual(
            identity,
            directory_tree_hash(
                b"source",
                DirectoryState(
                    root_mode=PosixMode.DIRECTORY,
                    entries=(
                        FileEntry(RepoPath("nested/file"), b"payload", PosixMode.FILE),
                    ),
                ),
            ),
        )
        self.assertNotEqual(
            identity,
            directory_tree_hash(
                b"source",
                DirectoryState(
                    root_mode=PosixMode.DIRECTORY,
                    entries=(
                        directory_entry,
                        FileEntry(
                            RepoPath("nested/file"), b"payload", PosixMode.EXECUTABLE
                        ),
                    ),
                ),
            ),
        )

    def test_directory_tree_identity_distinguishes_absent_and_empty(self) -> None:
        empty = DirectoryState(root_mode=PosixMode.DIRECTORY, entries=())
        self.assertNotEqual(
            directory_tree_hash(b"tree", empty),
            directory_tree_hash(b"tree", None),
        )

    def test_file_identity_distinguishes_absent_and_empty_files(self) -> None:
        absent = file_state_identity(None, text=True)
        empty = file_state_identity(b"", text=True, mode=PosixMode.FILE)
        self.assertIsInstance(absent, FileState)
        self.assertFalse(absent.present)
        self.assertTrue(empty.present)
        self.assertNotEqual(
            file_state_hash(b"file", absent), file_state_hash(b"file", empty)
        )
        with self.assertRaises(ValueError):
            file_state_identity(None, text=True, mode=PosixMode.FILE)

    def test_target_source_and_manifest_identities_are_tagged_and_immutable(
        self,
    ) -> None:
        target = target_identity(b"/workspace/project", device=8, inode=42)
        self.assertIsInstance(target, TargetIdentity)
        self.assertEqual(
            target.digest,
            tagged_digest(
                b"target-binding",
                len(b"/workspace/project").to_bytes(8, "big")
                + b"/workspace/project"
                + (8).to_bytes(8, "big")
                + (42).to_bytes(8, "big"),
            ),
        )
        source = source_identity(((RepoPath("a"), b"a", PosixMode.FILE),))
        self.assertIsInstance(source, SourceIdentity)
        manifest = manifest_identity({"schema": 1, "source": source.digest})
        self.assertIsInstance(manifest, ManifestIdentity)
        self.assertEqual(manifest.digest, tagged_digest(b"manifest", manifest.payload))
        with self.assertRaises(ValueError):
            target_identity(b"/workspace/project", device=-1, inode=42)


if __name__ == "__main__":
    unittest.main()
