"""Tests for the shared bootstrap vocabulary module."""

from __future__ import annotations

from typing import get_args

from scripts.bootstrap.schemas import LicensingInput
from scripts.bootstrap.vocabulary import (
    BRANCH_NAME,
    COMMIT_SHA,
    IDENTIFIER,
    LICENSING_MODES,
    PATH_BEARING_LICENSING_MODES,
    PROJECT_NAME,
    SETTING_NAME,
    SHA256,
    SLOT_MODES,
    is_secret_setting_name,
)


def test_schema_licensing_literal_matches_vocabulary() -> None:
    literal = set(get_args(LicensingInput.model_fields["mode"].annotation))
    assert literal == LICENSING_MODES


def test_path_bearing_modes_are_the_supplied_license_modes() -> None:
    assert frozenset(
        {"provided-project-license", "private"}
    ) == PATH_BEARING_LICENSING_MODES
    assert PATH_BEARING_LICENSING_MODES <= LICENSING_MODES


def test_identifier_accepts_kebab_case_and_rejects_other_classes() -> None:
    for value in ("repo", "repo-url", "repo2", "a"):
        assert IDENTIFIER.fullmatch(value), value
    for value in ("Repo", "repo--url", "repo-", "_repo", "repo_url"):
        assert not IDENTIFIER.fullmatch(value), value


def test_setting_name_accepts_underscores_but_not_dashes() -> None:
    assert SETTING_NAME.fullmatch("cache_name")
    assert not SETTING_NAME.fullmatch("cache-name")


def test_project_and_branch_names_cover_the_ascii_classes() -> None:
    assert PROJECT_NAME.fullmatch("My.Project-1")
    assert not PROJECT_NAME.fullmatch("1leading-digit")
    assert BRANCH_NAME.fullmatch("feature/issue-1")
    assert not BRANCH_NAME.fullmatch("/leading-slash")


def test_sha256_accepts_exactly_64_lowercase_hex() -> None:
    assert SHA256.fullmatch("0" * 64)
    assert not SHA256.fullmatch("0" * 63)
    assert not SHA256.fullmatch("0" * 65)
    assert not SHA256.fullmatch("A" * 64)


def test_commit_sha_accepts_40_or_64_hex() -> None:
    assert COMMIT_SHA.fullmatch("0" * 40)
    assert COMMIT_SHA.fullmatch("0" * 64)
    assert not COMMIT_SHA.fullmatch("0" * 41)


def test_secret_setting_detection_covers_the_word_list() -> None:
    for name in (
        "api_key",
        "api-key",
        "token_expiry",
        "secret",
        "password",
        "credential",
    ):
        assert is_secret_setting_name(name), name


def test_benign_setting_names_are_not_secret() -> None:
    for name in ("cache_name", "repo", "enabled"):
        assert not is_secret_setting_name(name), name


def test_slot_modes_are_file_and_scaffold() -> None:
    assert frozenset({"file", "scaffold"}) == SLOT_MODES
