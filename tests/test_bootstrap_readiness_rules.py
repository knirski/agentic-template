"""Tests for the frozen readiness-rule catalog."""

from __future__ import annotations

import unittest
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


class CatalogCompleteness(unittest.TestCase):
    """The catalog carries every readiness v1 rule from the frozen baseline."""

    def test_catalog_covers_all_old_checker_codes(self) -> None:
        for code in _OLD_CHECKER_CODES:
            self.assertIn(code, FINDING_CODES, f"missing catalog entry: {code}")

    def test_catalog_covers_slot_placeholder_codes(self) -> None:
        for code in _SLOT_PLACEHOLDER_CODES:
            self.assertIn(code, FINDING_CODES, f"missing catalog entry: {code}")

    def test_catalog_covers_all_shared_core_codes(self) -> None:
        for code in _ALL_SHARED_CORE_CODES:
            self.assertTrue(
                finding_code_is_known(code),
                f"shared-core code not in catalog: {code}",
            )

    def test_catalog_codes_match_frozen_v1_baseline(self) -> None:
        expected_codes = set(_ALL_SHARED_CORE_CODES)
        catalog_codes = {rule.code for rule in FROZEN_CATALOG_V1}
        self.assertSetEqual(catalog_codes, expected_codes)
        self.assertSetEqual(set(FINDING_CODES), catalog_codes)

    def test_all_rules_are_blocking(self) -> None:
        for rule in FROZEN_CATALOG_V1:
            self.assertEqual(rule.severity, "blocking")

    def test_all_rules_are_adopter_owned(self) -> None:
        for rule in FROZEN_CATALOG_V1:
            self.assertEqual(rule.owned_path_class, "adopter")

    def test_all_rules_are_path_subject_kind(self) -> None:
        for rule in FROZEN_CATALOG_V1:
            self.assertEqual(rule.subject_kind, "path")


class CatalogIdentityInvariants(unittest.TestCase):
    """Unique identity invariant: (code, subject_kind, rule) is unique."""

    def test_no_duplicate_identities(self) -> None:
        identities = [
            (rule.code, rule.subject_kind, rule.rule) for rule in FROZEN_CATALOG_V1
        ]
        self.assertEqual(len(set(identities)), len(identities))

    def test_no_duplicate_codes(self) -> None:
        codes = [rule.code for rule in FROZEN_CATALOG_V1]
        self.assertEqual(len(set(codes)), len(codes))

    def test_lookup_by_code_returns_correct_rule(self) -> None:
        rule = rule_by_code("READINESS_PRD_MARKER")
        self.assertEqual(rule.predicate, "text-absent")
        patterns = rule.parameters["patterns"]
        assert isinstance(patterns, tuple)
        self.assertIn("placeholder:prd", patterns[0])

    def test_rules_by_code_returns_full_mapping(self) -> None:
        mapping = rules_by_code()
        self.assertEqual(len(mapping), len(FROZEN_CATALOG_V1))


class SatisfierClassification(unittest.TestCase):
    """Satisfier classification covers all four kinds exhaustively."""

    def test_satisfier_compatibility_covers_all_members(self) -> None:
        for satisfier in (
            "initial-plan",
            "managed-render",
            "adopter-edit",
            "external-action",
        ):
            result = satisfier_compatibility(satisfier)
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_all_v1_rules_use_adopter_edit(self) -> None:
        for rule in FROZEN_CATALOG_V1:
            self.assertEqual(
                rule.satisfier,
                "adopter-edit",
                f"{rule.code} has unexpected satisfier: {rule.satisfier}",
            )


class PredicateKindCoverage(unittest.TestCase):
    """The predicate kind union covers all v1 predicates."""

    def test_all_predicate_kinds_used(self) -> None:
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
        self.assertEqual(used, expected)


class DerivedConstantsConsistency(unittest.TestCase):
    """Derived constants match their catalog entries."""

    def test_prd_marker_matches_catalog(self) -> None:
        rule = rule_by_code("READINESS_PRD_MARKER")
        self.assertEqual(
            PRD_MARKER,
            rule.parameters["patterns"][0],  # pyright: ignore[reportIndexIssue]
        )

    def test_readme_marker_matches_catalog(self) -> None:
        rule = rule_by_code("READINESS_README_MARKER")
        self.assertEqual(
            README_MARKER,
            rule.parameters["patterns"][0],  # pyright: ignore[reportIndexIssue]
        )

    def test_required_prd_headings_match_catalog(self) -> None:
        rule = rule_by_code("READINESS_PRD_HEADING_MISSING")
        self.assertEqual(
            REQUIRED_PRD_HEADINGS,
            rule.parameters["headings"],
        )

    def test_required_readme_sections_match_catalog(self) -> None:
        rule = rule_by_code("READINESS_README_SECTION")
        self.assertEqual(
            REQUIRED_README_SECTIONS,
            rule.parameters["sections"],
        )

    def test_readme_validation_command_matches_catalog(self) -> None:
        rule = rule_by_code("READINESS_README_COMMAND")
        self.assertEqual(
            README_VALIDATION_COMMAND,
            rule.parameters["required_text"],
        )


