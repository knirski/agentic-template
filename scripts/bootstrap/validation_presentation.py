"""Shared presentation and argument rules for template-owned validators."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from scripts.bootstrap.canonical_json import canonical_json

if TYPE_CHECKING:
    from scripts.bootstrap.readiness import Finding

ValidationFormat = Literal["text", "json"]
ValidationColor = Literal["auto", "always", "never"]


@dataclass(frozen=True, slots=True)
class ValidationOptions:
    format: ValidationFormat = "text"
    color: ValidationColor = "auto"
    explain: bool = False
    quiet: bool = False


def parse_options(argv: list[str]) -> ValidationOptions | None:
    """Parse the common validator presentation flags.

    JSON is intentionally a single machine-owned stream: decorative colour and
    quiet mode are rejected, matching the bootstrap command contract.
    """

    format_value: ValidationFormat = "text"
    color_value: ValidationColor = "auto"
    explain = False
    quiet = False
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--explain":
            explain = True
        elif argument == "--quiet":
            quiet = True
        elif argument in ("--format", "--color"):
            index += 1
            if index >= len(argv):
                return None
            value = argv[index]
            if argument == "--format" and value in ("text", "json"):
                format_value = value
            elif argument == "--color" and value in ("auto", "always", "never"):
                color_value = value
            else:
                return None
        else:
            return None
        index += 1
    if format_value == "json" and (color_value != "auto" or quiet):
        return None
    return ValidationOptions(format_value, color_value, explain, quiet)


def requested_json(argv: list[str]) -> bool:
    """Return whether an invalid invocation explicitly requested JSON output."""

    return any(
        argument == "--format=json"
        or (
            argument == "--format"
            and index + 1 < len(argv)
            and argv[index + 1] == "json"
        )
        for index, argument in enumerate(argv)
    )


def render_usage_error(command: str, message: str, *, json_output: bool) -> int:
    """Render one deterministic usage error in the requested presentation format."""

    if json_output:
        print(
            canonical_json(
                {
                    "schema_version": 1,
                    "command": command,
                    "outcome_class": "invalid_request",
                    "exit_code": 2,
                    "findings": [],
                    "diagnostic": safe_text(message),
                    "explain": False,
                }
            ).decode("utf-8")
        )
    else:
        print(safe_text(message), file=sys.stderr)
    return 2


def color_enabled(options: ValidationOptions, *, stream: object = sys.stderr) -> bool:
    """Return whether text presentation may emit ANSI colour."""

    if options.color == "never" or "NO_COLOR" in os.environ:
        return False
    if options.color == "always":
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def safe_text(value: str) -> str:
    """Escape terminal controls and non-printable Unicode deterministically."""

    escaped: list[str] = []
    bidi_controls = {
        *range(0x202A, 0x202F),
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0x206A,
        0x206B,
        0x206C,
        0x206D,
        0x206E,
        0x206F,
    }
    for character in value:
        codepoint = ord(character)
        if codepoint in bidi_controls or codepoint < 0x20 or codepoint == 0x7F:
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            else:
                escaped.append(f"\\u{codepoint:04x}")
        elif not character.isprintable():
            escaped.append(f"\\u{codepoint:04x}")
        else:
            escaped.append(character)
    return "".join(escaped)


def finding_document(finding: Finding) -> dict[str, object]:
    """Convert one structured readiness finding to canonical JSON data."""

    return {
        "code": finding.code,
        "subject": finding.subject,
        "rule": finding.rule,
        "severity": finding.severity,
        "message": finding.message,
        "next_action": safe_text(str(finding.next_action)),
    }


def render_findings(
    *,
    command: str,
    findings: tuple[Finding, ...],
    exit_code: int,
    options: ValidationOptions,
    diagnostic: str | None = None,
) -> int:
    """Render a validator result as one text stream or one JSON document."""

    if options.format == "json":
        document: dict[str, object] = {
            "schema_version": 1,
            "command": command,
            "outcome_class": (
                "succeeded"
                if exit_code == 0
                else "validation_failed"
                if exit_code == 1
                else "internal_failure"
            ),
            "exit_code": exit_code,
            "findings": [finding_document(finding) for finding in findings],
            "explain": options.explain,
        }
        if diagnostic is not None:
            document["diagnostic"] = safe_text(diagnostic)
        print(canonical_json(document).decode("utf-8"))
        return exit_code

    if options.explain and not options.quiet:
        print(f"state: {command}", file=sys.stderr)
    if diagnostic is not None:
        print(safe_text(diagnostic), file=sys.stderr)
    for finding in findings:
        rendered = safe_text(finding.render())
        if color_enabled(options):
            rendered = f"\033[31m{rendered}\033[0m"
        print(rendered, file=sys.stderr)
    return exit_code
