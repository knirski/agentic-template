"""Contract tests for durable adopter documentation."""

from __future__ import annotations

from pathlib import Path

from scripts.bootstrap.blobs import VerifiedBlobStore
from scripts.bootstrap.capability_fragments import (
    capability_definitions,
    core_definition,
)
from scripts.bootstrap.contributions import render_generation
from scripts.bootstrap.identity import sha256_hex
from scripts.bootstrap.intents import GenerationPath
from scripts.bootstrap.paths import RepoPath
from scripts.bootstrap.render import (
    LicensingInfo,
    MaintenanceInfo,
    ProfileInfo,
    ProjectInfo,
)
from scripts.bootstrap.result import Err, Ok

ROOT = Path(__file__).resolve().parent.parent
DOCUMENT_PATHS = (
    "docs/delivery-workflow.md",
    "docs/template-updates.md",
    "docs/capabilities.md",
    "docs/github-setup.md",
)


def _rendered(
    *,
    effective: tuple[str, ...] = (),
    additions: tuple[str, ...] = (),
    settings: dict[str, dict[str, str | bool]] | None = None,
    profile_id: str = "custom",
    frozen: tuple[str, ...] | None = None,
    maintenance: MaintenanceInfo | None = None,
) -> dict[str, bytes]:
    match render_generation(
        generation_path=GenerationPath.COPIER,
        core=core_definition(),
        definitions=capability_definitions(),
        effective=effective,
        additions=additions,
        settings=settings or {},
        project=ProjectInfo(name="example", default_branch="main"),
        licensing=LicensingInfo(mode="retain-apache-2.0", content_sha256=None),
        profile=ProfileInfo(
            id=profile_id, frozen=effective if frozen is None else frozen
        ),
        maintenance=maintenance or MaintenanceInfo(status="clean", retained_paths=()),
        slots={},
        blobs=VerifiedBlobStore.empty(),
    ):
        case Ok(files):
            return {file.path.value: file.content for file in files}
        case Err(error):
            raise AssertionError(f"unexpected render failure: {error}")


def test_rendered_output_contains_all_durable_adopter_documents() -> None:
    rendered = _rendered()

    assert set(DOCUMENT_PATHS) <= set(rendered)
    for path in DOCUMENT_PATHS:
        text = rendered[path].decode("utf-8")
        assert "managed by the Rygor" in text
        assert "README.md" in text
        assert "CONTRIBUTING.md" in text


def test_capability_document_records_selection_additions_and_settings() -> None:
    rendered = _rendered(
        effective=("nix", "cachix-publish"),
        additions=("cachix-publish",),
        settings={"cachix-publish": {"cache_name": "example-cache"}},
        frozen=("nix",),
    )

    capabilities = rendered["docs/capabilities.md"].decode("utf-8")
    assert "- Profile: `custom`" in capabilities
    assert "- Frozen profile selection: `nix`" in capabilities
    assert "- Explicit additions: `cachix-publish`" in capabilities
    assert "- Effective dependency closure: `nix, cachix-publish`" in capabilities
    assert "example-cache" in capabilities
    assert "cachix-publish" in capabilities


def test_github_setup_contains_only_selected_capability_secrets() -> None:
    portable = _rendered()["docs/github-setup.md"].decode("utf-8")
    selected = _rendered(
        effective=("nix", "cachix-publish", "pr-agent-gemini"),
        settings={"cachix-publish": {"cache_name": "example-cache"}},
    )["docs/github-setup.md"].decode("utf-8")

    assert "GEMINI_API_KEY" not in portable
    assert "CACHIX_AUTH_TOKEN" not in portable
    assert "GEMINI_API_KEY" in selected
    assert "CACHIX_AUTH_TOKEN" in selected


def test_template_updates_records_maintenance_ownership() -> None:
    rendered = _rendered(
        maintenance=MaintenanceInfo(
            status="retained",
            retained_paths=(RepoPath("docs/specs"), RepoPath("tests")),
        )
    )

    updates = rendered["docs/template-updates.md"].decode("utf-8")
    assert "- Maintenance status: `retained`" in updates
    assert "Retained maintenance paths:" in updates
    assert "docs/specs\ntests" in updates


def test_documentation_has_no_legacy_hook_contract() -> None:
    rendered = _rendered(effective=("semantic-release",))
    legacy_hook = "scripts/" + "validate_project.py"

    for path in DOCUMENT_PATHS:
        text = rendered[path].decode("utf-8")
        assert "scripts/validate-project" in text
        assert legacy_hook not in text
        assert "adoption" not in text.lower()
        assert "migration" not in text.lower()


def test_source_documentation_carries_the_same_operational_contract() -> None:
    legacy_hook = "scripts/" + "validate_project.py"
    for relative in DOCUMENT_PATHS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "managed by the Rygor" in text
        assert "README.md" in text
        assert "CONTRIBUTING.md" in text
        assert "scripts/validate-project" in text
        assert legacy_hook not in text


def test_documentation_fragments_are_reproducible() -> None:
    first = _rendered(effective=("semantic-release",))
    second = _rendered(effective=("semantic-release",))

    assert first == second
    assert sha256_hex(first["docs/capabilities.md"]) == sha256_hex(
        second["docs/capabilities.md"]
    )


def test_cross_document_operational_contract_is_complete() -> None:
    rendered = _rendered(
        effective=("nix", "cachix-publish"),
        settings={"cachix-publish": {"cache_name": "example-cache"}},
    )
    delivery = rendered["docs/delivery-workflow.md"].decode("utf-8")
    updates = rendered["docs/template-updates.md"].decode("utf-8")
    capabilities = rendered["docs/capabilities.md"].decode("utf-8")
    github = rendered["docs/github-setup.md"].decode("utf-8")

    assert "recover" in delivery
    assert "receipt" in delivery
    assert "Copier" in updates
    assert "cannot use" in updates
    assert "Effective dependency closure" in capabilities
    assert "Available" in github
    assert "Unavailable in this run" in github
    assert "Dependabot" in github