class SharedCoreFindingsMatchCatalog(unittest.TestCase):
    """Shared-core finding codes match the catalog identities."""

    def test_finding_matches_catalog_for_known_codes(self) -> None:
        for code in _ALL_SHARED_CORE_CODES:
            self.assertTrue(
                finding_matches_catalog(code),
                f"shared-core code not matched by catalog: {code}",
            )

    def test_finding_matches_catalog_rejects_unknown(self) -> None:
        self.assertFalse(finding_matches_catalog("UNKNOWN_CODE"))
        self.assertFalse(finding_matches_catalog("READINESS_FAKE"))

    def test_finding_code_is_known_for_all_codes(self) -> None:
        for code in FINDING_CODES:
            self.assertTrue(finding_code_is_known(code))

    def test_finding_code_is_known_rejects_unknown(self) -> None:
        self.assertFalse(finding_code_is_known("UNKNOWN_CODE"))

    def test_findings_from_shared_core_have_matching_catalog_entry(self) -> None:
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
            self.assertTrue(
                finding_matches_catalog(finding.code),
                f"Finding({finding.code}) not in catalog",
            )


class CompatibilityCorpus(unittest.TestCase):
    """The schema-v1 readiness surface is frozen by a checked-in corpus."""

    def test_corpus_fixture_exists(self) -> None:
        corpus_path = ROOT / "scripts" / "fixtures" / "readiness-rule-catalog-v1.json"
        self.assertTrue(corpus_path.is_file())

    def test_template_validator_accepts_the_live_corpus(self) -> None:
        from scripts.validate_template import validate_readiness_rule_catalog

        self.assertEqual(validate_readiness_rule_catalog(ROOT), ())

    def test_new_blocking_adopter_rule_is_rejected(self) -> None:
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
        self.assertIn("added blocking adopter readiness rules", failures[0])

    def test_stable_identity_change_is_rejected(self) -> None:
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
        self.assertIn("removed stable readiness rules", failures[0])
        self.assertIn("added blocking adopter readiness rules", failures[0])


class CatalogTypeSafety(unittest.TestCase):
    """The catalog definition type-checks and the dataclass is frozen."""

    def test_frozen_catalog_is_tuple(self) -> None:
        self.assertIsInstance(FROZEN_CATALOG_V1, tuple)

    def test_all_entries_are_readiness_rule_definition(self) -> None:
        for rule in FROZEN_CATALOG_V1:
            self.assertIsInstance(rule, ReadinessRuleDefinition)

    def test_catalog_is_immutable(self) -> None:
        self.assertIsInstance(FROZEN_CATALOG_V1, tuple)
        self.assertIsInstance(FINDING_CODES, frozenset)


class HeadingContractPredicates(unittest.TestCase):
    """The heading-check rules share a predicate identifier."""

    def test_heading_findings_share_rule(self) -> None:
        codes = [
            "READINESS_PRD_HEADING_MISSING",
            "READINESS_PRD_HEADING_DUPLICATE",
            "READINESS_PRD_HEADING_ORDER",
        ]
        rules = [rule_by_code(code) for code in codes]
        self.assertTrue(
            all(r.rule == "prd-headings" for r in rules),
            "heading-check findings should share rule 'prd-headings'",
        )
        self.assertTrue(
            all(r.predicate == "heading-exactly-once-in-order" for r in rules),
            "heading-check findings should use heading predicate",
        )
        self.assertTrue(
            all(r.parameters["headings"] == REQUIRED_PRD_HEADINGS for r in rules),
            "heading-check findings should carry the same headings parameter",
        )


class SectionContractPredicates(unittest.TestCase):
    """The section-check rules share a predicate identifier."""

    def test_section_findings_share_rule(self) -> None:
        codes = ["READINESS_README_SECTION", "READINESS_README_SECTION_EMPTY"]
        rules = [rule_by_code(code) for code in codes]
        self.assertTrue(
            all(r.rule == "readme-sections" for r in rules),
            "section-check findings should share rule 'readme-sections'",
        )
        self.assertTrue(
            all(r.predicate == "section-exactly-one-nonempty" for r in rules),
            "section-check findings should use section predicate",
        )


if __name__ == "__main__":
    _ = unittest.main()
