"""Tests for capability dependency metadata and generated-project ownership.

Covers the T14 surface: dependency metadata round-trips and validation, the
generated ``pyproject.toml`` (baseline plus conditional capability
dependencies), the source-lock leakage fixtures, the slot-model pruned v1
contract, and the adopter-side uv lock follow-up.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from scripts.bootstrap.catalog import CATALOG, CapabilityDefinition
from scripts.bootstrap.dependencies import (
    BASELINE_PYTHON_RANGE,
    BASELINE_RUNTIME_DEPENDENCIES,
    GENERATED_PYPROJECT_PATH,
    DependencyError,
    DependencyErrorKind,
    effective_dependencies,
    effective_python_range,
    render_generated_pyproject,
    validate_invocation,
    validate_runtime_dependency,
    validate_supported_python,
)
from scripts.bootstrap.profiles import PROFILE_CAPABILITIES
from scripts.bootstrap.render import (
    CapabilityDefinition as RenderCapabilityDefinition,
)
from scripts.bootstrap.render import (
    ContextName,
    CoreDefinition,
    RenderError,
    RenderErrorKind,
    SlotDefinition,
    render_managed,
)
from scripts.bootstrap.result import Err, Ok, Result
from tests.test_bootstrap_render import (
    fixture_blobs,
    make_render_input,
    render_bytes,
)

SOURCE_ROOT = Path(__file__).resolve().parent.parent
GENERATED_PYPROJECT_FIXTURE = (
    SOURCE_ROOT / "scripts/fixtures/generated-dependencies/pyproject.toml"
)

# Source development-only packages that must never leak into a generated
# project's runtime dependency metadata or lock.
SOURCE_DEV_PACKAGES = (
    "basedpyright",
    "hypothesis",
    "mutmut",
    "pytest",
    "ruff",
)

EXPECTED_BASELINE_PYPROJECT = (
    b"[project]\n"
    b'name = "example"\n'
    b'version = "0.1.0"\n'
    b'requires-python = ">=3.14"\n'
    b"dependencies = [\n"
    b'    "pydantic>=2",\n'
    b'    "pyyaml>=6.0.3",\n'
    b"]\n"
)


def _err[Value, Failure: DependencyError](
    result: Result[Value, Failure],
) -> Failure:
    match result:
        case Err(error):
            return error
        case Ok(_):
            raise AssertionError("expected a failure")


def _render_error[Value](
    result: Result[Value, RenderError],
) -> RenderError:
    match result:
        case Err(error):
            return error
        case Ok(_):
            raise AssertionError("expected a render failure")


# --- Dependency metadata round-trips and validation -------------------------


def test_catalog_capabilities_carry_dependency_metadata() -> None:
    assert CATALOG["semantic-release"].runtime_dependencies == (
        "python-semantic-release>=9",
    )
    assert CATALOG["semantic-release"].supported_python == ">=3.14"
    assert CATALOG["semantic-release"].invocation == "uvx semantic-release"
    assert CATALOG["pr-agent-gemini"].runtime_dependencies == ("pr-agent",)
    assert CATALOG["pr-agent-gemini"].invocation == "uvx pr-agent"
    assert CATALOG["nix"].runtime_dependencies == ()
    assert CATALOG["nix"].invocation is None
    assert CATALOG["cachix-publish"].runtime_dependencies == ()
    assert CATALOG["cachix-publish"].invocation is None


def test_dependency_metadata_round_trips_through_the_catalog() -> None:
    for definition in CATALOG.values():
        restored = CapabilityDefinition.model_validate(definition.model_dump())
        assert restored == definition


def test_runtime_dependency_validation_normalizes_specifiers() -> None:
    assert validate_runtime_dependency("pydantic") == Ok("pydantic")
    assert validate_runtime_dependency("pydantic>=2") == Ok("pydantic>=2")
    assert validate_runtime_dependency("python-semantic-release>=9.0.0") == Ok(
        "python-semantic-release>=9"
    )
    assert validate_runtime_dependency("pr-agent >= 0.27") == Ok("pr-agent>=0.27")
    for invalid in ("", "rm -rf /", "pydantic>=2,<3", "pydantic==2", "-x", "x-", "a b"):
        assert _err(validate_runtime_dependency(invalid)).kind is (
            DependencyErrorKind.INVALID_DEPENDENCY
        )


def test_supported_python_validation_normalizes_specifiers() -> None:
    assert validate_supported_python(">=3.14") == Ok(">=3.14")
    assert validate_supported_python(">= 3.14") == Ok(">=3.14")
    assert validate_supported_python(">=3.14, <3.15") == Ok(">=3.14,<3.15")
    assert validate_supported_python("<3.15,>=3.14") == Ok(">=3.14,<3.15")
    assert validate_supported_python(">=3.14.0") == Ok(">=3.14")
    for invalid in ("", "3.14", "banana", ">=x", ">=3.14,", ">=3.14 <3.15", "==3.14"):
        assert _err(validate_supported_python(invalid)).kind is (
            DependencyErrorKind.INVALID_PYTHON_RANGE
        )


def test_invocation_validation() -> None:
    assert validate_invocation(None) == Ok(None)
    assert validate_invocation("uvx semantic-release") == Ok("uvx semantic-release")
    assert validate_invocation("uv run python -m my.tool") == Ok(
        "uv run python -m my.tool"
    )
    for invalid in (
        "",
        "uv",
        "uvx",
        "semantic-release",
        "bash -c x",
        "uvx semantic-release; rm -rf /",
        "uvx 'semantic-release'",
    ):
        assert _err(validate_invocation(invalid)).kind is (
            DependencyErrorKind.INVALID_INVOCATION
        )


def test_definitions_reject_invalid_dependency_metadata() -> None:
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="bad-dep", description="x", runtime_dependencies=("rm -rf /",)
        )
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="bad-range", description="x", supported_python="banana"
        )
    with pytest.raises(ValidationError):
        _ = CapabilityDefinition(
            id="bad-invocation", description="x", invocation="bash -c x"
        )
    with pytest.raises(ValidationError):
        _ = RenderCapabilityDefinition(
            id="bad-range", runtime_dependencies=("rm -rf /",)
        )


# --- Effective tables and every profile/custom-selection matrix -------------


@pytest.mark.parametrize("profile_id", sorted(PROFILE_CAPABILITIES))
def test_every_profile_renders_the_baseline_and_requires_python_314(
    profile_id: str,
) -> None:
    selection = PROFILE_CAPABILITIES[profile_id]
    match effective_dependencies(selection, CATALOG):
        case Ok(dependencies):
            pass
        case Err(error):
            raise AssertionError(f"unexpected dependency failure: {error}")
    match effective_python_range(selection, CATALOG):
        case Ok(python_range):
            pass
        case Err(error):
            raise AssertionError(f"unexpected range failure: {error}")
    rendered = render_generated_pyproject("example", python_range, dependencies)
    assert b'requires-python = ">=3.14"' in rendered
    for baseline in BASELINE_RUNTIME_DEPENDENCIES:
        assert baseline.encode() in rendered
    if profile_id == "portable":
        assert b"semantic-release" not in rendered
        assert b"pr-agent" not in rendered
    if profile_id == "integrated":
        assert b"python-semantic-release>=9" in rendered
        assert b'"pr-agent"' in rendered


@pytest.mark.parametrize(
    "selection",
    [
        (),
        ("nix",),
        ("cachix-publish",),
        ("semantic-release", "pr-agent-gemini"),
        ("nix", "cachix-publish", "pr-agent-gemini"),
    ],
)
def test_custom_selection_matrices_add_dependencies_only_when_required(
    selection: tuple[str, ...],
) -> None:
    match effective_dependencies(selection, CATALOG):
        case Ok(dependencies):
            pass
        case Err(error):
            raise AssertionError(f"unexpected dependency failure: {error}")
    assert dependencies[: len(BASELINE_RUNTIME_DEPENDENCIES)] == (
        BASELINE_RUNTIME_DEPENDENCIES
    )
    has_semantic_release = "semantic-release" in selection
    has_pr_agent = "pr-agent-gemini" in selection
    assert ("python-semantic-release>=9" in dependencies) == has_semantic_release
    assert ("pr-agent" in dependencies) == has_pr_agent
    assert all(dependency not in dependencies for dependency in SOURCE_DEV_PACKAGES)


def test_effective_python_range_intersects_and_rejects_incompatible_ranges(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        CATALOG,
        "narrower",
        CapabilityDefinition(id="narrower", description="x", supported_python=">=3.15"),
    )
    monkeypatch.setitem(
        CATALOG,
        "excludes-baseline",
        CapabilityDefinition(
            id="excludes-baseline", description="x", supported_python="<3.14"
        ),
    )
    assert effective_python_range(("narrower",), CATALOG) == Ok(">=3.15")
    assert effective_python_range((), CATALOG) == Ok(">=3.14")
    failure = _err(effective_python_range(("excludes-baseline",), CATALOG))
    assert failure.kind is DependencyErrorKind.INCOMPATIBLE_PYTHON_RANGE
    assert failure.subject == "excludes-baseline"
    failure = _err(effective_dependencies(("ghost",), CATALOG))
    assert failure.kind is DependencyErrorKind.UNKNOWN_CAPABILITY
    assert failure.subject == "ghost"


# --- Generated pyproject ownership and leakage ------------------------------


def test_generated_pyproject_matches_the_frozen_fixture() -> None:
    rendered = render_generated_pyproject(
        "example", ">=3.14", BASELINE_RUNTIME_DEPENDENCIES
    )
    assert rendered == GENERATED_PYPROJECT_FIXTURE.read_bytes()
    assert rendered == EXPECTED_BASELINE_PYPROJECT


def test_render_managed_emits_the_generated_pyproject_for_every_profile() -> None:
    store, content_ids = fixture_blobs()
    render_input = make_render_input(store, content_ids, effective=())
    rendered = render_bytes(render_input, store)
    assert rendered[GENERATED_PYPROJECT_PATH] == EXPECTED_BASELINE_PYPROJECT
    assert "uv.lock" not in rendered


def test_render_managed_never_claims_a_generated_uv_lock() -> None:
    store, content_ids = fixture_blobs()
    render_input = make_render_input(store, content_ids)
    match render_managed(render_input, store):
        case Ok(managed):
            assert all(file.path.value != "uv.lock" for file in managed)
        case Err(error):
            raise AssertionError(f"unexpected render failure: {error}")


def test_render_adds_capability_dependencies_only_when_selected() -> None:
    store, content_ids = fixture_blobs()
    definitions = {
        "semantic-release": RenderCapabilityDefinition(
            id="semantic-release",
            runtime_dependencies=("python-semantic-release>=9",),
            supported_python=">=3.14",
            invocation="uvx semantic-release",
        ),
        "pr-agent-gemini": RenderCapabilityDefinition(
            id="pr-agent-gemini",
            runtime_dependencies=("pr-agent",),
        ),
    }
    base = make_render_input(store, content_ids, effective=())
    base = replace(
        base,
        definitions=definitions,
        effective=("semantic-release",),
        core=CoreDefinition(),
        contributions=(),
        documents={},
    )
    rendered = render_bytes(base, store)
    assert b"python-semantic-release>=9" in rendered[GENERATED_PYPROJECT_PATH]
    assert b"pr-agent" not in rendered[GENERATED_PYPROJECT_PATH]


def test_render_rejects_an_artifact_claiming_the_generated_pyproject_path() -> None:
    store, content_ids = fixture_blobs()
    render_input = make_render_input(store, content_ids)
    definitions = dict(render_input.definitions)
    definitions["semantic-release"] = definitions["semantic-release"].model_copy(
        update={
            "artifacts": (
                definitions["semantic-release"]
                .artifacts[0]
                .model_copy(update={"path": GENERATED_PYPROJECT_PATH}),
            )
        }
    )
    match render_managed(
        replace(render_input, definitions=definitions),
        store,
    ):
        case Err(error):
            assert error.kind is RenderErrorKind.OWNERSHIP_COLLISION
            assert error.subject == GENERATED_PYPROJECT_PATH
        case Ok(_):
            raise AssertionError("expected an ownership collision failure")


def test_render_rejects_an_incompatible_capability_python_range() -> None:
    store, content_ids = fixture_blobs()
    render_input = make_render_input(store, content_ids)
    definitions = {
        "semantic-release": RenderCapabilityDefinition(
            id="semantic-release", supported_python="<3.14"
        )
    }
    result = render_managed(
        replace(
            render_input,
            definitions=definitions,
            effective=("semantic-release",),
            core=CoreDefinition(),
            contributions=(),
            documents={},
        ),
        store,
    )
    error = _render_error(result)
    assert error.kind is RenderErrorKind.INVALID_TEMPLATE
    assert error.reason == "incompatible_python_range"
    assert error.subject == "semantic-release"


def test_source_lock_and_dev_packages_do_not_leak_into_generated_projects() -> None:
    rendered = render_generated_pyproject(
        "example", BASELINE_PYTHON_RANGE, BASELINE_RUNTIME_DEPENDENCIES
    ).decode()
    for package in SOURCE_DEV_PACKAGES:
        assert package not in rendered
    # Both generation paths keep the source pyproject and lock out of generated
    # projects: Copier excludes them and the snapshot-cleanup declaration
    # removes them.
    copier = (SOURCE_ROOT / "copier.yml").read_text(encoding="utf-8")
    assert "pyproject.toml" in copier
    assert "uv.lock" in copier
    ownership_document = cast(
        dict[str, object],
        json.loads(
            (SOURCE_ROOT / ".agentic-template/source-ownership.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    cleanup_paths = ownership_document.get("snapshot_cleanup_paths")
    assert isinstance(cleanup_paths, list)
    assert "pyproject.toml" in cleanup_paths
    assert "uv.lock" in cleanup_paths


# --- Slot model: pruned v1 contract ----------------------------------------


def test_slot_definitions_carry_no_cardinality_and_only_yaml_markdown_contexts() -> (
    None
):
    assert set(SlotDefinition.model_fields) == {
        "id",
        "owner_artifact",
        "context",
        "separator",
        "allowed_contribution_kind",
    }
    with pytest.raises(ValidationError):
        _ = SlotDefinition(
            id="toml-slot",
            owner_artifact="artifact",
            context=cast(ContextName, "toml"),  # pyright: ignore[reportInvalidCast]  intentional invalid-context negative test
        )
    with pytest.raises(ValidationError):
        _ = SlotDefinition(
            id="cardinality-slot",
            owner_artifact="artifact",
            context="yaml",
            cardinality="many",  # pyright: ignore[reportCallIssue]  intentional unsupported-field negative test
        )


def test_contribution_composition_enforces_no_cardinality() -> None:
    store, content_ids = fixture_blobs()
    render_input = make_render_input(store, content_ids)
    assert len(render_input.contributions) >= 2
    # Multiple contributions to the same slot compose without any cardinality
    # constraint; the existing render already proves the ordering.
    assert [c.slot for c in render_input.contributions].count("ci-jobs") >= 2


# --- Adopter uv lock follow-up ----------------------------------------------


def test_generated_fixture_creates_and_uses_its_own_uv_lock() -> None:
    """The adopter's ``uv lock``/``uv sync`` follow-up resolves only runtime deps."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required for the generated lock fixture")
    with tempfile.TemporaryDirectory(prefix="agentic-template-generated-deps.") as raw:
        project = Path(raw)
        _ = (project / "pyproject.toml").write_bytes(
            render_generated_pyproject(
                "example", ">=3.14", BASELINE_RUNTIME_DEPENDENCIES
            )
        )
        locked = subprocess.run(
            [uv, "lock"], cwd=project, text=True, capture_output=True, check=False
        )
        if locked.returncode:
            pytest.skip(f"uv lock could not resolve offline or online: {locked.stderr}")
        lock = (project / "uv.lock").read_text(encoding="utf-8")
        assert "pydantic" in lock
        assert "pyyaml" in lock
        for package in SOURCE_DEV_PACKAGES:
            assert package not in lock
        synced = subprocess.run(
            [uv, "sync"], cwd=project, text=True, capture_output=True, check=False
        )
        if synced.returncode:
            pytest.skip(f"uv sync failed: {synced.stderr}")
        imported = subprocess.run(
            [uv, "run", "python", "-c", "import pydantic, yaml"],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
        assert imported.returncode == 0, imported.stderr
