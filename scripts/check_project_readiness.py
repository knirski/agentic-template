#!/usr/bin/env python3
"""Inspect generated-project readiness without executing or mutating project files."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PRD = ROOT / "docs" / "prd.md"
README = ROOT / "README.md"
HOOK = ROOT / "scripts" / "validate_project.py"
PRD_MARKER = "<!-- agentic-template:placeholder:prd -->"
README_MARKER = "<!-- agentic-template:placeholder:readme -->"
HOOK_SENTINEL = "agentic-template:unconfigured:validate-project"
REQUIRED_HEADINGS = [
    "Problem",
    "Goals",
    "Non-goals",
    "Users and workflows",
    "Requirements",
    "Quality attributes",
    "Release criteria",
    "Open questions",
]


@dataclass(frozen=True)
class Finding:
    code: str
    path: Path
    message: str
    next_action: str

    def render(self) -> str:
        return f"{self.code}: {self.path.relative_to(ROOT)}: {self.message}; next: {self.next_action}"


def read_text(path: Path, findings: list[Finding]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        findings.append(
            Finding(
                "READINESS_MISSING_FILE",
                path,
                "file is missing",
                "restore the required file",
            )
        )
    except (OSError, UnicodeError) as exc:
        findings.append(
            Finding(
                "INTERNAL_READINESS_ERROR",
                path,
                f"cannot read file ({exc})",
                "fix the file and rerun validation",
            )
        )
    return None


def visible_lines(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        match = re.match(r"(`{3,}|~{3,})", stripped)
        if match:
            delimiter = match.group(1)
            if fence is None:
                fence = (delimiter[0], len(delimiter))
            elif delimiter[0] == fence[0] and len(delimiter) >= fence[1]:
                fence = None
            continue
        if fence is None:
            result.append((number, line))
    return result


def check_prd(findings: list[Finding]) -> None:
    text = read_text(PRD, findings)
    if text is None:
        return
    lines = visible_lines(text)
    if PRD_MARKER in text:
        findings.append(
            Finding(
                "READINESS_PRD_MARKER",
                PRD,
                "template replacement marker remains",
                "replace the marked PRD with product requirements",
            )
        )
    if "This file is authoritative for the Agentic Delivery Template" in text:
        findings.append(
            Finding(
                "READINESS_PRD_BOILERPLATE",
                PRD,
                "template-source boilerplate remains",
                "replace the introductory template contract",
            )
        )

    headings = [
        (n, m.group(1).strip())
        for n, line in lines
        if (m := re.match(r"^##\s+(.+?)\s*$", line))
    ]
    positions: list[int] = []
    for title in REQUIRED_HEADINGS:
        matches = [n for n, heading in headings if heading == title]
        if not matches:
            findings.append(
                Finding(
                    "READINESS_PRD_HEADING_MISSING",
                    PRD,
                    f"required heading '## {title}' is missing",
                    f"add exactly one '## {title}' section",
                )
            )
        else:
            if len(matches) > 1:
                findings.append(
                    Finding(
                        "READINESS_PRD_HEADING_DUPLICATE",
                        PRD,
                        f"heading '## {title}' appears {len(matches)} times",
                        f"keep one '## {title}' section",
                    )
                )
            positions.append(matches[0])
    if positions and positions != sorted(positions):
        findings.append(
            Finding(
                "READINESS_PRD_HEADING_ORDER",
                PRD,
                "required headings are out of order",
                "reorder the required level-two sections",
            )
        )

    req_section = next(
        (n for n, heading in headings if heading == "Requirements"), None
    )
    if req_section is None:
        return
    req_end = next(
        (n for n, heading in headings if n > req_section), len(text.splitlines()) + 1
    )
    req_lines = [(n, line) for n, line in lines if req_section < n < req_end]
    declarations: dict[str, tuple[int, str]] = {}
    declaration_pattern = re.compile(r"^###\s+(REQ-(\d{3})):\s*(.*?)\s*$")
    for number, line in req_lines:
        match = declaration_pattern.match(line)
        if match:
            identifier, digits, title = match.groups()
            if digits == "000":
                findings.append(
                    Finding(
                        "READINESS_REQUIREMENT_ID",
                        PRD,
                        f"requirement {identifier} has an invalid identifier",
                        "use an identifier from REQ-001 through REQ-999",
                    )
                )
            if identifier in declarations:
                findings.append(
                    Finding(
                        "READINESS_REQUIREMENT_DUPLICATE",
                        PRD,
                        f"requirement {identifier} is declared more than once",
                        "keep one declaration for the identifier",
                    )
                )
            declarations[identifier] = (number, title)
            if title == "":
                findings.append(
                    Finding(
                        "READINESS_REQUIREMENT_TITLE",
                        PRD,
                        f"requirement {identifier} has an empty title",
                        "add a non-empty requirement title",
                    )
                )
            continue
        malformed = re.match(r"^###\s+(REQ-[^:]+):", line)
        if malformed:
            findings.append(
                Finding(
                    "READINESS_REQUIREMENT_ID",
                    PRD,
                    "requirement heading has an invalid identifier",
                    "use an identifier from REQ-001 through REQ-999",
                )
            )
    if not declarations:
        findings.append(
            Finding(
                "READINESS_REQUIREMENT_MISSING",
                PRD,
                "no requirement declaration exists",
                "add at least one ### REQ-001: Title declaration",
            )
        )
    for identifier, (line_no, _) in declarations.items():
        next_heading = next(
            (n for n, line in req_lines if n > line_no and line.startswith("### ")),
            req_end,
        )
        body = [
            line.strip()
            for n, line in req_lines
            if line_no < n < next_heading and line.strip()
        ]
        if not body:
            findings.append(
                Finding(
                    "READINESS_REQUIREMENT_BODY",
                    PRD,
                    f"requirement {identifier} has no body",
                    "add explanatory and acceptance content below the requirement heading",
                )
            )


def check_readme(findings: list[Finding]) -> None:
    text = read_text(README, findings)
    if text is None:
        return
    lines = visible_lines(text)
    if README_MARKER in text:
        findings.append(
            Finding(
                "READINESS_README_MARKER",
                README,
                "template replacement marker remains",
                "replace the marked README with project documentation",
            )
        )
    if "# Agentic Delivery Template" in text:
        findings.append(
            Finding(
                "READINESS_README_BOILERPLATE",
                README,
                "template title remains",
                "replace the template title with the project title",
            )
        )
    if "A language-neutral GitHub repository template for planning" in text:
        findings.append(
            Finding(
                "READINESS_README_BOILERPLATE",
                README,
                "template introduction remains",
                "replace the template introduction with project documentation",
            )
        )
    titles = [line for _, line in lines if re.match(r"^#\s+", line)]
    if len(titles) != 1:
        findings.append(
            Finding(
                "READINESS_README_TITLE",
                README,
                "README must contain exactly one level-one project title",
                "add one non-template '# Project name' title",
            )
        )
    raw_lines = list(enumerate(text.splitlines(), 1))
    headings = [(n, line) for n, line in lines if re.match(r"^##\s+.+?\s*$", line)]
    section_spans: dict[str, tuple[int, int]] = {}
    for section in ("Setup", "Validation"):
        matches = [
            n
            for n, line in headings
            if re.fullmatch(rf"##\s+{re.escape(section)}\s*", line, re.I)
        ]
        if len(matches) != 1:
            findings.append(
                Finding(
                    "READINESS_README_SECTION",
                    README,
                    f"README must contain exactly one '## {section}' section",
                    f"add one non-empty '## {section}' section",
                )
            )
        else:
            start = matches[0]
            end = next((n for n, line in headings if n > start), len(raw_lines) + 1)
            section_spans[section] = (start, end)
            body = [
                line
                for number, line in raw_lines
                if start < number < end and not re.match(r"^##\s+", line)
            ]
            if not any(line.strip() for line in body):
                findings.append(
                    Finding(
                        "READINESS_README_SECTION_EMPTY",
                        README,
                        f"README section '## {section}' is empty",
                        f"add content to the '## {section}' section",
                    )
                )
    validation_start, validation_end = section_spans.get("Validation", (None, None))
    validation_text = "\n".join(
        line
        for n, line in raw_lines
        if validation_start is not None
        and validation_end is not None
        and validation_start < n < validation_end
    )
    if (
        validation_start is not None
        and validation_end is not None
        and "scripts/validate_repository.py" not in validation_text
    ):
        findings.append(
            Finding(
                "READINESS_README_COMMAND",
                README,
                "README does not name the canonical validation command",
                "document python3.14 scripts/validate_repository.py in the Validation section",
            )
        )


def check_hook(findings: list[Finding]) -> None:
    if not HOOK.exists():
        findings.append(
            Finding(
                "READINESS_HOOK_MISSING",
                HOOK,
                "project-validation hook is missing",
                "create an executable scripts/validate_project.py hook",
            )
        )
        return
    if HOOK.is_symlink() or not HOOK.is_file():
        findings.append(
            Finding(
                "READINESS_HOOK_NOT_EXECUTABLE",
                HOOK,
                "project-validation hook is not a regular file",
                "create an executable scripts/validate_project.py hook",
            )
        )
        return
    if not (HOOK.stat().st_mode & 0o111):
        findings.append(
            Finding(
                "READINESS_HOOK_NOT_EXECUTABLE",
                HOOK,
                "project-validation hook is not executable",
                "chmod +x scripts/validate_project.py",
            )
        )
    text = read_text(HOOK, findings)
    if text is not None and HOOK_SENTINEL in text:
        findings.append(
            Finding(
                "READINESS_HOOK_SENTINEL",
                HOOK,
                "unconfigured hook sentinel remains",
                "replace the stub with project validation commands",
            )
        )


def main(argv: list[str]) -> int:
    if argv:
        print(
            "INTERNAL_READINESS_ERROR: scripts/check_project_readiness.py: unexpected arguments; next: run it without arguments",
            file=sys.stderr,
        )
        return 2
    findings: list[Finding] = []
    try:
        check_prd(findings)
        check_readme(findings)
        check_hook(findings)
    except Exception as exc:  # defensive boundary for an internal evaluation failure
        print(
            f"INTERNAL_READINESS_ERROR: repository: {exc}; next: fix the checker input or implementation",
            file=sys.stderr,
        )
        return 2
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    if any(finding.code == "INTERNAL_READINESS_ERROR" for finding in findings):
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
