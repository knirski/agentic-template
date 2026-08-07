from __future__ import annotations

import unittest

from scripts.bootstrap.canonical_json import canonical_json, decode_json
from scripts.bootstrap.identity import (
    PosixMode,
    content_identity,
    sha256_hex,
    tagged_digest,
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


if __name__ == "__main__":
    unittest.main()
