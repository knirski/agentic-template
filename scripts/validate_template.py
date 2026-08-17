#!/usr/bin/env python3
"""Validate the template-owned file and skill contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from scripts.bootstrap import template_contract  # noqa: E402
from scripts.bootstrap.blobs import VerifiedBlobStore  # noqa: E402
from scripts.bootstrap.canonical_json import decode_json  # noqa: E402
from scripts.bootstrap.capability_fragments import (  # noqa: E402
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.catalog import catalog_surface  # noqa: E402
from scripts.bootstrap.contributions import render_generation  # noqa: E402
from scripts.bootstrap.entrypoint import reject_arguments  # noqa: E402
from scripts.bootstrap.intents import GenerationPath  # noqa: E402
from scripts.bootstrap.render import (  # noqa: E402
    LicensingInfo,
    MaintenanceInfo,
    ProfileInfo,
    ProjectInfo,
)
from scripts.bootstrap.result import Err, Ok  # noqa: E402
from scripts.bootstrap.template_contract import SOURCE_WORKFLOW_SELECTIONS  # noqa: E402

CATALOG_SURFACE_FIXTURE = "scripts/fixtures/catalog-surface-v1.json"
CATALOG_SURFACE_SCHEMA_VERSION = 1

# Present only in the template source; generated projects remove it, so the
# drift check below never mistakes an adopter's compiled CI for source CI.
SOURCE_FIXTURE_MARKER = ".agentic-template/maintenance-artifacts.json"


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


def validate_source_workflows(root: Path) -> tuple[str, ...]:
    """The source's committed workflows are compiled managed output.

    Each committed ``.github/workflows`` file is compared byte-for-byte against
    its canonical compiled render (the source ci is the portable baseline so
    unselected capabilities never reach adopters' active CI).  Generated
    projects are skipped: they remove the source marker and keep their own
    profile's CI.
    """
    if not (root / SOURCE_FIXTURE_MARKER).is_file():
        return ()
    store = VerifiedBlobStore.empty()
    core = core_definition()
    definitions = capability_definitions()
    project = ProjectInfo(name="example", default_branch="main")
    licensing = LicensingInfo(mode="retain-apache-2.0", content_sha256=None)
    maintenance = MaintenanceInfo(status="clean", retained_paths=())
    failures: list[str] = []
    for relative, selection in SOURCE_WORKFLOW_SELECTIONS.items():
        committed = root / relative
        if not committed.is_file():
            failures.append(f"source workflow {relative} is missing")
            continue
        match render_generation(
            generation_path=GenerationPath.GITHUB,
            core=core,
            definitions=definitions,
            effective=selection,
            settings={},
            project=project,
            licensing=licensing,
            profile=ProfileInfo(id="custom", frozen=selection),
            maintenance=maintenance,
            slots={},
            blobs=store,
        ):
            case Err(error):
                failures.append(
                    f"source workflow {relative} failed to render: "
                    + f"{error.kind.value}:{error.subject}"
                )
                continue
            case Ok(managed):
                compiled = {file.path.value: file.content for file in managed}
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
        *validate_source_workflows(root),
    )


def main(argv: list[str]) -> int:
    if reject_arguments(argv, "scripts/validate_template.py") is not None:
        return 2
    skill_paths = sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    skill_texts = tuple(
        (path, path.read_text(encoding="utf-8")) for path in skill_paths
    )
    failures = validate_contract(ROOT, skill_texts)
    for failure in failures:
        print(
            f"TEMPLATE_CONTRACT_ERROR: {failure}; next: restore the template contract",
            file=sys.stderr,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
