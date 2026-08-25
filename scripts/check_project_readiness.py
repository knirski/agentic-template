#!/usr/bin/env python3
"""Inspect generated-project readiness without mutating project files."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.readiness import (  # noqa: E402
    Finding as CoreFinding,
)
from scripts.bootstrap.readiness import (  # noqa: E402
    MechanicalReadinessResult,
    Repository,
    SubjectPath,
)
from scripts.bootstrap.readiness_rules import (  # noqa: E402
    CONTRIBUTING_MARKER,
    HOOK_PATH,
    HOOK_SENTINEL,
    PRD_BOILERPLATE_PATTERN,
    PRD_MARKER,
    README_BOILERPLATE_PATTERNS,
    README_MARKER,
    README_VALIDATION_COMMAND,
    REQUIRED_PRD_HEADINGS,
    REQUIRED_README_SECTIONS,
    REQUIREMENT_DECLARATION_PATTERN,
    SECURITY_MARKER,
    finding_code_is_known,
    rule_by_code,
)
from scripts.bootstrap.validation_presentation import (  # noqa: E402
    parse_options,
    render_findings,
    render_usage_error,
    requested_json,
)

PRD = ROOT / "docs" / "prd.md"
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
HOOK = ROOT / HOOK_PATH


def _finding(
    code: str,
    path: Path,
    message: str,
    next_action: str,
) -> CoreFinding:
    """Build the structured finding shared by readiness and bootstrap."""
    try:
        subject = path.relative_to(ROOT).as_posix()
    except ValueError:
        subject = path.as_posix()
    definition = rule_by_code(code) if finding_code_is_known(code) else None
    return CoreFinding(
        code=code,
        subject_at=Repository() if subject == "" else SubjectPath(subject),
        subject=subject,
        rule=definition.rule if definition is not None else code,
        severity=definition.severity if definition is not None else "blocking",
        message=message,
        next_action=next_action,
    )


@dataclass(frozen=True)
class HookState:
    path: Path
    exists: bool
    regular_file: bool
    executable: bool
    text: str | None


def visible_lines(text: str) -> tuple[tuple[int, str], ...]:
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
    return tuple(result)


def evaluate_prd(text: str, path: Path) -> tuple[CoreFinding, ...]:
    findings: list[CoreFinding] = []
    lines = visible_lines(text)
    if PRD_MARKER in text:
        findings.append(
            _finding(
                "READINESS_PRD_MARKER",
                path,
                "template replacement marker remains",
                "replace the marked PRD with product requirements",
            )
        )
    if PRD_BOILERPLATE_PATTERN in text:
        findings.append(
            _finding(
                "READINESS_PRD_BOILERPLATE",
                path,
                "template-source boilerplate remains",
                "replace the introductory template contract",
            )
        )

    headings = tuple(
        (number, match.group(1).strip())
        for number, line in lines
        if (match := re.match(r"^##\s+(.+?)\s*$", line))
    )
    positions: list[int] = []
    for title in REQUIRED_PRD_HEADINGS:
        # A list (not tuple) keeps basedpyright's indexing analysis happy:
        # `tuple(generator)` is inferred as `tuple[()]`, which basic mode flags
        # at `matches[0]` below even though `matches` is non-empty in this
        # `else` branch. Behaviour is identical (only len()/index/[] are used).
        matches = [number for number, heading in headings if heading == title]
        if not matches:
            findings.append(
                _finding(
                    "READINESS_PRD_HEADING_MISSING",
                    path,
                    f"required heading '## {title}' is missing",
                    f"add exactly one '## {title}' section",
                )
            )
        else:
            if len(matches) > 1:
                findings.append(
                    _finding(
                        "READINESS_PRD_HEADING_DUPLICATE",
                        path,
                        f"heading '## {title}' appears {len(matches)} times",
                        f"keep one '## {title}' section",
                    )
                )
            positions.append(matches[0])
    if positions and positions != sorted(positions):
        findings.append(
            _finding(
                "READINESS_PRD_HEADING_ORDER",
                path,
                "required headings are out of order",
                "reorder the required level-two sections",
            )
        )

    req_section = next(
        (number for number, heading in headings if heading == "Requirements"), None
    )
    if req_section is None:
        return tuple(findings)
    req_end = next(
        (number for number, _ in headings if number > req_section),
        len(text.splitlines()) + 1,
    )
    req_lines = tuple(
        (number, line) for number, line in lines if req_section < number < req_end
    )
    declarations: dict[str, tuple[int, str]] = {}
    declaration_pattern = re.compile(REQUIREMENT_DECLARATION_PATTERN)
    for number, line in req_lines:
        match = declaration_pattern.match(line)
        if match:
            identifier, digits, title = match.groups()
            if digits == "000":
                findings.append(
                    _finding(
                        "READINESS_REQUIREMENT_ID",
                        path,
                        f"requirement {identifier} has an invalid identifier",
                        "use an identifier from REQ-001 through REQ-999",
                    )
                )
            if identifier in declarations:
                findings.append(
                    _finding(
                        "READINESS_REQUIREMENT_DUPLICATE",
                        path,
                        f"requirement {identifier} is declared more than once",
                        "keep one declaration for the identifier",
                    )
                )
            declarations[identifier] = (number, title)
            if title == "":
                findings.append(
                    _finding(
                        "READINESS_REQUIREMENT_TITLE",
                        path,
                        f"requirement {identifier} has an empty title",
                        "add a non-empty requirement title",
                    )
                )
            continue
        if re.match(r"^###\s+(REQ-[^:]+):", line):
            findings.append(
                _finding(
                    "READINESS_REQUIREMENT_ID",
                    path,
                    "requirement heading has an invalid identifier",
                    "use an identifier from REQ-001 through REQ-999",
                )
            )
    if not declarations:
        findings.append(
            _finding(
                "READINESS_REQUIREMENT_MISSING",
                path,
                "no requirement declaration exists",
                "add at least one ### REQ-001: Title declaration",
            )
        )
    for identifier, (line_number, _) in declarations.items():
        next_heading = next(
            (
                number
                for number, line in req_lines
                if number > line_number and line.startswith("### ")
            ),
            req_end,
        )
        body = tuple(
            line.strip()
            for number, line in req_lines
            if line_number < number < next_heading and line.strip()
        )
        if not body:
            findings.append(
                _finding(
                    "READINESS_REQUIREMENT_BODY",
                    path,
                    f"requirement {identifier} has no body",
                    "add explanatory and acceptance content below the requirement heading",
                )
            )
    return tuple(findings)


def evaluate_readme(text: str, path: Path) -> tuple[CoreFinding, ...]:
    findings: list[CoreFinding] = []
    lines = visible_lines(text)
    if README_MARKER in text:
        findings.append(
            _finding(
                "READINESS_README_MARKER",
                path,
                "template replacement marker remains",
                "replace the marked README with project documentation",
            )
        )
    if any(pattern in text for pattern in README_BOILERPLATE_PATTERNS):
        findings.append(
            _finding(
                "READINESS_README_BOILERPLATE",
                path,
                "template README boilerplate remains",
                "replace the template introduction with project documentation",
            )
        )
    titles = tuple(line for _, line in lines if re.match(r"^#\s+", line))
    if len(titles) != 1:
        findings.append(
            _finding(
                "READINESS_README_TITLE",
                path,
                "README must contain exactly one level-one project title",
                "add one non-template '# Project name' title",
            )
        )
    raw_lines = tuple(enumerate(text.splitlines(), 1))
    headings = tuple(
        (number, line) for number, line in lines if re.match(r"^##\s+.+?\s*$", line)
    )
    section_spans: dict[str, tuple[int, int]] = {}
    for section in REQUIRED_README_SECTIONS:
        matches = tuple(
            number
            for number, line in headings
            if re.fullmatch(rf"##\s+{re.escape(section)}\s*", line, re.I)
        )
        if len(matches) != 1:
            findings.append(
                _finding(
                    "READINESS_README_SECTION",
                    path,
                    f"README must contain exactly one '## {section}' section",
                    f"add one non-empty '## {section}' section",
                )
            )
        else:
            start = matches[0]
            end = next(
                (number for number, _ in headings if number > start), len(raw_lines) + 1
            )
            section_spans[section] = (start, end)
            body = tuple(
                line
                for number, line in raw_lines
                if start < number < end and not re.match(r"^##\s+", line)
            )
            if not any(line.strip() for line in body):
                findings.append(
                    _finding(
                        "READINESS_README_SECTION_EMPTY",
                        path,
                        f"README section '## {section}' is empty",
                        f"add content to the '## {section}' section",
                    )
                )
    validation_start, validation_end = section_spans.get("Validation", (None, None))
    validation_text = "\n".join(
        line
        for number, line in raw_lines
        if validation_start is not None
        and validation_end is not None
        and validation_start < number < validation_end
    )
    if (
        validation_start is not None
        and validation_end is not None
        and README_VALIDATION_COMMAND not in validation_text
    ):
        findings.append(
            _finding(
                "READINESS_README_COMMAND",
                path,
                "README does not name the canonical validation command",
                "document uv run --python 3.14 scripts/validate_repository.py in the Validation section",
            )
        )
    return tuple(findings)


def evaluate_hook(state: HookState) -> tuple[CoreFinding, ...]:
    if not state.exists:
        return (
            _finding(
                "READINESS_HOOK_MISSING",
                state.path,
                "project-validation hook is missing",
                f"create an executable {HOOK_PATH} hook",
            ),
        )
    if not state.regular_file:
        return (
            _finding(
                "READINESS_HOOK_NOT_REGULAR",
                state.path,
                "project-validation hook is not a regular file",
                f"create a regular executable {HOOK_PATH} hook",
            ),
        )
    findings: list[CoreFinding] = []
    if not state.executable:
        findings.append(
            _finding(
                "READINESS_HOOK_NOT_EXECUTABLE",
                state.path,
                "project-validation hook is not executable",
                f"chmod +x {HOOK_PATH}",
            )
        )
    if state.text is not None and HOOK_SENTINEL in state.text:
        findings.append(
            _finding(
                "READINESS_HOOK_SENTINEL",
                state.path,
                "unconfigured hook sentinel remains",
                "replace the stub with project validation commands",
            )
        )
    return tuple(findings)


def evaluate_seed_slot(
    value: tuple[str, Path] | None,
    *,
    marker: str,
    code: str,
    next_action: str,
) -> tuple[CoreFinding, ...]:
    if value is None or marker not in value[0]:
        return ()
    return (
        _finding(
            code,
            value[1],
            "template replacement marker remains",
            next_action,
        ),
    )


def evaluate_readiness(
    *,
    prd: tuple[str, Path] | None,
    readme: tuple[str, Path] | None,
    hook: HookState,
    security_policy: tuple[str, Path] | None = None,
    contributing: tuple[str, Path] | None = None,
    initial_findings: tuple[CoreFinding, ...] = (),
) -> tuple[CoreFinding, ...]:
    findings = list(initial_findings)
    if prd is not None:
        findings.extend(evaluate_prd(*prd))
    if readme is not None:
        findings.extend(evaluate_readme(*readme))
    findings.extend(
        evaluate_seed_slot(
            security_policy,
            marker=SECURITY_MARKER,
            code="READINESS_SECURITY_MARKER",
            next_action="replace the marked security policy with project policy",
        )
    )
    findings.extend(
        evaluate_seed_slot(
            contributing,
            marker=CONTRIBUTING_MARKER,
            code="READINESS_CONTRIBUTING_MARKER",
            next_action="replace the marked contributing guide with project guidance",
        )
    )
    findings.extend(evaluate_hook(hook))
    return tuple(sorted(findings, key=lambda finding: finding.identity()))


def mechanical_readiness(
    findings: tuple[CoreFinding, ...],
) -> MechanicalReadinessResult:
    """Return the shared structured result used by bootstrap gating."""
    return MechanicalReadinessResult(1, findings)


def exit_code(findings: tuple[CoreFinding, ...]) -> int:
    if any(finding.code == "INTERNAL_READINESS_ERROR" for finding in findings):
        return 2
    return 1 if any(finding.severity == "blocking" for finding in findings) else 0


def read_text(path: Path, findings: list[CoreFinding]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        findings.append(
            _finding(
                "READINESS_MISSING_FILE",
                path,
                "file is missing",
                "restore the required file",
            )
        )
    except (OSError, UnicodeError) as exc:
        findings.append(
            _finding(
                "INTERNAL_READINESS_ERROR",
                path,
                f"cannot read file ({exc})",
                "fix the file and rerun validation",
            )
        )
    return None


def inspect_hook(path: Path, findings: list[CoreFinding]) -> HookState:
    if not path.exists():
        return HookState(path, False, False, False, None)
    if path.is_symlink() or not path.is_file():
        return HookState(path, True, False, False, None)
    executable = bool(path.stat().st_mode & 0o111)
    text = read_text(path, findings)
    return HookState(path, True, True, executable, text)


def main(argv: list[str]) -> int:
    options = parse_options(argv)
    if options is None:
        return render_usage_error(
            "check_project_readiness",
            (
                "READINESS_USAGE_ERROR: scripts/check_project_readiness.py: invalid presentation options; "
                "next: use --format text|json --color auto|always|never --explain --quiet"
            ),
            json_output=requested_json(argv),
        )
    initial_findings: list[CoreFinding] = []
    try:
        prd_text = read_text(PRD, initial_findings)
        readme_text = read_text(README, initial_findings)
        security_text = read_text(SECURITY, initial_findings)
        contributing_text = read_text(CONTRIBUTING, initial_findings)
        hook_state = inspect_hook(HOOK, initial_findings)
        findings = evaluate_readiness(
            prd=(prd_text, PRD) if prd_text is not None else None,
            readme=(readme_text, README) if readme_text is not None else None,
            security_policy=(security_text, SECURITY)
            if security_text is not None
            else None,
            contributing=(contributing_text, CONTRIBUTING)
            if contributing_text is not None
            else None,
            hook=hook_state,
            initial_findings=tuple(initial_findings),
        )
    except Exception as exc:  # defensive boundary for an internal evaluation failure
        return render_findings(
            command="check_project_readiness",
            findings=(),
            exit_code=2,
            options=options,
            diagnostic=(
                "INTERNAL_READINESS_ERROR: repository: "
                + str(exc)
                + "; next: fix the checker input or implementation"
            ),
        )
    return render_findings(
        command="check_project_readiness",
        findings=findings,
        exit_code=exit_code(findings),
        options=options,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
