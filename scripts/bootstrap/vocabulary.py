"""Shared bootstrap vocabulary: identifier classes, digests, and closed mode sets.

Every constrained value class and closed mode set used by the bootstrap engine is
declared once here. Pydantic schemas consume the anchored pattern strings; the
pure-core decoders and validators consume the compiled regular expressions with
``fullmatch`` so both sides share one character class.
"""

from __future__ import annotations

import re
from typing import TypeGuard

IDENTIFIER_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
SETTING_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
PROJECT_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9._-]*$"
BRANCH_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
TRANSACTION_ID_PATTERN = SHA256_PATTERN
COMMIT_SHA_PATTERN = r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"
# Unanchored by design: embedded inside the byte-level render marker regexes.
MARKER_NAME_PATTERN = r"[a-z][a-z0-9-]*"

IDENTIFIER = re.compile(IDENTIFIER_PATTERN)
SETTING_NAME = re.compile(SETTING_NAME_PATTERN)
PROJECT_NAME = re.compile(PROJECT_NAME_PATTERN)
BRANCH_NAME = re.compile(BRANCH_NAME_PATTERN)
SHA256 = re.compile(SHA256_PATTERN)
TRANSACTION_ID = re.compile(TRANSACTION_ID_PATTERN)
COMMIT_SHA = re.compile(COMMIT_SHA_PATTERN)

LICENSING_MODES = frozenset(
    {"retain-apache-2.0", "provided-project-license", "private"}
)
PATH_BEARING_LICENSING_MODES = frozenset({"provided-project-license", "private"})
SLOT_MODES = frozenset({"file", "scaffold"})

SECRET_SETTING_WORDS = (
    "secret",
    "token",
    "password",
    "credential",
    "api-key",
    "api_key",
)


def is_sha256(value: object) -> TypeGuard[str]:
    """Return whether a value is a lowercase 256-bit hex digest."""

    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def is_secret_setting_name(name: str) -> bool:
    """Return whether a setting name resembles a credential-bearing value."""
    return any(word in name.lower() for word in SECRET_SETTING_WORDS)
