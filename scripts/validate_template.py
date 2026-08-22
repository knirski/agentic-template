#!/usr/bin/env python3
"""Validate the template-owned file and skill contract."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap import template_contract  # noqa: E402
from scripts.bootstrap.canonical_json import decode_json  # noqa: E402
from scripts.bootstrap.catalog import catalog_surface  # noqa: E402
from scripts.bootstrap.contributions import render_source_fixture  # noqa: E402
from scripts.bootstrap.readiness import Finding, Repository  # noqa: E402
from scripts.bootstrap.readiness_rules import readiness_rule_surface  # noqa: E402
from scripts.bootstrap.result import Err, Ok  # noqa: E402
from scripts.bootstrap.template_contract import SOURCE_WORKFLOW_SELECTIONS  # noqa: E402
from scripts.bootstrap.validation_presentation import (  # noqa: E402
    parse_options,
    render_findings,
    render_usage_error,
    requested_json,
)

CATALOG_SURFACE_FIXTURE = "scripts/fixtures/catalog-surface-v1.json"
CATALOG_SURFACE_SCHEMA_VERSION = 1
READINESS_RULE_CORPUS = "scripts/fixtures/readiness-rule-catalog-v1.json"
READINESS_RULE_SCHEMA_VERSION = 1

# Present only in the template source; generated projects remove it, so the
# drift check below never mistakes an adopter's compiled CI for source CI.
# It is not reliable on its own: the documented ``apply
# --leave-maintenance-artifacts`` repair retains this inventory in adopters.
SOURCE_FIXTURE_MARKER = ".agentic-template/maintenance-artifacts.json"
# The managed manifest apply always writes and the source never commits.  Its
# presence marks a managed adopter (including the repair path above), whose
# per-profile compiled ci.yml legitimately differs from the source baseline.
MANAGED_ADOPTER_MARKER = ".agentic-template/project.json"


def validate_catalog_surface(root: Path) -> tuple[str, ...]:
    """Compare the live catalog surface against the frozen v1 fixture.

    The fixture records the stable-ID compatibility contract: dependency ids,
    setting shapes, owned output paths, slot contributions, document
    fragments, and runtime dependency metadata.  A drift is a template-contract
    failure because it silently changes what generated projects receive.
    """
    fixture_path = root / CATALOG_SURFACE_FIXTURE
    try:
        fixture = decode_json(fixture_path.read_bytes())
    except OSError, ValueError:
        return ("catalog surface fixture is missing or invalid",)
    if not isinstance(fixture, dict):
        return ("catalog surface fixture is not a JSON object",)
    fixture_capabilities = fixture.get("capabilities")
    if not isinstance(fixture_capabilities, dict):
        return ("catalog surface fixture carries no capabilities object",)
    live_capabilities = catalog_surface()
    live = {
        "schema_version": CATALOG_SURFACE_SCHEMA_VERSION,
        "capabilities": live_capabilities,
    }
    if live == fixture:
        return ()
    removed = sorted(
        capability_id
        for capability_id in fixture_capabilities
        if capability_id not in live_capabilities
    )
    added = sorted(
        capability_id
        for capability_id in live_capabilities
        if capability_id not in fixture_capabilities
    )
    changed = sorted(
        capability_id
        for capability_id in fixture_capabilities
        if capability_id in live_capabilities
        and fixture_capabilities[capability_id] != live_capabilities[capability_id]
    )
    details: list[str] = []
    if removed:
        details.append(f"removed: {', '.join(removed)}")
    if added:
        details.append(f"added: {', '.join(added)}")
    if changed:
        details.append(f"changed: {', '.join(changed)}")
    return (
        "catalog surface drifted from the frozen v1 fixture ("
        + "; ".join(details)
        + "); next: restore the frozen catalog surface",
    )


def validate_readiness_rule_catalog(root: Path) -> tuple[str, ...]:
    """Reject v1 readiness changes that add adopter obligations or rebind IDs."""

    fixture_path = root / READINESS_RULE_CORPUS
    try:
        fixture = decode_json(fixture_path.read_bytes())
    except OSError, ValueError:
        return ("readiness-rule compatibility corpus is missing or invalid",)
    if not isinstance(fixture, dict):
        return ("readiness-rule compatibility corpus is not a JSON object",)
    if fixture.get("schema_version") != READINESS_RULE_SCHEMA_VERSION:
        return ("readiness-rule compatibility corpus has an unsupported schema",)
    raw_rules = fixture.get("rules")
    if not isinstance(raw_rules, list) or not all(
        isinstance(rule, dict) for rule in raw_rules
    ):
        return ("readiness-rule compatibility corpus carries no rules",)
    baseline_rules = cast(list[dict[str, object]], raw_rules)
    live_rules = list(readiness_rule_surface())

    def identity(rule: dict[str, object]) -> tuple[str, str, str]:
        return (
            str(rule.get("code")),
            str(rule.get("subject_kind")),
            str(rule.get("rule")),
        )

    baseline_by_identity = {identity(rule): rule for rule in baseline_rules}
    live_by_identity = {identity(rule): rule for rule in live_rules}
    removed = sorted(set(baseline_by_identity) - set(live_by_identity))
    added = sorted(set(live_by_identity) - set(baseline_by_identity))
    changed = sorted(
        key
        for key in set(baseline_by_identity) & set(live_by_identity)
        if baseline_by_identity[key] != live_by_identity[key]
    )
    failures: list[str] = []
    if removed:
        failures.append(f"removed stable readiness rules: {removed}")
    if changed:
        failures.append(f"changed stable readiness rules: {changed}")
    adopter_obligations = [
        key
        for key in added
        if live_by_identity[key].get("severity") == "blocking"
        and live_by_identity[key].get("owned_path_class") == "adopter"
    ]
    if adopter_obligations:
        failures.append(
            "added blocking adopter readiness rules: " + str(adopter_obligations)
        )
    return tuple(
        [
            "readiness-rule compatibility corpus drifted ("
            + "; ".join(failures)
            + "); next: restore the frozen readiness-rule catalog",
        ]
        if failures
        else []
    )


def validate_source_workflows(root: Path) -> tuple[str, ...]:
    """The source's committed workflows are compiled managed output.

    Each committed ``.github/workflows`` file is compared byte-for-byte against
    its canonical compiled render (the source ci is the portable baseline so
    unselected capabilities never reach adopters' active CI).  Managed adopter
    projects are skipped -- their per-profile compiled CI is meant to differ
    from the source baseline -- detected by the managed manifest, which also
    covers the ``--leave-maintenance-artifacts`` repair path that retains the
    source marker.
    """
    if not (root / SOURCE_FIXTURE_MARKER).is_file():
        return ()
    if (root / MANAGED_ADOPTER_MARKER).is_file():
        return ()
    failures: list[str] = []
    for relative, selection in SOURCE_WORKFLOW_SELECTIONS.items():
        committed = root / relative
        if not committed.is_file():
            failures.append(f"source workflow {relative} is missing")
            continue
        match render_source_fixture(selection):
            case Err(error):
                failures.append(
                    f"source workflow {relative} failed to render: "
                    + f"{error.kind.value}:{error.subject}"
                )
                continue
            case Ok(compiled):
                expected = compiled.get(relative)
        if expected is None:
            failures.append(
                f"source workflow {relative} is not produced by its compiled render"
            )
            continue
        if committed.read_bytes() != expected:
            failures.append(
                f"source workflow {relative} drifted from the compiled render; "
                + "next: restore it from the compiled output"
            )
    return tuple(failures)


def validate_contract(
    root: Path, skill_texts: tuple[tuple[Path, str], ...]
) -> tuple[str, ...]:
    """Evaluate an observed template through the shared pure policy."""
    present_files = tuple(
        relative
        for relative in template_contract.REQUIRED_FILES
        if (root / relative).is_file()
    )
    observed_skills = tuple(
        (path.relative_to(root).as_posix(), text) for path, text in skill_texts
    )
    failures = template_contract.required_contract_failures(
        present_files, observed_skills
    )
    return (
        *failures,
        *validate_catalog_surface(root),
        *validate_readiness_rule_catalog(root),
        *validate_source_workflows(root),
    )


def main(argv: list[str]) -> int:
    options = parse_options(argv)
    if options is None:
        return render_usage_error(
            "validate_template",
            (
                "TEMPLATE_USAGE_ERROR: scripts/validate_template.py: invalid presentation options; "
                "next: use --format text|json --color auto|always|never --explain --quiet"
            ),
            json_output=requested_json(argv),
        )
    try:
        skill_paths = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
        skill_texts = tuple(
            (path, path.read_text(encoding="utf-8")) for path in skill_paths
        )
        failures = validate_contract(ROOT, skill_texts)
    except Exception as exc:  # defensive boundary for a broken source checkout
        return render_findings(
            command="validate_template",
            findings=(),
            exit_code=2,
            options=options,
            diagnostic=(
                "TEMPLATE_INTERNAL_ERROR: repository: "
                + str(exc)
                + "; next: restore the template contract"
            ),
        )
    findings = tuple(
        Finding(
            code="TEMPLATE_CONTRACT_ERROR",
            subject_at=Repository(),
            subject="repository",
            rule="template-owned contract must remain valid",
            severity="blocking",
            message=failure,
            next_action="restore the template contract",
        )
        for failure in failures
    )
    return render_findings(
        command="validate_template",
        findings=findings,
        exit_code=1 if failures else 0,
        options=options,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
