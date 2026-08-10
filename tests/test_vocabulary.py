"""Tests for the shared bootstrap vocabulary module."""

from __future__ import annotations

import unittest
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


class LicensingVocabularyTests(unittest.TestCase):
    def test_schema_licensing_literal_matches_vocabulary(self) -> None:
        literal = set(get_args(LicensingInput.model_fields["mode"].annotation))
        self.assertEqual(literal, LICENSING_MODES)

    def test_path_bearing_modes_are_the_supplied_license_modes(self) -> None:
        self.assertEqual(
            PATH_BEARING_LICENSING_MODES,
            frozenset({"provided-project-license", "private"}),
        )
        self.assertLessEqual(PATH_BEARING_LICENSING_MODES, LICENSING_MODES)


class IdentifierVocabularyTests(unittest.TestCase):
    def test_identifier_accepts_kebab_case_and_rejects_other_classes(self) -> None:
        for value in ("repo", "repo-url", "repo2", "a"):
            self.assertIsNotNone(IDENTIFIER.fullmatch(value), value)
        for value in ("Repo", "repo--url", "repo-", "_repo", "repo_url"):
            self.assertIsNone(IDENTIFIER.fullmatch(value), value)

    def test_setting_name_accepts_underscores_but_not_dashes(self) -> None:
        self.assertIsNotNone(SETTING_NAME.fullmatch("cache_name"))
        self.assertIsNone(SETTING_NAME.fullmatch("cache-name"))

    def test_project_and_branch_names_cover_the_ascii_classes(self) -> None:
        self.assertIsNotNone(PROJECT_NAME.fullmatch("My.Project-1"))
        self.assertIsNone(PROJECT_NAME.fullmatch("1leading-digit"))
        self.assertIsNotNone(BRANCH_NAME.fullmatch("feature/issue-1"))
        self.assertIsNone(BRANCH_NAME.fullmatch("/leading-slash"))


class DigestVocabularyTests(unittest.TestCase):
    def test_sha256_accepts_exactly_64_lowercase_hex(self) -> None:
        self.assertIsNotNone(SHA256.fullmatch("0" * 64))
        self.assertIsNone(SHA256.fullmatch("0" * 63))
        self.assertIsNone(SHA256.fullmatch("0" * 65))
        self.assertIsNone(SHA256.fullmatch("A" * 64))

    def test_commit_sha_accepts_40_or_64_hex(self) -> None:
        self.assertIsNotNone(COMMIT_SHA.fullmatch("0" * 40))
        self.assertIsNotNone(COMMIT_SHA.fullmatch("0" * 64))
        self.assertIsNone(COMMIT_SHA.fullmatch("0" * 41))


class SecretVocabularyTests(unittest.TestCase):
    def test_secret_setting_detection_covers_the_word_list(self) -> None:
        for name in (
            "api_key",
            "api-key",
            "token_expiry",
            "secret",
            "password",
            "credential",
        ):
            self.assertTrue(is_secret_setting_name(name), name)

    def test_benign_setting_names_are_not_secret(self) -> None:
        for name in ("cache_name", "repo", "enabled"):
            self.assertFalse(is_secret_setting_name(name), name)


class SlotModeVocabularyTests(unittest.TestCase):
    def test_slot_modes_are_file_and_scaffold(self) -> None:
        self.assertEqual(SLOT_MODES, frozenset({"file", "scaffold"}))
