"""Tests for the frozen readiness-rule catalog."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.bootstrap.readiness import Finding, SubjectPath, finding_matches_catalog
from scripts.bootstrap.readiness_rules import (
    FINDING_CODES,
    FROZEN_CATALOG_V1,
    PRD_MARKER,
    README_MARKER,
    README_VALIDATION_COMMAND,
    REQUIRED_PRD_HEADINGS,
    REQUIRED_README_SECTIONS,
    ReadinessRuleDefinition,
    finding_code_is_known,
    rule_by_code,
    rules_by_code,
    satisfier_compatibility,
)

ROOT = Path(__file__).resolve().parent.parent

# The complete set of finding codes produced by the old checker and
# the bootstrap slot-placeholder machinery.  A finding code not in this
# set is missing from the catalog.
_OLD_CHECKER_CODES: tuple[str, ...] = (
    "READINESS_PRD_MARKER",
    "READINESS_PRD_BOILERPLATE",
    "READINESS_PRD_HEADING_MISSING",
    "READINESS_PRD_HEADING_DUPLICATE",
    "READINESS_PRD_HEADING_ORDER",
    "READINESS_REQUIREMENT_MISSING",
    "READINESS_REQUIREMENT_ID",
    "READINESS_REQUIREMENT_DUPLICATE",
    "READINESS_REQUIREMENT_TITLE",
    "READINESS_REQUIREMENT_BODY",
    "READINESS_README_MARKER",
    "READINESS_README_BOILERPLATE",
    "READINESS_README_TITLE",
    "READINESS_README_SECTION",
    "READINESS_README_SECTION_EMPTY",
    "READINESS_README_COMMAND",
    "READINESS_HOOK_MISSING",
    "READINESS_HOOK_NOT_REGULAR",
    "READINESS_HOOK_NOT_EXECUTABLE",
    "READINESS_HOOK_SENTINEL",
)
_SLOT_PLACEHOLDER_CODES: tuple[str, ...] = (
    "READINESS_SECURITY_MARKER",
    "READINESS_CONTRIBUTING_MARKER",
)
_ALL_SHARED_CORE_CODES: tuple[str, ...] = (
    *_OLD_CHECKER_CODES,
    *_SLOT_PLACEHOLDER_CODES,
)


def test_catalog_covers_all_old_checker_codes() -> None:
    for code in _OLD_CHECKER_CODES:
        assert code in FINDING_CODES, f"missing catalog entry: {code}"


def test_catalog_covers_slot_placeholder_codes() -> None:
    for code in _SLOT_PLACEHOLDER_CODES:
        assert code in FINDING_CODES, f"missing catalog entry: {code}"


def test_catalog_covers_all_shared_core_codes() -> None:
    for code in _ALL_SHARED_CORE_CODES:
        assert finding_code_is_known(code), f"shared-core code not in catalog: {code}"


def test_catalog_codes_match_frozen_v1_baseline() -> None:
    expected_codes = set(_ALL_SHARED_CORE_CODES)
    catalog_codes = {rule.code for rule in FROZEN_CATALOG_V1}
    assert catalog_codes == expected_codes
    assert set(FINDING_CODES) == catalog_codes


def test_all_rules_are_blocking() -> None:
    for rule in FROZEN_CATALOG_V1:
        assert rule.severity == "blocking"


def test_all_rules_are_adopter_owned() -> None:
    for rule in FROZEN_CATALOG_V1:
        assert rule.owned_path_class == "adopter"


def test_all_rules_are_path_subject_kind() -> None:
    for rule in FROZEN_CATALOG_V1:
        assert rule.subject_kind == "path"


def test_no_duplicate_identities() -> None:
    identities = [
        (rule.code, rule.subject_kind, rule.rule) for rule in FROZEN_CATALOG_V1
    ]
    assert len(set(identities)) == len(identities)


def test_no_duplicate_codes() -> None:
    codes = [rule.code for rule in FROZEN_CATALOG_V1]
    assert len(set(codes)) == len(codes)


def test_lookup_by_code_returns_correct_rule() -> None:
    rule = rule_by_code("READINESS_PRD_MARKER")
    assert rule.predicate == "text-absent"
    patterns = rule.parameters["patterns"]
    assert isinstance(patterns, tuple)
    assert "placeholder:prd" in patterns[0]


def test_rules_by_code_returns_full_mapping() -> None:
    mapping = rules_by_code()
    assert len(mapping) == len(FROZEN_CATALOG_V1)


def test_satisfier_compatibility_covers_all_members() -> None:
    for satisfier in (
        "initial-plan",
        "managed-render",
        "adopter-edit",
        "external-action",
    ):
        result = satisfier_compatibility(satisfier)
        assert isinstance(result, str)
        assert len(result) > 0


def test_all_v1_rules_use_adopter_edit() -> None:
    for rule in FROZEN_CATALOG_V1:
        assert rule.satisfier == "adopter-edit", (
            f"{rule.code} has unexpected satisfier: {rule.satisfier}"
        )


def test_all_predicate_kinds_used() -> None:
    used = {rule.predicate for rule in FROZEN_CATALOG_V1}
    expected = {
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
    }
    assert used == expected


def test_prd_marker_matches_catalog() -> None:
    rule = rule_by_code("READINESS_PRD_MARKER")
    assert rule.parameters["patterns"][0] == PRD_MARKER  # pyright: ignore[reportIndexIssue]


def test_readme_marker_matches_catalog() -> None:
    rule = rule_by_code("READINESS_README_MARKER")
    assert rule.parameters["patterns"][0] == README_MARKER  # pyright: ignore[reportIndexIssue]


def test_required_prd_headings_match_catalog() -> None:
    rule = rule_by_code("READINESS_PRD_HEADING_MISSING")
    assert rule.parameters["headings"] == REQUIRED_PRD_HEADINGS


def test_required_readme_sections_match_catalog() -> None:
    rule = rule_by_code("READINESS_README_SECTION")
    assert rule.parameters["sections"] == REQUIRED_README_SECTIONS


def test_readme_validation_command_matches_catalog() -> None:
    rule = rule_by_code("READINESS_README_COMMAND")
    assert rule.parameters["required_text"] == README_VALIDATION_COMMAND


def test_finding_matches_catalog_for_known_codes() -> None:
    for code in _ALL_SHARED_CORE_CODES:
        assert finding_matches_catalog(code), (
            f"shared-core code not matched by catalog: {code}"
        )


def test_finding_matches_catalog_rejects_unknown() -> None:
    assert not finding_matches_catalog("UNKNOWN_CODE")
    assert not finding_matches_catalog("READINESS_FAKE")


def test_finding_code_is_known_for_all_codes() -> None:
    for code in FINDING_CODES:
        assert finding_code_is_known(code)


def test_finding_code_is_known_rejects_unknown() -> None:
    assert not finding_code_is_known("UNKNOWN_CODE")


def test_findings_from_shared_core_have_matching_catalog_entry() -> None:
    """Construct sample findings and verify they match catalog entries."""
    codes_to_check = [
        "READINESS_PRD_MARKER",
        "READINESS_PRD_HEADING_MISSING",
        "READINESS_REQUIREMENT_ID",
        "READINESS_README_SECTION",
        "READINESS_HOOK_SENTINEL",
        "READINESS_SECURITY_MARKER",
    ]
    for code in codes_to_check:
        finding = Finding(
            code=code,
            subject_at=SubjectPath("docs/prd.md"),
            subject="docs/prd.md",
            rule=code,
            severity="blocking",
            message="test",
            next_action="fix",
        )
        assert finding_matches_catalog(finding.code), (
            f"Finding({finding.code}) not in catalog"
        )


def test_corpus_fixture_exists() -> None:
    corpus_path = ROOT / "scripts" / "fixtures" / "readiness-rule-catalog-v1.json"
    assert corpus_path.is_file()


def test_template_validator_accepts_the_live_corpus() -> None:
    from scripts.validate_template import validate_readiness_rule_catalog

    assert validate_readiness_rule_catalog(ROOT) == ()


def test_template_validator_rejects_malformed_corpus_shapes() -> None:
    from scripts import validate_template

    documents = (
        b"[]",
        b'{"schema_version": 2}',
        b'{"schema_version": 1, "rules": [1]}',
    )
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        corpus = root / "scripts/fixtures/readiness-rule-catalog-v1.json"
        corpus.parent.mkdir(parents=True)
        for document in documents:
            _ = corpus.write_bytes(document)
            assert len(validate_template.validate_readiness_rule_catalog(root)) == 1


def test_new_blocking_adopter_rule_is_rejected() -> None:
    from scripts import validate_template
    from scripts.bootstrap.readiness_rules import readiness_rule_surface

    added = {
        "code": "READINESS_NEW",
        "subject_kind": "path",
        "rule": "READINESS_NEW",
        "severity": "blocking",
        "owned_path_class": "adopter",
        "satisfier": "adopter-edit",
        "predicate": "file-exists",
        "parameters": {"path": "NEW.md"},
    }
    with patch.object(
        validate_template,
        "readiness_rule_surface",
        return_value=(*readiness_rule_surface(), added),
        create=True,
    ):
        failures = validate_template.validate_readiness_rule_catalog(ROOT)
    assert "added blocking adopter readiness rules" in failures[0]


def test_stable_identity_change_is_rejected() -> None:
    from scripts import validate_template
    from scripts.bootstrap.readiness_rules import readiness_rule_surface

    changed = {
        **readiness_rule_surface()[0],
        "rule": "READINESS_REBOUND",
    }
    with patch.object(
        validate_template,
        "readiness_rule_surface",
        return_value=(changed, *readiness_rule_surface()[1:]),
        create=True,
    ):
        failures = validate_template.validate_readiness_rule_catalog(ROOT)
    assert "removed stable readiness rules" in failures[0]
    assert "added blocking adopter readiness rules" in failures[0]


def test_stable_rule_change_is_rejected() -> None:
    from scripts import validate_template
    from scripts.bootstrap.readiness_rules import readiness_rule_surface

    live = readiness_rule_surface()
    changed = {**live[0], "severity": "advisory"}
    with patch.object(
        validate_template,
        "readiness_rule_surface",
        return_value=(changed, *live[1:]),
        create=True,
    ):
        failures = validate_template.validate_readiness_rule_catalog(ROOT)
    assert "changed stable readiness rules" in failures[0]


def test_frozen_catalog_is_tuple() -> None:
    assert isinstance(FROZEN_CATALOG_V1, tuple)


def test_all_entries_are_readiness_rule_definition() -> None:
    for rule in FROZEN_CATALOG_V1:
        assert isinstance(rule, ReadinessRuleDefinition)


def test_catalog_is_immutable() -> None:
    assert isinstance(FROZEN_CATALOG_V1, tuple)
    assert isinstance(FINDING_CODES, frozenset)


def test_heading_findings_share_rule() -> None:
    codes = [
        "READINESS_PRD_HEADING_MISSING",
        "READINESS_PRD_HEADING_DUPLICATE",
        "READINESS_PRD_HEADING_ORDER",
    ]
    rules = [rule_by_code(code) for code in codes]
    assert all(r.rule == "prd-headings" for r in rules), (
        "heading-check findings should share rule 'prd-headings'"
    )
    assert all(r.predicate == "heading-exactly-once-in-order" for r in rules), (
        "heading-check findings should use heading predicate"
    )
    assert all(r.parameters["headings"] == REQUIRED_PRD_HEADINGS for r in rules), (
        "heading-check findings should carry the same headings parameter"
    )


def test_section_findings_share_rule() -> None:
    codes = ["READINESS_README_SECTION", "READINESS_README_SECTION_EMPTY"]
    rules = [rule_by_code(code) for code in codes]
    assert all(r.rule == "readme-sections" for r in rules), (
        "section-check findings should share rule 'readme-sections'"
    )
    assert all(r.predicate == "section-exactly-one-nonempty" for r in rules), (
        "section-check findings should use section predicate"
    )
