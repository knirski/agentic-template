"""Frozen, serializable template-contract definitions and pure checks."""

from __future__ import annotations

import re

REQUIRED_FILES: tuple[str, ...] = (
    "AGENTS.md",
    ".agents/AGENTS.md",
    "README.md",
    "copier.yml",
    "docs/prd.md",
    "docs/agents/domain.md",
    "docs/agents/issue-tracker.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".github/workflows/pr-agent-commands.yml",
    ".github/workflows/pr-agent.yml",
    ".github/workflows/semantic-release.yml",
    ".pr_agent.toml",
    ".releaserc",
    "scripts/check_project_readiness.py",
    "scripts/validate_project.py",
    "scripts/validate_repository.py",
    "scripts/bootstrap/__init__.py",
    "scripts/bootstrap/canonical_json.py",
    "scripts/bootstrap/presentation.py",
    "scripts/bootstrap/readiness.py",
    "scripts/bootstrap/template_contract.py",
    "scripts/bootstrap/validation_program.py",
)

REQUIRED_SKILLS: tuple[str, ...] = (
    "atelier-orchestrator",
    "atelier-setup",
    "code-commit",
    "code-handoff",
    "code-pull-request",
    "code-review",
    "code-subagents",
    "loop-on-ci",
    "modern-python",
    "oracle-debug",
    "oracle-domain-modelling",
    "oracle-grill-me",
    "pr-review-loop",
    "spec-brainstorm",
    "spec-finish",
    "spec-implement",
    "spec-plan",
    "verification-before-completion",
)


def valid_skill_frontmatter(text: str) -> bool:
    match = re.match(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", text, re.S)
    frontmatter = match.group("body") if match else ""
    return bool(
        match
        and re.search(r"^name:[ \t]*.+$", frontmatter, re.M)
        and re.search(r"^description:[ \t]*.+$", frontmatter, re.M)
    )


def required_contract_failures(
    present_files: tuple[str, ...],
    skill_texts: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    present = set(present_files)
    failures = [
        f"missing required file: {relative}"
        for relative in REQUIRED_FILES
        if relative not in present
    ]
    skill_paths = {path for path, _ in skill_texts}
    failures.extend(
        f"missing required skill: .agents/skills/{skill}/SKILL.md"
        for skill in REQUIRED_SKILLS
        if f".agents/skills/{skill}/SKILL.md" not in skill_paths
    )
    failures.extend(
        f"invalid skill frontmatter: {path}"
        for path, text in skill_texts
        if not valid_skill_frontmatter(text)
    )
    return tuple(failures)


def contract_findings(
    missing_files: tuple[str, ...],
    missing_skills: tuple[str, ...],
    invalid_skills: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        [
            *(f"missing required file: {item}" for item in missing_files),
            *(f"missing required skill: {item}" for item in missing_skills),
            *(f"invalid skill frontmatter: {item}" for item in invalid_skills),
        ]
    )
