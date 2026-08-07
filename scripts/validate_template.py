#!/usr/bin/env python3
"""Validate the template-owned file and skill contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = [
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
]
REQUIRED_SKILLS = [
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
]


def valid_skill_frontmatter(text: str) -> bool:
    match = re.match(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", text, re.S)
    frontmatter = match.group("body") if match else ""
    return bool(
        match
        and re.search(r"^name:\s*.+$", frontmatter, re.M)
        and re.search(r"^description:\s*.+$", frontmatter, re.M)
    )


def required_contract_failures(
    root: Path,
    skill_texts: tuple[tuple[Path, str], ...],
) -> tuple[str, ...]:
    failures = [
        f"missing required file: {relative}"
        for relative in REQUIRED_FILES
        if not (root / relative).is_file()
    ]
    failures.extend(
        f"missing required skill: {(root / '.agents' / 'skills' / skill).relative_to(root)}"
        for skill in REQUIRED_SKILLS
        if not (root / ".agents" / "skills" / skill / "SKILL.md").is_file()
    )
    failures.extend(
        f"invalid skill frontmatter: {path.relative_to(root)}"
        for path, text in skill_texts
        if not valid_skill_frontmatter(text)
    )
    return tuple(failures)


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate_template.py", file=sys.stderr)
        return 2
    skill_paths = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    skill_texts = tuple(
        (path, path.read_text(encoding="utf-8")) for path in skill_paths
    )
    failures = required_contract_failures(ROOT, skill_texts)
    for failure in failures:
        print(
            f"TEMPLATE_CONTRACT_ERROR: {failure}; next: restore the template contract",
            file=sys.stderr,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
