"""Source-tree integrated-fixture wiring (T16).

The apply pipeline compiles per-profile CI as managed output, so generated
projects receive exactly the workflow files for their selected profile and
drift in the managed CI is detected by the standard ``status`` machinery
(``restore`` is the later lifecycle task).  The source's own committed
workflow files stay byte-identical to their canonical compiled renders, the
source never commits Nix workflow files (so adopters cannot inherit Nix),
maintainer-only jobs live in a workflow excluded from generated projects, and
no Actions YAML parser, semantic workflow normal form, allowlist, or
trust-predicate conformance fixture remains.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import cast

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.capability_fragments import CORE_CI_PATH  # noqa: E402
from scripts.bootstrap.resolver import resolve_bundle  # noqa: E402
from scripts.bootstrap.result import Err, Ok  # noqa: E402
from scripts.bootstrap.schemas import BootstrapBundle  # noqa: E402

__all__ = ["CORE_CI_PATH", "_activate_source", "render_for"]
from scripts.bootstrap.template_contract import SOURCE_WORKFLOW_SELECTIONS  # noqa: E402
from tests.fixtures import (  # noqa: E402
    ALL_CAPABILITIES,
    CLEANUP_PATHS,
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    copy_tracked,
    render_for,
    run,
    scaffold_hook,
    write_bundle,
)

# The source-maintainer-only workflows: excluded from generated projects by
# the Copier _exclude list and removed from GitHub snapshots by the cleanup
# contract, so adopters never receive the maintainer check suite.
MAINTAINER_WORKFLOWS = frozenset(
    {
        ".github/workflows/template-ci.yml",
        ".github/workflows/copier-smoke.yml",
        ".github/workflows/mutation.yml",
    }
)
# Capability artifacts are source-maintainer files too: committed for the
# source's own use but excluded from generated projects and compiled per-profile
# by apply, so unselected adopters never receive them.  The set spans workflow
# and non-workflow outputs, hence the name.
CAPABILITY_ARTIFACTS = frozenset(
    {
        ".github/workflows/pr-agent.yml",
        ".github/workflows/pr-agent-commands.yml",
        ".github/workflows/semantic-release.yml",
        ".pr_agent.toml",
        ".releaserc",
    }
)
# The maintainer-only jobs in template-ci.yml.  None may appear in any
# compiled render that generated projects receive.
MAINTAINER_ONLY_MARKERS = (
    "uv sync",
    "ruff check",
    "basedpyright",
    "pytest --cov",
    "coverage.xml",
    "actionlint",
)


def test_maintainer_only_jobs_are_excluded_from_generated_projects() -> None:
    source_ownership = cast(
        dict[str, object],
        json.loads(
            (ROOT / ".agentic-template/source-ownership.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    copier_config = cast(
        dict[str, object],
        yaml.safe_load((ROOT / "copier.yml").read_text(encoding="utf-8")),
    )
    cleanup_paths = cast(list[str], source_ownership["snapshot_cleanup_paths"])
    excludes = set(cast(list[str], copier_config["_exclude"]))
    for relative in (*MAINTAINER_WORKFLOWS, *CAPABILITY_ARTIFACTS):
        assert relative in cleanup_paths
        assert relative in excludes
    # The snapshot declaration is the single source of truth: the test-side
    # mirror and the cleanup set must stay in lockstep, and the Copier _exclude
    # list must cover every declared cleanup path (plus the inventory itself).
    assert set(CLEANUP_PATHS) == set(cleanup_paths)
    assert set(CLEANUP_PATHS) <= excludes
    assert ".agentic-template/maintenance-artifacts.json" in excludes
    assert ".github/workflows/project-validation.yml" in excludes
    assert ".github/workflows/project-validation.yml" not in set(
        cast(list[str], source_ownership["lifecycle_paths"])
    )

    managed_documents = {
        "docs/capabilities.md",
        "docs/delivery-workflow.md",
        "docs/github-setup.md",
        "docs/template-updates.md",
    }
    assert managed_documents.isdisjoint(
        set(cast(list[str], source_ownership["lifecycle_paths"]))
    )
    assert managed_documents <= excludes

    maintainer = (ROOT / ".github/workflows/template-ci.yml").read_text(
        encoding="utf-8"
    )
    for marker in MAINTAINER_ONLY_MARKERS:
        assert marker in maintainer, f"template-ci.yml lost maintainer job {marker}"

    # No compiled render adopters receive contains the maintainer check suite.
    for path, selection in SOURCE_WORKFLOW_SELECTIONS.items():
        rendered = render_for(selection)[path].decode("utf-8")
        for marker in MAINTAINER_ONLY_MARKERS:
            assert marker not in rendered, f"{path} leaked maintainer job {marker}"


def test_source_workflows_match_the_frozen_security_fixtures() -> None:
    # The source capability workflows are byte-identical to the frozen
    # security fixtures, so the structural preflight policy and local canary
    # coverage in test_secret_preflight.py also pin the source itself.
    assert (ROOT / ".github/workflows/pr-agent.yml").read_bytes() == (
        ROOT / "scripts/fixtures/workflows/pr-agent-gemini.yml"
    ).read_bytes()
    assert (ROOT / ".github/workflows/semantic-release.yml").read_bytes() == (
        ROOT / "scripts/fixtures/workflows/semantic-release.yml"
    ).read_bytes()


def test_release_requires_copier_generation_coverage() -> None:
    """The release job must depend on the complete Copier generation gate."""
    maintainer = (ROOT / ".github/workflows/template-ci.yml").read_text(
        encoding="utf-8"
    )
    copier = (ROOT / ".github/workflows/copier-smoke.yml").read_text(encoding="utf-8")
    assert "  workflow_call:" in copier
    assert "  copier-smoke:\n" in maintainer
    assert "uses: ./.github/workflows/copier-smoke.yml" in maintainer
    assert (
        "needs: [python-source, source-fixtures, workflow-lint, copier-smoke]"
        in maintainer
    )


def test_copier_smoke_retries_only_the_transient_teardown_race() -> None:
    """The smoke step absorbs the copier teardown race, nothing else.

    The upstream race aborts healthy runs during tempdir cleanup with
    "[Errno 39] Directory not empty" under a ``copier.*.new_copy.*`` path.
    The retry guard must key on exactly that signature so real smoke-test
    regressions still fail fast.
    """
    copier = (ROOT / ".github/workflows/copier-smoke.yml").read_text(encoding="utf-8")
    assert 'grep -q "Errno 39" <<<"$out"' in copier
    assert 'grep -q "new_copy" <<<"$out"' in copier
    assert 'grep -q "Directory not empty" <<<"$out"' in copier
    for invocation in ("tests/test_copier.py", "tests/test_copier_bootstrap.py"):
        assert f"retry_smoke uv run python {invocation}" in copier


# The modules that own workflow rendering; the conformance-free pin below is
# scoped to them rather than the whole scripts tree, so unrelated prose or
# future legitimate YAML use elsewhere cannot trip it.
WORKFLOW_RENDER_MODULES = (
    ROOT / "scripts/bootstrap/capability_fragments.py",
    ROOT / "scripts/bootstrap/contributions.py",
    ROOT / "scripts/bootstrap/render.py",
    ROOT / "scripts/validate_template.py",
)


def test_no_actions_yaml_parser_or_conformance_fixture_remains() -> None:
    # No Actions YAML parser, semantic workflow normal form, allowlist, or
    # trust-predicate fixture is defined in the workflow-rendering modules;
    # PyYAML is limited to scalar emission in the render boundary and never
    # parses workflows.
    for path in WORKFLOW_RENDER_MODULES:
        text = path.read_text(encoding="utf-8")
        for token in ("allowlist", "trust_predicate", "trust-predicate"):
            assert token not in text, f"{path} still references {token}"
        assert "yaml.safe_load" not in text, f"{path} still parses workflow YAML"
    render = (ROOT / "scripts/bootstrap/render.py").read_text(encoding="utf-8")
    assert "yaml.safe_dump" in render


def test_every_committed_workflow_is_pinned_or_excluded() -> None:
    """Every committed workflow is either source-pinned or excluded from adopters.

    A newly committed workflow must be added to ``SOURCE_WORKFLOW_SELECTIONS``
    (pinned byte-for-byte as source CI) or to the snapshot cleanup/Copier
    exclude sets -- otherwise it silently ships into every generated project and
    the "adopters receive exactly their selection" guarantee rots.
    """
    source_ownership = cast(
        dict[str, object],
        json.loads(
            (ROOT / ".agentic-template/source-ownership.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    copier_config = cast(
        dict[str, object],
        yaml.safe_load((ROOT / "copier.yml").read_text(encoding="utf-8")),
    )
    excluded = set(cast(list[str], source_ownership["snapshot_cleanup_paths"]))
    excluded |= set(cast(list[str], copier_config["_exclude"]))
    pinned = set(SOURCE_WORKFLOW_SELECTIONS)
    committed = {
        f".github/workflows/{path.name}"
        for path in (ROOT / ".github/workflows").glob("*.yml")
    }
    homeless = sorted(committed - pinned - excluded)
    assert not homeless, (
        "committed workflows neither pinned nor excluded: " + ", ".join(homeless)
    )


def _resolved_effective(bundle: BootstrapBundle) -> tuple[str, ...]:
    """The dependency-topological effective order the resolver derives."""
    match resolve_bundle(bundle):
        case Ok(resolved):
            return resolved.effective
        case Err(failure):
            raise AssertionError(f"bundle resolution failed: {failure}")


def _activate_source(
    parent: Path,
    *,
    capabilities: tuple[str, ...] | None = None,
    capability_settings: dict[str, dict[str, str | bool]] | None = None,
    retain_maintenance: bool = False,
) -> tuple[Path, Path]:
    """Copy the tracked source, overlay remaining scaffold slots, and apply one bundle.

    With ``retain_maintenance`` the apply keeps the maintenance inventory (the
    documented ``--leave-maintenance-artifacts`` repair path).
    """
    project = parent / "project"
    copy_tracked(ROOT, project)
    record = parent / "hook-runs"
    _ = record.write_text("", encoding="utf-8")
    hook = project / "scripts/validate-project"
    _ = hook.write_text(scaffold_hook(record), encoding="utf-8")
    hook.chmod(0o755)
    _ = (project / "scripts/bootstrap/fragments/scaffolds/validate-project").write_text(
        scaffold_hook(record), encoding="utf-8"
    )
    _ = (project / "CONTRIBUTING.md").write_text(
        SCAFFOLD_CONTRIBUTING, encoding="utf-8"
    )
    _ = (project / "SECURITY.md").write_text(SCAFFOLD_SECURITY, encoding="utf-8")
    for args in (
        ("init", "-q", "-b", "main"),
        ("add", "-A"),
        (
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "scaffold",
        ),
    ):
        result = run(["git", "-C", str(project), *args])
        assert result.returncode == 0, result.stderr
    bundle = write_bundle(
        parent,
        supplied=True,
        record=record,
        capabilities=capabilities,
        capability_settings=capability_settings,
    )
    apply_argv = [
        sys.executable,
        str(project / "scripts/bootstrap_project.py"),
        "apply",
        "--bundle",
        str(bundle),
        "--target",
        str(project),
    ]
    if retain_maintenance:
        apply_argv.append("--leave-maintenance-artifacts")
    applied = run(apply_argv)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    return project, record


def test_apply_compiles_and_manages_per_profile_ci() -> None:
    """A portable activation installs the compiled, managed baseline CI."""
    with tempfile.TemporaryDirectory(prefix="agentic-template-source.") as raw:
        project, _record = _activate_source(Path(raw))

        # The installed ci.yml is the compiled portable render -- managed
        # output, byte-identical to the source's committed baseline.
        compiled_ci = render_for(())[CORE_CI_PATH]
        committed_ci = (ROOT / CORE_CI_PATH).read_bytes()
        installed_ci = project / CORE_CI_PATH
        assert compiled_ci == committed_ci == installed_ci.read_bytes()

        # ci.yml is a managed artifact the status/restore machinery tracks.
        manifest = cast(
            dict[str, object],
            json.loads(
                (project / ".agentic-template/project.json").read_text(encoding="utf-8")
            ),
        )
        managed_paths = {
            str(entry["path"])
            for entry in cast(list[dict[str, str]], manifest["managed"])
        }
        assert CORE_CI_PATH in managed_paths

        # Maintainer-only and capability workflows are removed by snapshot
        # cleanup, and Nix workflows are never present because the source never
        # commits them: an unselected adopter receives no capability artifact.
        for relative in (*MAINTAINER_WORKFLOWS, *CAPABILITY_ARTIFACTS):
            assert not (project / relative).exists(), relative
        for relative in (
            ".github/workflows/nix.yml",
            ".github/workflows/cachix-publish.yml",
        ):
            assert not (project / relative).exists(), relative

        cli = [sys.executable, str(project / "scripts/bootstrap_project.py")]
        clean = run([*cli, "status", "--target", str(project)])
        assert clean.returncode == 0, clean.stdout + clean.stderr
        assert "managed: verified: no managed drift" in clean.stdout

        # Drift in the managed CI is reported by status; restore repairs it in
        # the later lifecycle task (T18).
        with installed_ci.open("a", encoding="utf-8") as handle:
            _ = handle.write("  # local drift\n")
        drifted = run([*cli, "status", "--target", str(project)])
        assert drifted.returncode == 0, drifted.stdout + drifted.stderr
        assert "managed: drift: .github/workflows/ci.yml" in drifted.stdout


def test_apply_compiles_selected_capability_workflows() -> None:
    """A selected profile compiles its capability workflows through apply.

    The source never commits Nix workflow files, yet selecting the capabilities
    makes apply compile every selected artifact into the project -- and only
    those, so adopters receive exactly the workflows they selected.
    """
    with tempfile.TemporaryDirectory(prefix="agentic-template-source.") as raw:
        parent = Path(raw)
        selection = tuple(sorted(ALL_CAPABILITIES))
        project, _record = _activate_source(
            parent,
            capabilities=selection,
            capability_settings={"cachix-publish": {"cache_name": "example"}},
        )
        # Render the expected output in the same effective order apply resolves
        # (dependency-topological), closing the test/apply ordering gap.
        bundle = BootstrapBundle.model_validate(
            json.loads((parent / "bundle/bootstrap.json").read_text(encoding="utf-8"))
        )
        compiled = render_for(_resolved_effective(bundle))
        workflow_names = {
            ".github/workflows/ci.yml",
            ".github/workflows/project-validation.yml",
            ".github/workflows/semantic-release.yml",
            ".github/workflows/nix.yml",
            ".github/workflows/cachix-publish.yml",
            ".github/workflows/pr-agent.yml",
            ".github/workflows/pr-agent-commands.yml",
        }
        managed_workflows = workflow_names - {
            ".github/workflows/project-validation.yml"
        }
        assert managed_workflows <= set(compiled)
        for relative in managed_workflows:
            assert (project / relative).read_bytes() == compiled[relative], relative
        # Exactly the selected workflow set and no more: the maintainer-only
        # workflows must never leak into an adopter's .github/workflows.
        installed = {
            f".github/workflows/{path.name}"
            for path in (project / ".github/workflows").iterdir()
            if path.suffix == ".yml"
        }
        assert installed == workflow_names, (
            "adopter received unexpected workflows: "
            + ", ".join(sorted(installed - workflow_names))
        )
        # The non-workflow capability artifacts compile per-profile too.
        for relative in (".releaserc", ".pr_agent.toml", "flake.nix", "flake.lock"):
            assert relative in compiled, f"{relative} missing from the compiled render"
            assert (project / relative).read_bytes() == compiled[relative], relative
        assert (ROOT / ".github/workflows/nix.yml").exists() is False


def test_leave_maintenance_artifacts_retains_and_still_validates() -> None:
    """A repaired adopter that retains the maintenance inventory validates.

    ``apply --leave-maintenance-artifacts`` keeps
    ``.agentic-template/maintenance-artifacts.json``, so the shipped
    ``scripts/validate_template.py`` must not mistake a managed adopter for the
    template source and pin its per-profile compiled CI against the source's
    portable baseline.
    """
    with tempfile.TemporaryDirectory(prefix="agentic-template-source.") as raw:
        project, _record = _activate_source(
            Path(raw),
            capabilities=tuple(sorted(ALL_CAPABILITIES)),
            capability_settings={"cachix-publish": {"cache_name": "example"}},
            retain_maintenance=True,
        )
        assert (project / ".agentic-template/maintenance-artifacts.json").is_file()
        assert (project / ".agentic-template/project.json").is_file()
        validated = run([sys.executable, str(project / "scripts/validate_template.py")])
        assert validated.returncode == 0, validated.stdout + validated.stderr
