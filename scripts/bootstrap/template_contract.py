"""Frozen, serializable template-contract definitions and pure checks."""

from __future__ import annotations

import re

REQUIRED_FILES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    ".agents/AGENTS.md",
    ".rygor/source-ownership.json",
    "README.md",
    "copier.yml",
    "docs/prd.md",
    "docs/agents/domain.md",
    "docs/agents/issue-tracker.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".github/workflows/project-validation.yml",
    "scripts/check_project_readiness.py",
    "scripts/check-release-eligibility.py",
    "scripts/validate-project",
    "scripts/validate_repository.py",
    "scripts/bootstrap/__init__.py",
    "scripts/bootstrap/canonical_json.py",
    "scripts/bootstrap/presentation.py",
    "scripts/bootstrap/readiness.py",
    "scripts/bootstrap/readiness_rules.py",
    "scripts/bootstrap/template_contract.py",
    "scripts/bootstrap/validation_program.py",
)

# The source tree is the compiled-managed-artifact fixture: every committed
# ``.github/workflows`` file is either pinned by ``SOURCE_WORKFLOW_SELECTIONS``
# to its canonical compiled render or a source-maintainer artifact excluded from
# generated projects (``test_every_committed_workflow_is_pinned_or_excluded``
# reconciles the committed tree against both sets).  The source ci.yml stays the
# compiled portable baseline (the source repo releases through the maintainer
# workflow and runs no capability job); capability workflow files are
# source-maintainer artifacts excluded from generated projects and compiled
# per-profile by apply, so unselected adopters never receive them.  The source
# never ships Nix workflow files.
SOURCE_WORKFLOW_SELECTIONS: dict[str, tuple[str, ...]] = {
    ".github/workflows/ci.yml": (),
    ".github/workflows/semantic-release.yml": ("semantic-release",),
    ".github/workflows/pr-agent.yml": ("pr-agent-gemini",),
    ".github/workflows/pr-agent-commands.yml": ("pr-agent-gemini",),
}

REQUIRED_SKILLS: tuple[str, ...] = (
    "atelier-orchestrator",
    "atelier-setup",
    "code-commit",
    "code-handoff",
    "code-pull-request",
    "code-review",
    "code-subagents",
    "loop-on-ci",
    "oracle-debug",
    "oracle-domain-modelling",
    "oracle-grill-me",
    "pr-review-loop",
    "python-build-tools",
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


def readiness_rule_catalog_failures() -> tuple[str, ...]:
    """Validate readiness-rule catalog invariants as part of the template contract.

    The catalog is a generated-lifecycle source artifact.  These checks ensure
    internal consistency; the release-time compatibility comparison lives in
    the template validator because it reads the checked-in corpus.
    """
    from scripts.bootstrap.readiness_rules import (
        FROZEN_CATALOG_V1,
    )

    failures: list[str] = []
    if not FROZEN_CATALOG_V1:
        failures.append("readiness-rule catalog is empty")
        return tuple(failures)
    codes = tuple(rule.code for rule in FROZEN_CATALOG_V1)
    if len(set(codes)) != len(codes):
        duplicates = [c for c in codes if codes.count(c) > 1]
        failures.append(f"duplicate readiness-rule codes: {sorted(set(duplicates))}")
    identities = tuple(
        (rule.code, rule.subject_kind, rule.rule) for rule in FROZEN_CATALOG_V1
    )
    if len(set(identities)) != len(identities):
        failures.append("duplicate readiness-rule identities")
    satisfiers = {rule.satisfier for rule in FROZEN_CATALOG_V1}
    if satisfiers != {"adopter-edit"}:
        unexpected = sorted(satisfiers - {"adopter-edit"})
        failures.append(f"unexpected v1 satisfier values: {unexpected}")
    return tuple(failures)


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
    failures.extend(readiness_rule_catalog_failures())
    return tuple(failures)
