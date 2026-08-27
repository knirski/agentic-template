from __future__ import annotations

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


def test_serializes_only_the_strict_json_value_domain() -> None:
    assert canonical_json({"b": 2, "a": True}) == b'{"a":true,"b":2}'
    assert canonical_json(None) == b"null"
    # Floats are now part of the strict domain; only non-finite floats,
    # out-of-range integers, and surrogate strings remain rejected.
    assert decode_json(b"1.5") == 1.5
    assert canonical_json(1.5) == b"1.5"
    for value in (float("nan"), 2**53 + 1, "\ud800"):
        try:
            canonical_json(value)
            raise AssertionError(f"expected ValueError for {value!r}")
        except ValueError:
            pass
    try:
        decode_json(b"NaN")
        raise AssertionError("expected ValueError for NaN")
    except ValueError:
        pass


def test_rejects_duplicate_keys_and_non_utf8() -> None:
    for payload in (b'{"a":1,"a":2}', b"\xff"):
        try:
            decode_json(payload)
            raise AssertionError(f"expected ValueError for {payload!r}")
        except ValueError:
            pass


def test_rejects_documents_beyond_the_maximum_nesting_depth() -> None:
    deep = b"[" * 200 + b"0" + b"]" * 200
    try:
        decode_json(deep)
        raise AssertionError("expected ValueError for deep nesting")
    except ValueError:
        pass
    nested: object = 0
    for _ in range(200):
        nested = [nested]
    try:
        canonical_json(nested)
        raise AssertionError("expected ValueError for deep nested canonical")
    except ValueError:
        pass


def test_accepts_repository_relative_posix_paths() -> None:
    result = parse_path("docs/readme.md")
    assert result == Ok(RepoPath("docs/readme.md"))


def test_rejects_noncanonical_path_shapes() -> None:
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
        assert isinstance(parse_path(value), Err)


def test_normalizes_mixed_line_endings_to_one_trailing_lf() -> None:
    assert normalize_text(b"a\r\nb\rc\n\n") == b"a\nb\nc\n"
    try:
        normalize_text(b"\xff")
        raise AssertionError("expected ValueError for \\xff")
    except ValueError:
        pass


def test_content_identity_distinguishes_raw_and_normalized_bytes() -> None:
    identity = content_identity(b"hello\r\n", text=True)
    assert identity.normalized_sha256 == sha256_hex(b"hello\n")
    assert identity.raw_sha256 == sha256_hex(b"hello\r\n")
    assert identity.size == 7


def test_tagged_digest_separates_domains() -> None:
    assert tagged_digest(b"one", b"two") != tagged_digest(b"onet", b"wo")


def test_tagged_digest_frames_kind_length_before_payload() -> None:
    assert tagged_digest(b"a", b"b\npayload") != tagged_digest(b"a\nb", b"payload")


def test_tree_hash_is_sorted_and_mode_sensitive() -> None:
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
    assert actual == expected
    assert actual != tree_hash(b"tree", ((RepoPath("a"), b"1", PosixMode.EXECUTABLE),))


def test_tree_hash_rejects_duplicate_paths() -> None:
    try:
        tree_hash(
            b"tree",
            (
                (RepoPath("a"), b"1", PosixMode.FILE),
                (RepoPath("a"), b"2", PosixMode.FILE),
            ),
        )
        raise AssertionError("expected ValueError for duplicate paths")
    except ValueError:
        pass


def test_directory_tree_identity_includes_topology_and_directory_modes() -> None:
    file_entry = FileEntry(RepoPath("nested/file"), b"payload", PosixMode.FILE)
    directory_entry = DirectoryEntry(RepoPath("nested"), PosixMode.DIRECTORY)
    identity = directory_tree_hash(
        b"source",
        DirectoryState(
            root_mode=PosixMode.DIRECTORY,
            entries=(file_entry, directory_entry),
        ),
    )
    assert identity == directory_tree_hash(
        b"source",
        DirectoryState(
            root_mode=PosixMode.DIRECTORY,
            entries=(directory_entry, file_entry),
        ),
    )
    assert identity != directory_tree_hash(
        b"source",
        DirectoryState(
            root_mode=PosixMode.DIRECTORY,
            entries=(FileEntry(RepoPath("nested/file"), b"payload", PosixMode.FILE),),
        ),
    )
    assert identity != directory_tree_hash(
        b"source",
        DirectoryState(
            root_mode=PosixMode.DIRECTORY,
            entries=(
                directory_entry,
                FileEntry(RepoPath("nested/file"), b"payload", PosixMode.EXECUTABLE),
            ),
        ),
    )


def test_directory_tree_identity_distinguishes_absent_and_empty() -> None:
    empty = DirectoryState(root_mode=PosixMode.DIRECTORY, entries=())
    assert directory_tree_hash(b"tree", empty) != directory_tree_hash(b"tree", None)


def test_file_identity_distinguishes_absent_and_empty_files() -> None:
    absent = file_state_identity(None, text=True)
    empty = file_state_identity(b"", text=True, mode=PosixMode.FILE)
    assert isinstance(absent, FileState)
    assert not absent.present
    assert empty.present
    assert file_state_hash(b"file", absent) != file_state_hash(b"file", empty)
    try:
        file_state_identity(None, text=True, mode=PosixMode.FILE)
        raise AssertionError("expected ValueError for mismatched present/mode")
    except ValueError:
        pass


def test_target_source_and_manifest_identities_are_tagged_and_immutable() -> None:
    target = target_identity(b"/workspace/project", device=8, inode=42)
    assert isinstance(target, TargetIdentity)
    assert target.digest == tagged_digest(
        b"target-binding",
        len(b"/workspace/project").to_bytes(8, "big")
        + b"/workspace/project"
        + (8).to_bytes(8, "big")
        + (42).to_bytes(8, "big"),
    )
    source = source_identity(((RepoPath("a"), b"a", PosixMode.FILE),))
    assert isinstance(source, SourceIdentity)
    manifest = manifest_identity({"schema": 1, "source": source.digest})
    assert isinstance(manifest, ManifestIdentity)
    assert manifest.digest == tagged_digest(b"manifest", manifest.payload)
    try:
        target_identity(b"/workspace/project", device=-1, inode=42)
        raise AssertionError("expected ValueError for negative device")
    except ValueError:
        pass
