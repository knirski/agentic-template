#!/usr/bin/env python3
"""Secret scanner enforcing the repository `## Safety` rule.

Agent-agnostic detection core: flags likely secrets in arbitrary text or
structured JSON. AI-agent integrations (Claude Code, Codex, Cursor, Copilot,
...) wire this script as a pre-write hook and feed it the content to scan; the
detection logic assumes nothing about any specific agent's event shape. The
decision transport (here: a non-zero exit blocks the write) is the
integration's concern and lives in the agent's own settings file.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make the repo root importable so this script reuses the typed JSON domain
# that the rest of the codebase shares, instead of re-declaring it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bootstrap.canonical_json import StrictJsonValue, decode_json

# Conservative, high-signal patterns. Tuned to minimize false positives:
# only values that resemble real credentials are flagged.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"(?i)(?:api[_-]?key|secret|client[_-]?secret|access[_-]?token|"
        + r"auth[_-]?token|password|passwd)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"
    ),
)


def scan_text(text: str) -> str | None:
    """Return a reason string if `text` looks secret-bearing, else ``None``."""
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        return f"possible secret matched {pattern.pattern!r}"
    return None


# Keys whose values hold content being *removed* from a file (e.g. an edit's
# previous text). Scanning them would block legitimate secret deletion, so they
# are flattened to nothing. Only prospective content reaches the scanner.
_SKIP_VALUE_KEYS = frozenset({"old_string"})


def flatten_json(
    value: StrictJsonValue, skip_keys: frozenset[str] = _SKIP_VALUE_KEYS
) -> str:
    """Concatenate every string leaf of a JSON value into one scannable string.

    Values under ``skip_keys`` are omitted so removal-only content (such as an
    edit's ``old_string``) is never scanned; only content that would persist in
    the resulting file is inspected.
    """
    match value:
        case str(text):
            return text
        case dict(mapping):
            return "\n".join(
                flatten_json(child, skip_keys)
                for key, child in mapping.items()
                if key not in skip_keys
            )
        case list(items):
            return "\n".join(flatten_json(item, skip_keys) for item in items)
        case float():
            return ""
        case bool() | int() | None:
            return ""


def main() -> int:
    """Read a hook event from stdin and block on suspected secrets.

    The script is agent-agnostic: it scans the entire decoded event, so it
    catches secrets regardless of which agent sent it or what field names it
    uses. An integration is responsible for piping the relevant tool input as
    JSON and for interpreting a non-zero exit as "block this write". Returns
    ``0`` to allow, ``2`` to block.
    """
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        event = decode_json(raw.encode("utf-8"))
    except ValueError:
        # Not a recognized hook event, or not strict JSON; never block on it.
        return 0

    reason = scan_text(flatten_json(event))
    if reason is None:
        return 0

    message = f"Blocked write: {reason}. Refusing to write a suspected secret (AGENTS.md ## Safety)."
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
