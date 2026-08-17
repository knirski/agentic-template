"""Full profile/custom-selection capability matrix over the compiled render.

Every profile and representative custom selection is rendered through the
shared pure boundary (``core_definition`` + ``capability_definitions`` from
``scripts/bootstrap/capability_fragments.py``) and pinned: unselected
capabilities emit no artifacts or workflow jobs, the release graph waits on
every selected managed capability check, the compiled workflow fixtures in
``scripts/fixtures/workflows`` stay byte-identical to the canonical render,
and the source's committed workflow files stay byte-identical to their
canonical compiled renders (the source ci is the portable baseline).  The
source never commits Nix workflow files, so generated projects can only
receive them through an explicit capability selection compiled by apply.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import pytest

from scripts.bootstrap.capability_fragments import CORE_CI_PATH, capability_definitions
from scripts.bootstrap.catalog import CATALOG, catalog_surface
from scripts.bootstrap.template_contract import SOURCE_WORKFLOW_SELECTIONS
from tests.fixtures import ALL_CAPABILITIES, render_for

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_FIXTURES = ROOT / "scripts/fixtures/workflows"
CATALOG_SURFACE_FIXTURE = ROOT / "scripts/fixtures/catalog-surface-v1.json"

# Every capability artifact path, keyed by capability id.
CAPABILITY_ARTIFACT_PATHS: dict[str, tuple[str, ...]] = {
    "semantic-release": (".releaserc", ".github/workflows/semantic-release.yml"),
    "nix": ("flake.nix", "flake.lock", ".github/workflows/nix.yml"),
    "cachix-publish": (".github/workflows/cachix-publish.yml",),
    "pr-agent-gemini": (
        ".pr_agent.toml",
        ".github/workflows/pr-agent.yml",
        ".github/workflows/pr-agent-commands.yml",
    ),
}

# Every capability contribution id, keyed by capability id.
CAPABILITY_CONTRIBUTIONS: dict[str, tuple[str, ...]] = {
    "semantic-release": ("release",),
    "nix": ("nix-check",),
    "cachix-publish": ("cachix-publish",),
    "pr-agent-gemini": (),
}


def _ci_job_names(rendered: dict[str, bytes]) -> list[str]:
    """The job keys of the compiled CI, in order."""
    text = rendered[CORE_CI_PATH].decode("utf-8")
    lines = text.splitlines()
    jobs_index = next(index for index, line in enumerate(lines) if line == "jobs:")
    jobs: list[str] = []
    for line in lines[jobs_index + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            jobs.append(line.strip().rstrip(":"))
    return jobs


# --- profile and selection matrix -------------------------------------------


def test_portable_profile_emits_core_only() -> None:
    rendered = render_for(())
    assert set(rendered) == {CORE_CI_PATH, "pyproject.toml"}
    jobs = _ci_job_names(rendered)
    assert jobs == ["project-validation", "delivery-contract"]
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    assert "release:" not in ci
    assert "nix-check" not in ci
    assert "cachix-publish" not in ci
    assert "semantic-release" not in ci
    assert b'requires-python = ">=3.14"' in rendered["pyproject.toml"]


def test_release_automated_profile_emits_the_release_graph() -> None:
    rendered = render_for(("semantic-release",))
    assert ".releaserc" in rendered
    assert ".github/workflows/semantic-release.yml" in rendered
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    assert 'needs: ["project-validation", "delivery-contract"]' in ci
    assert "github.ref_name == github.event.repository.default_branch" in ci
    assert "github.repository != 'knirski/agentic-template'" in ci
    for absent in (
        "flake.nix",
        "flake.lock",
        ".github/workflows/nix.yml",
        ".github/workflows/cachix-publish.yml",
        ".github/workflows/pr-agent.yml",
        ".pr_agent.toml",
    ):
        assert absent not in rendered
    assert "nix-check" not in ci
    assert ".releaserc" in rendered
    assert b"python-semantic-release>=9" in rendered["pyproject.toml"]


def test_nix_enabled_profile_emits_nix_artifacts_without_release() -> None:
    rendered = render_for(("nix",))
    for path in CAPABILITY_ARTIFACT_PATHS["nix"]:
        assert path in rendered
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    assert "  nix-check:" in ci
    assert "uses: ./.github/workflows/nix.yml" in ci
    assert "release:" not in ci
    assert "cachix-publish" not in ci
    assert ".releaserc" not in rendered
    flake = rendered["flake.nix"].decode("utf-8")
    assert 'description = "example";' in flake
    assert "tests/" not in flake
    # The bare-python nix lane runs only the stdlib-only readiness checker;
    # the full validator needs the declared runtime dependencies and runs
    # through uv in the project-validation CI.
    assert "scripts/check_project_readiness.py" in flake
    assert "scripts/validate_repository.py" not in flake


def test_integrated_profile_emits_everything_and_gates_release() -> None:
    rendered = render_for(ALL_CAPABILITIES)
    expected_paths = {CORE_CI_PATH, "pyproject.toml"}
    for paths in CAPABILITY_ARTIFACT_PATHS.values():
        expected_paths.update(paths)
    assert set(rendered) == expected_paths
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    jobs = _ci_job_names(rendered)
    assert jobs == [
        "project-validation",
        "delivery-contract",
        "nix-check",
        "cachix-publish",
        "release",
    ]
    # Release waits on the core jobs and every selected capability check.
    assert 'needs: ["project-validation", "delivery-contract", "nix-check"]' in ci
    # Cachix publishing is gated on the default-branch event and Nix success.
    assert "  cachix-publish:" in ci
    assert "needs: [nix-check]" in ci
    assert "github.ref_name == github.event.repository.default_branch" in ci
    # Nix never reaches the portable graph: the check job is a capability
    # contribution, and the release job needs it only when selected.
    assert "uses: ./.github/workflows/cachix-publish.yml" in ci


@pytest.mark.parametrize(
    ("selection", "expected_jobs"),
    [
        ((), ["project-validation", "delivery-contract"]),
        (("semantic-release",), ["project-validation", "delivery-contract", "release"]),
        (("nix",), ["project-validation", "delivery-contract", "nix-check"]),
        (
            ("nix", "cachix-publish"),
            ["project-validation", "delivery-contract", "nix-check", "cachix-publish"],
        ),
        (
            ("semantic-release", "nix"),
            ["project-validation", "delivery-contract", "nix-check", "release"],
        ),
        (
            ("semantic-release", "cachix-publish", "nix"),
            [
                "project-validation",
                "delivery-contract",
                "nix-check",
                "cachix-publish",
                "release",
            ],
        ),
        (("pr-agent-gemini",), ["project-validation", "delivery-contract"]),
        (
            ("semantic-release", "pr-agent-gemini"),
            ["project-validation", "delivery-contract", "release"],
        ),
    ],
)
def test_custom_selection_matrix(
    selection: tuple[str, ...], expected_jobs: list[str]
) -> None:
    rendered = render_for(selection)
    assert _ci_job_names(rendered) == expected_jobs


@pytest.mark.parametrize("capability_id", ALL_CAPABILITIES)
def test_unselected_capabilities_emit_no_artifacts_or_jobs(capability_id: str) -> None:
    dropped = {capability_id}
    if capability_id == "nix":
        # cachix-publish depends on nix and cannot be selected without it.
        dropped.add("cachix-publish")
    selection = tuple(
        capability for capability in ALL_CAPABILITIES if capability not in dropped
    )
    rendered = render_for(selection)
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    for path in CAPABILITY_ARTIFACT_PATHS[capability_id]:
        assert path not in rendered
    for contribution in CAPABILITY_CONTRIBUTIONS[capability_id]:
        assert f"  {contribution}:" not in ci
    # A selected capability that depends on the dropped one cannot render.
    if capability_id == "nix":
        assert "cachix-publish" not in ci
        assert ".github/workflows/cachix-publish.yml" not in rendered


# --- release graph gating ----------------------------------------------------


@pytest.mark.parametrize(
    ("selection", "expected_needs"),
    [
        (("semantic-release",), ["project-validation", "delivery-contract"]),
        (
            ("semantic-release", "nix"),
            ["project-validation", "delivery-contract", "nix-check"],
        ),
        (
            ("semantic-release", "cachix-publish", "nix"),
            ["project-validation", "delivery-contract", "nix-check"],
        ),
    ],
)
def test_release_needs_include_every_selected_capability_check(
    selection: tuple[str, ...], expected_needs: list[str]
) -> None:
    rendered = render_for(selection)
    ci = rendered[CORE_CI_PATH].decode("utf-8")
    assert f"needs: {json.dumps(expected_needs)}" in ci


def test_no_release_job_without_semantic_release() -> None:
    for selection in ((), ("nix",), ("pr-agent-gemini",), ("nix", "cachix-publish")):
        rendered = render_for(selection)
        assert "release:" not in rendered[CORE_CI_PATH].decode("utf-8")
        assert ".github/workflows/semantic-release.yml" not in rendered
        assert ".releaserc" not in rendered


def test_nix_is_absent_from_every_portable_render() -> None:
    for selection in ((), ("semantic-release",), ("pr-agent-gemini",)):
        rendered = render_for(selection)
        text = "\n".join(content.decode("utf-8") for content in rendered.values())
        assert "flake.nix" not in text
        assert "nix-check" not in text
        assert "cachix" not in text


# --- frozen fixtures ---------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "fixture_name"),
    [
        (".github/workflows/semantic-release.yml", "semantic-release.yml"),
        (".github/workflows/nix.yml", "nix.yml"),
        (".github/workflows/cachix-publish.yml", "cachix-publish.yml"),
        (".github/workflows/pr-agent.yml", "pr-agent-gemini.yml"),
    ],
)
def test_workflow_fixtures_match_the_compiled_render(
    path: str, fixture_name: str
) -> None:
    rendered = render_for(ALL_CAPABILITIES)
    fixture = WORKFLOW_FIXTURES / fixture_name
    assert rendered[path] == fixture.read_bytes(), f"{path} drifted from its fixture"


def test_frozen_workflow_fixtures_are_complete() -> None:
    assert sorted(path.name for path in WORKFLOW_FIXTURES.glob("*.yml")) == [
        "cachix-publish.yml",
        "nix.yml",
        "pr-agent-gemini.yml",
        "semantic-release.yml",
    ]


def test_source_workflows_match_the_compiled_render() -> None:
    for path, selection in SOURCE_WORKFLOW_SELECTIONS.items():
        compiled = render_for(selection)
        assert (ROOT / path).read_bytes() == compiled[path], (
            f"{path} drifted from the compiled source render; "
            "restore it from the compiled output"
        )


def test_source_never_commits_nix_capability_workflows() -> None:
    # Copier and snapshot apply copy every committed source workflow into
    # generated projects' pre-apply trees, so committing Nix workflow files
    # would leak them into adopters that never selected Nix.  Nix stays
    # optional: only an explicit capability selection compiles these
    # artifacts through apply.
    for path in (
        ".github/workflows/nix.yml",
        ".github/workflows/cachix-publish.yml",
    ):
        assert not (ROOT / path).exists(), f"{path} must not be committed"


def test_catalog_surface_matches_the_frozen_fixture() -> None:
    fixture = cast(
        dict[str, object],
        json.loads(CATALOG_SURFACE_FIXTURE.read_text(encoding="utf-8")),
    )
    assert fixture["schema_version"] == 1
    live = cast(dict[str, object], json.loads(json.dumps(catalog_surface())))
    assert live == fixture["capabilities"]


def test_catalog_and_render_surfaces_agree() -> None:
    """The declarative catalog and the fragment render definitions cannot drift."""
    definitions = capability_definitions()
    assert set(definitions) == set(CATALOG)
    for capability_id, definition in CATALOG.items():
        render_definition = definitions[capability_id]
        assert tuple(artifact.path for artifact in definition.artifacts) == tuple(
            artifact.path for artifact in render_definition.artifacts
        )
        assert tuple(
            (contribution.id, contribution.slot, contribution.order, contribution.kind)
            for contribution in definition.contributions
        ) == tuple(
            (
                contribution.id,
                contribution.slot,
                contribution.order,
                contribution.kind,
            )
            for contribution in render_definition.contributions
        )
        assert definition.runtime_dependencies == render_definition.runtime_dependencies
        assert definition.invocation == render_definition.invocation
        assert definition.supported_python == render_definition.supported_python


def test_compiled_workflows_pass_actionlint() -> None:
    actionlint = shutil.which("actionlint")
    if actionlint is None:
        pytest.skip("actionlint is required for the workflow lint check")
    with tempfile.TemporaryDirectory(prefix="agentic-template-actionlint.") as raw:
        directory = Path(raw)
        for selection in ((), ("semantic-release",), ALL_CAPABILITIES):
            rendered = render_for(selection)
            for path, content in rendered.items():
                if path.startswith(".github/workflows/"):
                    relative = directory / Path(path)
                    relative.parent.mkdir(parents=True, exist_ok=True)
                    _ = relative.write_bytes(content)
        for fixture in WORKFLOW_FIXTURES.glob("*.yml"):
            _ = shutil.copy2(fixture, directory / ".github/workflows" / fixture.name)
        result = subprocess.run(
            [
                actionlint,
                *(
                    str(path)
                    for path in sorted((directory / ".github/workflows").glob("*.yml"))
                ),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


# --- adopter uv follow-up ----------------------------------------------------

UV_LOCK_TIMEOUT_SECONDS = 180
UV_SYNC_TIMEOUT_SECONDS = 180
UV_RUN_TIMEOUT_SECONDS = 120


def test_adopter_fixture_installs_and_runs_capability_commands() -> None:
    """uv resolves the integrated pyproject and runs the declared command.

    The generated pyproject resolves through the adopter's ``uv lock``/``uv
    sync`` follow-up, the semantic-release capability command runs through its
    declared uv invocation, and the canonical validators remain directly
    runnable in the uv environment.  Bootstrap itself never installs packages:
    it renders the declarations only, and the lock here is created by the
    adopter's uv, not by bootstrap.
    """
    from tests.test_generated_dependencies import SOURCE_DEV_PACKAGES

    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the adopter fixture")
    with tempfile.TemporaryDirectory(prefix="agentic-template-adopter.") as raw:
        project = Path(raw)
        rendered = render_for(ALL_CAPABILITIES)
        _ = (project / "pyproject.toml").write_bytes(rendered["pyproject.toml"])
        _ = shutil.copytree(ROOT / "scripts", project / "scripts")
        locked = subprocess.run(
            [uv, "lock"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=UV_LOCK_TIMEOUT_SECONDS,
        )
        assert locked.returncode == 0, (
            "uv lock failed on the integrated generated pyproject: " + locked.stderr
        )
        synced = subprocess.run(
            [uv, "sync"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=UV_SYNC_TIMEOUT_SECONDS,
        )
        assert synced.returncode == 0, "uv sync failed: " + synced.stderr
        command = subprocess.run(
            [uv, "run", "semantic-release", "--help"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=UV_RUN_TIMEOUT_SECONDS,
        )
        assert command.returncode == 0, (
            "the declared capability invocation failed: " + command.stderr
        )
        validator = subprocess.run(
            [uv, "run", "python", "scripts/validate_template.py"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            timeout=UV_RUN_TIMEOUT_SECONDS,
        )
        # The validator runs in the uv environment (pydantic imports); the
        # fixture is an incomplete project, so only contract findings remain.
        assert validator.returncode == 1, validator.stderr
        assert "TEMPLATE_CONTRACT_ERROR" in validator.stderr
        assert "ImportError" not in validator.stderr
        lock = (project / "uv.lock").read_text(encoding="utf-8")
        assert "pydantic" in lock
        assert "pyyaml" in lock
        assert "python-semantic-release" in lock
        # pr-agent stays out of the generated runtime (see the catalog
        # declaration comments) and source dev packages never leak.
        assert "pr-agent" not in lock
        for package in SOURCE_DEV_PACKAGES:
            assert package not in lock
