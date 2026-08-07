"""Effect adapters for stable observations and target-protection facts.

The filesystem/Git shell supplies a complete pass.  This module only compares its
semantic records, which keeps retry policy deterministic and testable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from scripts.bootstrap.errors import ObservationError, ObservationErrorKind
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.state import (
    CanonicalTemplateSource,
    OrdinaryProject,
    TargetProtection,
)

_CANONICAL_REMOTE = "github.com/knirski/agentic-template"
_SCP_REMOTE = re.compile(r"^(?:[^@]+@)?(?P<host>[^:/]+):(?P<path>.+)$")


@dataclass(frozen=True, slots=True)
class StableRawProjectObservation:
    """The semantic identity and bounded bytes captured by one full pass."""

    semantic_identity: object
    payload: bytes


def collect_coherent_observation(
    collect_pass: Callable[[], StableRawProjectObservation],
    *,
    max_attempts: int = 3,
) -> Result[StableRawProjectObservation, ObservationError]:
    """Return two identical complete passes, retrying boundedly on concurrent change."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for _ in range(max_attempts):
        first = collect_pass()
        second = collect_pass()
        if first == second:
            return Ok(second)
    return Err(
        ObservationError(
            ObservationErrorKind.CONCURRENT_TARGET_CHANGE,
            "target changed during three observation attempts",
        )
    )


def _remote_parts(remote: str) -> tuple[str, str] | None:
    match = None if "://" in remote else _SCP_REMOTE.fullmatch(remote)
    if match is not None:
        return match.group("host"), match.group("path")
    parsed = urlsplit(remote)
    if parsed.scheme not in {"https", "ssh", "http"} or not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in {None, 22, 80, 443}:
        return None
    return parsed.hostname, parsed.path


def normalize_remote(remote: str) -> str | None:
    """Normalize supported HTTPS/SSH/scp Git remotes to ``host/owner/repo``."""

    parts = _remote_parts(remote.strip())
    if parts is None:
        return None
    host, path = parts
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path or "/" not in path or "\x00" in path:
        return None
    return f"{host.lower()}/{path.lower()}"


def target_protection_for_remotes(remotes: Iterable[str]) -> TargetProtection:
    """Recognize the canonical template source without authenticating the repository."""

    for remote in remotes:
        if normalize_remote(remote) == _CANONICAL_REMOTE:
            return CanonicalTemplateSource(_CANONICAL_REMOTE)
    return OrdinaryProject()
