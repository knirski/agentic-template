#!/usr/bin/env python3
"""Exercise the GitHub-style same-tree generation path and T13 source contracts.

The bootstrap suite (``GitHubBootstrapTests``) copies the tracked source tree,
overlays the remaining canonical seed-once scaffold files, and installs
supplied and all-scaffold bundles through the real
CLI entry point.  The source-contract tests pin the ADR ownership split,
Copier exclusion consistency, snapshot-cleanup inventory consistency, and the
absence of Bash workflow adapters.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Protocol, TypedDict, cast, override
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.bootstrap.scaffold import SEED_ONCE_PATHS  # noqa: E402
from tests.factory import (  # noqa: E402
    SnapshotConfig,
    build_snapshot_project,
    copy_tree,
    pristine_snapshot,
    write_answer_bundle,
)
from tests.fixtures import (  # noqa: E402
    CLEANUP_PATHS,
    PRD,
    README,
    run,
    tracked_files,
)

RETAINED_PATHS = (
    ".rygor/source-ownership.json",
    "AGENTS.md",
    "copier.yml",
    "docs/agents/domain.md",
    "scripts/bootstrap_project.py",
    "scripts/check-release-eligibility.py",
    "scripts/validate_repository.py",
)
# Cleanup paths whose source bytes are replaced by a bootstrap-managed output
# during apply; the generated pyproject replaces the source pyproject.
CLEANUP_PATH_EXEMPTIONS = frozenset({"pyproject.toml"})
GENERATED_PYPROJECT = (
    ROOT / "scripts/fixtures/generated-dependencies/pyproject.toml"
).read_text(encoding="utf-8")
SOURCE_OWNERSHIP = ROOT / ".rygor/source-ownership.json"
MAINTENANCE_INVENTORY = ROOT / ".rygor/maintenance-artifacts.json"
ADR_0001 = ROOT / "docs/adr/0001-use-copier-for-template-updates.md"
WORKFLOWS = ROOT / ".github/workflows"

# check-release-eligibility.py contract: the fake ``gh api`` reports these
# well-formed but fictitious main-branch and stale-commit SHAs.
MAIN_BRANCH_SHA = "ab" * 20
STALE_COMMIT_SHA = "cd" * 20


class GitHubSnapshot(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory[str]  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle
    project: Path  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle

    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"
        copy_tree(pristine_snapshot(), self.project)
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse((self.project / ".direnv").exists())
        self.assertFalse((self.project / "untracked-canary.txt").exists())
        for relative in ("docs/prd.md", "README.md", "scripts/validate-project"):
            path = self.project / relative
            path.chmod(path.stat().st_mode | 0o600)

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/check_project_readiness.py"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/validate_repository.py"],
            cwd=self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_untouched_snapshot_fails_then_minimal_configuration_passes(self) -> None:
        untouched = self.run_checker()
        self.assertEqual(untouched.returncode, 1)
        self.assertIn("READINESS_PRD_MARKER", untouched.stderr)
        self.assertIn("READINESS_README_BOILERPLATE", untouched.stderr)
        _ = (self.project / "docs/prd.md").write_text(PRD, encoding="utf-8")
        _ = (self.project / "README.md").write_text(README, encoding="utf-8")
        _ = (self.project / "SECURITY.md").write_text(
            "# Security\n\nReport privately.\n", encoding="utf-8"
        )
        _ = (self.project / "CONTRIBUTING.md").write_text(
            "# Contributing\n\nWelcome.\n", encoding="utf-8"
        )
        hook = self.project / "scripts/validate-project"
        _ = hook.write_text(f"#!{sys.executable}\nprint('ok')\n", encoding="utf-8")
        hook.chmod(hook.stat().st_mode | 0o100)
        configured = self.run_validator()
        self.assertEqual(configured.returncode, 0, configured.stderr)


class GitHubBootstrapTests(unittest.TestCase):
    """A recognized GitHub snapshot installs through the shared compiler."""

    tmp: tempfile.TemporaryDirectory[str]  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle

    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_source_exposes_only_the_canonical_validation_hook(self) -> None:
        legacy_hook = ROOT / "scripts" / ("validate" + "_project.py")
        hook = ROOT / "scripts/validate-project"
        self.assertTrue(hook.is_file())
        self.assertNotEqual(hook.stat().st_mode & 0o111, 0)
        configured = run([str(hook)], cwd=ROOT)
        self.assertEqual(configured.returncode, 1)
        self.assertIn("rygor:unconfigured:validate-project", configured.stderr)
        usage = run([str(hook), "unexpected"], cwd=ROOT)
        self.assertEqual(usage.returncode, 2)
        self.assertIn("usage: scripts/validate-project", usage.stderr)
        self.assertFalse(legacy_hook.exists())
        self.assertNotIn(
            legacy_hook.relative_to(ROOT).as_posix(),
            (ROOT / "scripts/check_project_readiness.py").read_text(encoding="utf-8"),
        )

    def _snapshot(self, name: str) -> tuple[Path, Path]:
        """Materialize a live snapshot project and its recording-hook record."""
        parent = Path(self.tmp.name) / name
        parent.mkdir()
        snapshot = build_snapshot_project(
            parent, SnapshotConfig(), pristine=pristine_snapshot()
        )
        return snapshot.root, snapshot.hook_runs

    def _apply(self, project: Path, bundle: Path, *, leave: bool = False) -> int:
        argv = [
            sys.executable,
            str(project / "scripts/bootstrap_project.py"),
            "apply",
            "--bundle",
            str(bundle),
            "--target",
            str(project),
        ]
        if leave:
            argv.append("--leave-maintenance-artifacts")
        result = run(argv)
        if result.returncode not in (0, 1):
            self.fail(result.stdout + result.stderr)
        return result.returncode

    def test_supplied_apply_installs_and_cleans_the_snapshot(self) -> None:
        project, record = self._snapshot("supplied")
        bundle = write_answer_bundle(Path(self.tmp.name), supplied=True, record=record)
        exit_code = self._apply(project, bundle)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)
        self.assertTrue((project / ".rygor/project.json").is_file())
        self.assertEqual((project / "docs/prd.md").read_text(encoding="utf-8"), PRD)
        self.assertEqual((project / "README.md").read_text(encoding="utf-8"), README)
        for relative in CLEANUP_PATHS:
            if relative in CLEANUP_PATH_EXEMPTIONS:
                # The generated pyproject replaces the source one as
                # bootstrap-managed output; cleanup removes everything else.
                continue
            with self.subTest(path=relative):
                self.assertFalse((project / relative).exists(), relative)
        self.assertFalse((project / ".rygor/maintenance-artifacts.json").exists())
        self.assertEqual(
            (project / "pyproject.toml").read_text(encoding="utf-8"),
            GENERATED_PYPROJECT,
        )
        for relative in RETAINED_PATHS:
            with self.subTest(path=relative):
                self.assertTrue((project / relative).exists(), relative)
        self.assertFalse((project / ".copier-answers.yml").exists())
        self.assertTrue((project / "SECURITY.md").is_file())
        self.assertTrue((project / "CONTRIBUTING.md").is_file())

    def test_all_scaffold_apply_installs_exits_one_and_cleans(self) -> None:
        project, record = self._snapshot("scaffold")
        bundle = write_answer_bundle(Path(self.tmp.name), supplied=False, record=record)
        # Scaffold slots remain unready: the install completes and the hook
        # runs once, but the command reports not-ready at exit 1.
        self.assertEqual(self._apply(project, bundle), 1)
        self.assertTrue((project / ".rygor/project.json").is_file())
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)
        for relative in CLEANUP_PATHS:
            if relative in CLEANUP_PATH_EXEMPTIONS:
                continue
            with self.subTest(path=relative):
                self.assertFalse((project / relative).exists(), relative)
        self.assertEqual(
            (project / "pyproject.toml").read_text(encoding="utf-8"),
            GENERATED_PYPROJECT,
        )

    def test_cleanup_mismatch_refuses_then_leave_retains(self) -> None:
        project, record = self._snapshot("mismatch")
        bundle = write_answer_bundle(Path(self.tmp.name), supplied=False, record=record)
        damaged = project / "pyproject.toml"
        with damaged.open("a", encoding="utf-8") as handle:
            _ = handle.write("\n# local drift\n")
        refused = run(
            [
                sys.executable,
                str(project / "scripts/bootstrap_project.py"),
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(project),
            ]
        )
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("CLEANUP_CONTRACT_INVALID", refused.stdout + refused.stderr)
        self.assertIn("pyproject.toml", refused.stdout + refused.stderr)
        self.assertIn("--leave-maintenance-artifacts", refused.stdout + refused.stderr)
        self.assertTrue((project / ".rygor/maintenance-artifacts.json").is_file())
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 0)
        self.assertEqual(self._apply(project, bundle, leave=True), 1)
        self.assertTrue((project / ".rygor/project.json").is_file())
        self.assertTrue(damaged.is_file())
        self.assertTrue((project / ".rygor/maintenance-artifacts.json").is_file())
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)

    def test_apply_refuses_without_a_git_working_tree(self) -> None:
        parent = Path(self.tmp.name)
        project = parent / "plain"
        copy_tree(pristine_snapshot(), project)
        bundle = write_answer_bundle(
            parent, supplied=True, record=parent / "plain-runs"
        )
        result = run(
            [
                sys.executable,
                str(project / "scripts/bootstrap_project.py"),
                "apply",
                "--bundle",
                str(bundle),
                "--target",
                str(project),
            ]
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertFalse((project / ".rygor/project.json").exists())


class _InventoryEntry(TypedDict):
    path: str
    kind: str
    sha256: str


class _InventoryDocument(TypedDict):
    schema_version: int
    entries: list[_InventoryEntry]


class _OwnershipDocument(TypedDict):
    snapshot_cleanup_paths: list[str]


# A shell-script reference inside a run command: ``.sh`` followed by a
# separator or end of line.  ``${{ github.sha }}`` and similar expressions
# contain ``.sh`` textually but never a script filename.
_SHELL_SCRIPT_REFERENCE = re.compile(r"\.sh(?=[\s\"'#;)&<>|]|$)")


def _yaml_mapping(path: Path) -> object:
    """Load a YAML document; callers cast the shape they expect."""
    with path.open(encoding="utf-8") as handle:
        return cast(object, yaml.safe_load(handle))


def _json_mapping(path: Path) -> object:
    """Load a JSON document; callers cast the shape they expect."""
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


# Copier's own safety exclusions, re-declared because a custom _exclude list
# replaces them; the maintenance set is the cleanup-inventory contract.
COPIER_SAFETY_EXCLUSIONS = frozenset(
    {
        ".DS_Store",
        ".direnv",
        ".git",
        ".hypothesis",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage",
        ".svn",
        ".venv",
        "~*",
        "*.py[co]",
        "__pycache__",
        "copier.yaml",
        "result",
    }
)
BOOTSTRAP_MANAGED_DOCUMENTS = frozenset(
    {
        "docs/capabilities.md",
        "docs/delivery-workflow.md",
        "docs/github-setup.md",
        "docs/template-updates.md",
    }
)
ADOPTER_OWNED_OUTPUTS = frozenset({".github/workflows/project-validation.yml"})
COPIER_SEED_ONCE_EXCLUSIONS = frozenset(
    "/" + path.value
    if path.value in {"README.md", "SECURITY.md", "CONTRIBUTING.md"}
    else path.value
    for path in SEED_ONCE_PATHS
)


class SourceContractTests(unittest.TestCase):
    """T13 source declarations: ownership split, exclusions, and inventory."""

    def test_adr_0001_states_the_ownership_split(self) -> None:
        text = ADR_0001.read_text(encoding="utf-8")
        self.assertIn("Copier owns source lifecycle updates", text)
        self.assertIn("bootstrap owns derived-output reconciliation", text)

    def test_copier_excludes_pin_the_maintenance_and_safety_sets(self) -> None:
        config = cast(dict[str, object], _yaml_mapping(ROOT / "copier.yml"))
        excludes = set(cast(list[str], config["_exclude"]))
        inventory = cast(_InventoryDocument, _json_mapping(MAINTENANCE_INVENTORY))
        maintenance = set(
            [entry["path"] for entry in inventory["entries"]]
            + [".rygor/maintenance-artifacts.json"]
        )
        self.assertEqual(
            excludes,
            maintenance
            | BOOTSTRAP_MANAGED_DOCUMENTS
            | ADOPTER_OWNED_OUTPUTS
            | COPIER_SEED_ONCE_EXCLUSIONS
            | COPIER_SAFETY_EXCLUSIONS,
            "_exclude must cover maintenance, managed-document, and safety sets",
        )

    def test_source_ownership_matches_the_cleanup_inventory(self) -> None:
        ownership = cast(_OwnershipDocument, _json_mapping(SOURCE_OWNERSHIP))
        inventory = cast(_InventoryDocument, _json_mapping(MAINTENANCE_INVENTORY))
        self.assertEqual(
            ownership["snapshot_cleanup_paths"],
            sorted(entry["path"] for entry in inventory["entries"]),
        )

    def test_cleanup_inventory_matches_the_tracked_source(self) -> None:
        expected = expected_cleanup_inventory()
        committed = cast(_InventoryDocument, _json_mapping(MAINTENANCE_INVENTORY))
        self.assertEqual(
            committed,
            expected,
            "maintenance-artifacts.json is stale; regenerate it from the tracked source",
        )

    def test_no_bash_workflow_adapters_or_shellcheck_configuration(self) -> None:
        self.assertFalse((ROOT / ".shellcheckrc").exists())
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            with self.subTest(workflow=workflow.name):
                self.assertNotIn("shell: bash", text)
                self.assertNotIn("shellcheck", text)
                # Textual scan, never YAML parsing: a ``run:`` key at any
                # indentation starts a block, and lines indented deeper than
                # the key are its multiline continuations.  A blank line keeps
                # the block open; any other line at or above the key indent
                # ends it.
                run_indent: int | None = None
                for line in text.splitlines():
                    stripped = line.lstrip()
                    if stripped.startswith("run:"):
                        run_indent = len(line) - len(stripped)
                    elif (
                        line.strip()
                        and run_indent is not None
                        and len(line) - len(line.lstrip()) <= run_indent
                    ):
                        run_indent = None
                    if run_indent is not None:
                        self.assertNotRegex(line, _SHELL_SCRIPT_REFERENCE, line)

    def test_release_eligibility_script_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rygor-eligibility.") as raw:
            parent = Path(raw)
            fake_gh = parent / "gh"
            _ = fake_gh.write_text(
                f"#!/usr/bin/env python3\nprint('{MAIN_BRANCH_SHA}')\n",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)
            output = parent / "output.txt"
            _ = output.write_text("", encoding="utf-8")
            env = {
                **dict(os.environ),
                "PATH": str(parent) + os.pathsep + os.environ.get("PATH", ""),
                "GH_TOKEN": "token",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_SHA": MAIN_BRANCH_SHA,
                "GITHUB_OUTPUT": str(output),
            }
            script = str(ROOT / "scripts/check-release-eligibility.py")
            eligible = run([sys.executable, script], env=env)
            self.assertEqual(eligible.returncode, 0, eligible.stderr)
            self.assertIn("eligible=true", output.read_text(encoding="utf-8"))
            env["GITHUB_SHA"] = STALE_COMMIT_SHA
            stale = run([sys.executable, script], env=env)
            self.assertEqual(stale.returncode, 0, stale.stderr)
            self.assertIn("eligible=false", output.read_text(encoding="utf-8"))
            missing = run([sys.executable, script], env={**env, "GITHUB_SHA": ""})
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)


class _EligibilityScript(Protocol):
    """The importable surface of scripts/check-release-eligibility.py."""

    subprocess: ModuleType

    def main(self) -> int: ...


def _load_eligibility_script() -> _EligibilityScript:
    """Load the hyphenated eligibility script under an importable name."""

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_release_eligibility", ROOT / "scripts/check-release-eligibility.py"
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load scripts/check-release-eligibility.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_EligibilityScript, cast(object, module))


class EligibilityScriptBranchTests(unittest.TestCase):
    """In-process branch coverage for the release-eligibility script.

    The subprocess contract test above drives the real executable with a fake
    ``gh`` binary; pytest-cov cannot measure that child process, so this suite
    also exercises ``main()`` in-process to keep the hardened branches
    counted by the coverage gate.
    """

    script: _EligibilityScript  # pyright: ignore[reportUninitializedInstanceVariable]  initialized in unittest setUp lifecycle

    @override
    def setUp(self) -> None:
        self.script = _load_eligibility_script()

    def _run(
        self,
        *,
        gh: SimpleNamespace | None = None,
        error: Exception | None = None,
        **env: str,
    ) -> int:
        if (gh is None) == (error is None):
            raise AssertionError("pass exactly one of gh or error")
        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_SHA": MAIN_BRANCH_SHA,
                    "GH_TOKEN": "token",
                    # CI always sets GITHUB_OUTPUT; pin it empty so in-process
                    # runs never append to the live job output file.
                    "GITHUB_OUTPUT": "",
                    **env,
                },
            ),
            patch.object(
                self.script.subprocess,
                "run",
                return_value=gh if gh is not None else None,
                side_effect=error,
            ),
        ):
            return self.script.main()

    def test_eligible_when_the_validated_commit_is_the_main_tip(self) -> None:
        gh = SimpleNamespace(returncode=0, stdout=MAIN_BRANCH_SHA, stderr="")
        with tempfile.TemporaryDirectory(prefix="rygor-eligibility.") as raw:
            output = Path(raw) / "output.txt"
            _ = output.write_text("", encoding="utf-8")
            self.assertEqual(self._run(gh=gh, GITHUB_OUTPUT=str(output)), 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "eligible=true\n")

    def test_stale_commit_is_not_eligible(self) -> None:
        gh = SimpleNamespace(returncode=0, stdout=MAIN_BRANCH_SHA, stderr="")
        self.assertEqual(self._run(gh=gh, GITHUB_SHA=STALE_COMMIT_SHA), 0)

    def test_missing_environment_is_a_usage_error(self) -> None:
        gh = SimpleNamespace(returncode=0, stdout=MAIN_BRANCH_SHA, stderr="")
        self.assertEqual(self._run(gh=gh, GITHUB_SHA=""), 2)

    def test_rejects_a_malformed_repository_name(self) -> None:
        gh = SimpleNamespace(returncode=0, stdout=MAIN_BRANCH_SHA, stderr="")
        self.assertEqual(
            self._run(gh=gh, GITHUB_REPOSITORY="not an owner/repository pair"), 2
        )

    def test_gh_api_failure_is_a_usage_error(self) -> None:
        gh = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        self.assertEqual(self._run(gh=gh), 2)

    def test_gh_timeout_is_a_usage_error(self) -> None:
        self.assertEqual(
            self._run(error=subprocess.TimeoutExpired("gh", timeout=30)), 2
        )

    def test_missing_gh_binary_is_a_usage_error(self) -> None:
        self.assertEqual(self._run(error=OSError("no such file: gh")), 2)


def expected_cleanup_inventory() -> dict[str, object]:
    """Recompute the inventory exactly as the snapshot observer sees it.

    Tracked files only (``git ls-files``); modes are canonicalized the same
    way the observer digests them (0o644 plus the executable bit for files,
    0o755 for directories), so the committed inventory matches a fixture
    copy of the tracked source under any umask.
    """

    from scripts.bootstrap.paths import RepoPath
    from scripts.bootstrap.scaffold import cleanup_directory_digest

    tracked = tracked_files(ROOT)
    entries: list[dict[str, str]] = []
    for raw in CLEANUP_PATHS:
        path = ROOT / raw
        if path.is_file():
            entries.append({"path": raw, "kind": "file", "sha256": _sha256_file(path)})
            continue
        prefix = raw + "/"
        children = [entry for entry in tracked if entry.startswith(prefix)]
        files: list[tuple[RepoPath, bytes, int]] = []
        directories: list[tuple[RepoPath, int]] = []
        seen_dirs: set[str] = set()
        for child in children:
            child_path = ROOT / child
            files.append(
                (
                    RepoPath(child),
                    child_path.read_bytes(),
                    0o644 | (child_path.stat().st_mode & 0o100),
                )
            )
            parent = Path(child).parent
            while parent.as_posix() != raw and parent.as_posix() != ".":
                if parent.as_posix() not in seen_dirs:
                    seen_dirs.add(parent.as_posix())
                    directories.append((RepoPath(parent.as_posix()), 0o755))
                parent = parent.parent
        entries.append(
            {
                "path": raw,
                "kind": "directory",
                "sha256": cleanup_directory_digest(
                    RepoPath(raw), files=tuple(files), directories=tuple(directories)
                ),
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    return {"schema_version": 1, "entries": entries}


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    _ = unittest.main()
