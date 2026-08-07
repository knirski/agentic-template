"""Frozen, serializable template-contract definitions and pure checks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContractRule:
    identity: str
    severity: str
    predicate: str
    satisfier: str


TEMPLATE_RULES: tuple[ContractRule, ...] = (
    ContractRule("required-files", "blocking", "file-present", "template-source"),
    ContractRule("required-skills", "blocking", "skill-present", "template-source"),
    ContractRule(
        "skill-frontmatter", "blocking", "frontmatter-valid", "template-source"
    ),
)


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatible: bool
    reasons: tuple[str, ...] = ()


def canonical_rules() -> tuple[ContractRule, ...]:
    return TEMPLATE_RULES


def compare_rules(
    baseline: tuple[ContractRule, ...], current: tuple[ContractRule, ...]
) -> CompatibilityResult:
    old = {rule.identity: rule for rule in baseline}
    reasons = tuple(
        f"rule changed: {identity}"
        for identity, rule in ((r.identity, r) for r in current)
        if identity in old and rule != old[identity]
    )
    return CompatibilityResult(not reasons, reasons)


def compatibility_corpus() -> tuple[tuple[str, bool], ...]:
    return (("empty-template", False), ("complete-template", True))


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
