"""Declarative readiness-rule catalog for manifest schema v1.

Carries every readiness v1 rule unchanged from the frozen baseline
(design.md § Frozen readiness-rule baseline v1).  The checker derives its
stable paths, markers, and headings from this catalog.

The public surface is compared with the checked-in schema-v1 compatibility
corpus by the template validator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

type Severity = Literal["blocking", "informational"]
type SubjectKind = Literal["path", "repository"]
type OwnedPathClass = Literal["adopter", "managed"]
type Satisfier = Literal[
    "initial-plan",
    "managed-render",
    "adopter-edit",
    "external-action",
]
type PredicateKind = Literal[
    "text-absent",
    "heading-exactly-once-in-order",
    "requirement-format",
    "requirement-unique",
    "requirement-title-nonempty",
    "requirement-body-nonempty",
    "requirement-present",
    "section-exactly-one-nonempty",
    "level-one-title-count",
    "section-contains-text",
    "file-exists",
    "file-regular",
    "file-executable",
]


# ---------------------------------------------------------------------------
# Readiness rule definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadinessRuleDefinition:
    """A single frozen readiness-rule definition.

    Identity ``(code, subject_kind, rule)`` must be unique across the
    catalog.  ``code`` is the stable diagnostic identifier shown to
    adopters.  ``rule`` is the logical check name, stable across message
    rewording; in v1 ``rule`` equals ``code`` for single-finding rules
    and is shared across grouped findings (e.g., the three heading-check
    findings share ``rule = "prd-headings"``).
    """

    code: str
    subject_kind: SubjectKind
    rule: str
    severity: Severity
    owned_path_class: OwnedPathClass
    satisfier: Satisfier
    predicate: PredicateKind
    # Predicate-specific canonical immutable values.  ``path`` is always
    # the repository-relative target file.  ``dict`` is used for
    # value-comparable canonical representation; the catalog tuple and
    # frozen dataclass prevent reassignment, and the values are never
    # mutated after construction.
    parameters: dict[str, str | int | tuple[str, ...]]


def _rule(
    code: str,
    predicate: PredicateKind,
    parameters: dict[str, str | int | tuple[str, ...]],
    *,
    rule: str | None = None,
) -> ReadinessRuleDefinition:
    return ReadinessRuleDefinition(
        code=code,
        subject_kind="path",
        rule=rule or code,
        severity="blocking",
        owned_path_class="adopter",
        satisfier="adopter-edit",
        predicate=predicate,
        parameters=parameters,
    )


# ---------------------------------------------------------------------------
# Frozen readiness-rule baseline v1
# ---------------------------------------------------------------------------
# Every rule is unchanged from the released v1.3.0 checker and the
# bootstrap marker table.  The checked-in compatibility corpus freezes this
# surface for released schema-v1 projects.
# ---------------------------------------------------------------------------

_REQUIRED_PRD_HEADINGS: tuple[str, ...] = (
    "Problem",
    "Goals",
    "Non-goals",
    "Users and workflows",
    "Requirements",
    "Quality attributes",
    "Release criteria",
    "Open questions",
)

FROZEN_CATALOG_V1: tuple[ReadinessRuleDefinition, ...] = (
    # -- PRD rules (docs/prd.md) ------------------------------------------
    _rule(
        "READINESS_PRD_MARKER",
        "text-absent",
        {
            "path": "docs/prd.md",
            "patterns": ("<!-- agentic-template:placeholder:prd -->",),
            "match": "text",
        },
    ),
    _rule(
        "READINESS_PRD_BOILERPLATE",
        "text-absent",
        {
            "path": "docs/prd.md",
            "patterns": (
                "This file is authoritative for the Agentic Delivery Template",
            ),
            "match": "text",
        },
    ),
    _rule(
        "READINESS_PRD_HEADING_MISSING",
        "heading-exactly-once-in-order",
        {"path": "docs/prd.md", "headings": _REQUIRED_PRD_HEADINGS},
        rule="prd-headings",
    ),
    _rule(
        "READINESS_PRD_HEADING_DUPLICATE",
        "heading-exactly-once-in-order",
        {"path": "docs/prd.md", "headings": _REQUIRED_PRD_HEADINGS},
        rule="prd-headings",
    ),
    _rule(
        "READINESS_PRD_HEADING_ORDER",
        "heading-exactly-once-in-order",
        {"path": "docs/prd.md", "headings": _REQUIRED_PRD_HEADINGS},
        rule="prd-headings",
    ),
    # -- Requirement rules (docs/prd.md Requirements section) -------------
    _rule(
        "READINESS_REQUIREMENT_MISSING",
        "requirement-present",
        {"path": "docs/prd.md", "min_count": 1},
    ),
    _rule(
        "READINESS_REQUIREMENT_ID",
        "requirement-format",
        {
            "path": "docs/prd.md",
            "declaration_pattern": r"^###\s+(REQ-(\d{3})):\s*(.*?)\s*$",
            "valid_range": ("001", "999"),
        },
    ),
    _rule(
        "READINESS_REQUIREMENT_DUPLICATE",
        "requirement-unique",
        {"path": "docs/prd.md"},
    ),
    _rule(
        "READINESS_REQUIREMENT_TITLE",
        "requirement-title-nonempty",
        {"path": "docs/prd.md"},
    ),
    _rule(
        "READINESS_REQUIREMENT_BODY",
        "requirement-body-nonempty",
        {"path": "docs/prd.md"},
    ),
    # -- README rules (README.md) ------------------------------------------
    _rule(
        "READINESS_README_MARKER",
        "text-absent",
        {
            "path": "README.md",
            "patterns": ("<!-- agentic-template:placeholder:readme -->",),
            "match": "text",
        },
    ),
    _rule(
        "READINESS_README_BOILERPLATE",
        "text-absent",
        {
            "path": "README.md",
            "patterns": (
                "# Agentic Delivery Template",
                "A language-neutral GitHub repository template for planning",
            ),
            "match": "text",
        },
    ),
    _rule(
        "READINESS_README_TITLE",
        "level-one-title-count",
        {"path": "README.md", "count": 1},
    ),
    _rule(
        "READINESS_README_SECTION",
        "section-exactly-one-nonempty",
        {"path": "README.md", "sections": ("Setup", "Validation")},
        rule="readme-sections",
    ),
    _rule(
        "READINESS_README_SECTION_EMPTY",
        "section-exactly-one-nonempty",
        {"path": "README.md", "sections": ("Setup", "Validation")},
        rule="readme-sections",
    ),
    _rule(
        "READINESS_README_COMMAND",
        "section-contains-text",
        {
            "path": "README.md",
            "section": "Validation",
            "required_text": "scripts/validate_repository.py",
        },
    ),
    # -- Hook rules (scripts/validate-project) ----------------------------
    _rule(
        "READINESS_HOOK_MISSING",
        "file-exists",
        {"path": "scripts/validate-project"},
    ),
    _rule(
        "READINESS_HOOK_NOT_REGULAR",
        "file-regular",
        {"path": "scripts/validate-project"},
    ),
    _rule(
        "READINESS_HOOK_NOT_EXECUTABLE",
        "file-executable",
        {"path": "scripts/validate-project"},
    ),
    _rule(
        "READINESS_HOOK_SENTINEL",
        "text-absent",
        {
            "path": "scripts/validate-project",
            "patterns": ("agentic-template:unconfigured:validate-project",),
            "match": "text",
        },
    ),
    # -- Bootstrap slot marker rules (marker table) -----------------------
    _rule(
        "READINESS_SECURITY_MARKER",
        "text-absent",
        {
            "path": "SECURITY.md",
            "patterns": ("<!-- agentic-template:placeholder:security -->",),
            "match": "text",
            "slot": "security_policy",
        },
    ),
    _rule(
        "READINESS_CONTRIBUTING_MARKER",
        "text-absent",
        {
            "path": "CONTRIBUTING.md",
            "patterns": ("<!-- agentic-template:placeholder:contributing -->",),
            "match": "text",
            "slot": "contributing",
        },
    ),
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

_RULES_BY_CODE: dict[str, ReadinessRuleDefinition] = {
    rule.code: rule for rule in FROZEN_CATALOG_V1
}
FINDING_CODES: frozenset[str] = frozenset(_RULES_BY_CODE)


def _json_compatible(value: object) -> object:
    if isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
        return [_json_compatible(item) for item in items]
    if isinstance(value, dict):
        mapping = cast(Mapping[str, object], value)
        return {key: _json_compatible(item) for key, item in mapping.items()}
    return value


def readiness_rule_surface() -> tuple[dict[str, object], ...]:
    """Return the JSON-compatible stable surface of the readiness catalog."""

    return tuple(
        {
            "code": rule.code,
            "subject_kind": rule.subject_kind,
            "rule": rule.rule,
            "severity": rule.severity,
            "owned_path_class": rule.owned_path_class,
            "satisfier": rule.satisfier,
            "predicate": rule.predicate,
            "parameters": _json_compatible(rule.parameters),
        }
        for rule in FROZEN_CATALOG_V1
    )


def rules_by_code() -> dict[str, ReadinessRuleDefinition]:
    """Mapping from finding code to its frozen rule definition."""
    return dict(_RULES_BY_CODE)


def rule_by_code(code: str) -> ReadinessRuleDefinition:
    """Look up a rule by its finding code.

    Raises ``KeyError`` if the code is not in the frozen catalog.
    """
    rule = _RULES_BY_CODE.get(code)
    if rule is None:
        raise KeyError(code)
    return rule


def finding_code_is_known(code: str) -> bool:
    """Return ``True`` if the finding code belongs to the frozen catalog."""
    return code in FINDING_CODES


# ---------------------------------------------------------------------------
# Derived constants — single source of truth
# ---------------------------------------------------------------------------
# These derive from the frozen catalog and are the single source of truth for
# the readiness checker and bootstrap policy.
# ---------------------------------------------------------------------------


def _text_patterns(rule: ReadinessRuleDefinition) -> tuple[str, ...]:
    patterns = rule.parameters["patterns"]
    assert isinstance(patterns, tuple)
    return patterns


def _path(rule: ReadinessRuleDefinition) -> str:
    path = rule.parameters["path"]
    assert isinstance(path, str)
    return path


def _headings(rule: ReadinessRuleDefinition) -> tuple[str, ...]:
    headings = rule.parameters["headings"]
    assert isinstance(headings, tuple)
    return headings


def _sections(rule: ReadinessRuleDefinition) -> tuple[str, ...]:
    sections = rule.parameters["sections"]
    assert isinstance(sections, tuple)
    return sections


def _str_param(rule: ReadinessRuleDefinition, key: str) -> str:
    value = rule.parameters[key]
    assert isinstance(value, str)
    return value


def _int_param(rule: ReadinessRuleDefinition, key: str) -> int:
    value = rule.parameters[key]
    assert isinstance(value, int)
    return value


# PRD constants
PRD_MARKER: str = _text_patterns(rule_by_code("READINESS_PRD_MARKER"))[0]
PRD_BOILERPLATE_PATTERN: str = _text_patterns(
    rule_by_code("READINESS_PRD_BOILERPLATE")
)[0]
REQUIRED_PRD_HEADINGS: tuple[str, ...] = _headings(
    rule_by_code("READINESS_PRD_HEADING_MISSING")
)
REQUIREMENT_DECLARATION_PATTERN: str = _str_param(
    rule_by_code("READINESS_REQUIREMENT_ID"), "declaration_pattern"
)

# README constants
README_MARKER: str = _text_patterns(rule_by_code("READINESS_README_MARKER"))[0]
README_BOILERPLATE_PATTERNS: tuple[str, ...] = _text_patterns(
    rule_by_code("READINESS_README_BOILERPLATE")
)
REQUIRED_README_SECTIONS: tuple[str, ...] = _sections(
    rule_by_code("READINESS_README_SECTION")
)
README_VALIDATION_COMMAND: str = _str_param(
    rule_by_code("READINESS_README_COMMAND"), "required_text"
)
README_TITLE_COUNT: int = _int_param(rule_by_code("READINESS_README_TITLE"), "count")

# Hook constants
HOOK_PATH: str = _path(rule_by_code("READINESS_HOOK_MISSING"))
HOOK_SENTINEL: str = _text_patterns(rule_by_code("READINESS_HOOK_SENTINEL"))[0]

# Slot marker constants
SECURITY_MARKER: str = _text_patterns(rule_by_code("READINESS_SECURITY_MARKER"))[0]
CONTRIBUTING_MARKER: str = _text_patterns(
    rule_by_code("READINESS_CONTRIBUTING_MARKER")
)[0]


# ---------------------------------------------------------------------------
# Satisfier classification
# ---------------------------------------------------------------------------


def satisfier_compatibility(satisfier: Satisfier) -> str:
    """Map a satisfier to its template-evolution compatibility class.

    The closed match ensures the classification covers every member of
    the ``Satisfier`` union, which the test suite verifies.
    """
    match satisfier:
        case "initial-plan":
            return "plan"
        case "managed-render":
            return "render"
        case "adopter-edit":
            return "edit"
        case "external-action":
            return "external"
