#!/usr/bin/env python3
"""Validate the template-owned file and skill contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = [
    "AGENTS.md", ".agents/AGENTS.md", "README.md", "copier.yml", "docs/prd.md",
    "docs/agents/domain.md", "docs/agents/issue-tracker.md", ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml", ".github/pull_request_template.md", ".github/workflows/ci.yml",
    ".github/workflows/pr-agent-commands.yml", ".github/workflows/pr-agent.yml",
    ".github/workflows/semantic-release.yml", ".pr_agent.toml", ".releaserc",
    "scripts/check-project-readiness.py", "scripts/validate-project.py", "scripts/validate-repository.py",
]
REQUIRED_SKILLS = ["atelier-orchestrator", "code-commit", "code-pull-request", "code-review", "loop-on-ci", "pr-review-loop", "verification-before-completion"]


def main(argv: list[str]) -> int:
    if argv:
        print("usage: scripts/validate-template.py", file=sys.stderr)
        return 2
    failures: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            failures.append(f"missing required file: {relative}")
    for skill in REQUIRED_SKILLS:
        path = ROOT / ".agents" / "skills" / skill / "SKILL.md"
        if not path.is_file():
            failures.append(f"missing required skill: {path.relative_to(ROOT)}")
    for path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(?P<body>.*?)\n---(?:\n|\Z)", text, re.S)
        frontmatter = match.group("body") if match else ""
        if (
            not match
            or not re.search(r"^name:\s*.+$", frontmatter, re.M)
            or not re.search(r"^description:\s*.+$", frontmatter, re.M)
        ):
            failures.append(f"invalid skill frontmatter: {path.relative_to(ROOT)}")
    for failure in failures:
        print(f"TEMPLATE_CONTRACT_ERROR: {failure}; next: restore the template contract", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
