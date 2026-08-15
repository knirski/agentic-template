#!/usr/bin/env python3
"""Exercise the GitHub-style same-tree generation path and T13 source contracts.

The bootstrap suite (``GitHubBootstrapTests``) copies the tracked source tree,
overlays the canonical seed-once scaffold (the source does not yet ship
``CONTRIBUTING.md`` and the extensionless hook; T20 completes that
transition), and installs supplied and all-scaffold bundles through the real
CLI entry point.  The source-contract tests pin the ADR ownership split,
Copier exclusion consistency, snapshot-cleanup inventory consistency, and the
absence of Bash workflow adapters.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast, override

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fixtures import (  # noqa: E402
    CLEANUP_PATHS,
    PRD,
    README,
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    copy_tracked,
    run,
    scaffold_hook,
    tracked_files,
    write_bundle,
)

RETAINED_PATHS = (
    ".agentic-template/source-ownership.json",
    "AGENTS.md",
    "copier.yml",
    "docs/agents/domain.md",
    "scripts/bootstrap_project.py",
    "scripts/check-release-eligibility.py",
    "scripts/validate_repository.py",
)
SOURCE_OWNERSHIP = ROOT / ".agentic-template/source-ownership.json"
MAINTENANCE_INVENTORY = ROOT / ".agentic-template/maintenance-artifacts.json"
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
        if shutil.which("git"):
            copy_tracked(ROOT, self.project)
        else:
            _ = shutil.copytree(
                ROOT,
                self.project,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".direnv",
                    "__pycache__",
                    "result",
                    ".venv",
                    ".hypothesis",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".mypy_cache",
                    ".coverage",
                ),
            )
        self.assertFalse((self.project / ".git").exists())
        self.assertFalse((self.project / ".direnv").exists())
        self.assertFalse((self.project / "untracked-canary.txt").exists())
        for relative in ("docs/prd.md", "README.md", "scripts/validate_project.py"):
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
        hook = self.project / "scripts/validate_project.py"
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

    def _snapshot(self, name: str) -> tuple[Path, Path]:
        """Copy the tracked source, overlay the seed-once scaffold, git-init."""
        parent = Path(self.tmp.name)
        project = parent / name
        copy_tracked(ROOT, project)
        record = parent / f"{name}-hook-runs"
        _ = record.write_text("", encoding="utf-8")
        hook = project / "scripts/validate-project"
        _ = hook.write_text(scaffold_hook(record), encoding="utf-8")
        hook.chmod(0o755)
        _ = (project / "CONTRIBUTING.md").write_text(
            SCAFFOLD_CONTRIBUTING, encoding="utf-8"
        )
        # The scaffold slot contract requires marker-bearing placeholder
        # content; the source's real SECURITY.md is not a placeholder.
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
            if result.returncode:
                self.fail(result.stderr)
        return project, record

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
        bundle = write_bundle(Path(self.tmp.name), supplied=True, record=record)
        exit_code = self._apply(project, bundle)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)
        self.assertTrue((project / ".agentic-template/project.json").is_file())
        self.assertEqual((project / "docs/prd.md").read_text(encoding="utf-8"), PRD)
        self.assertEqual((project / "README.md").read_text(encoding="utf-8"), README)
        for relative in CLEANUP_PATHS:
            with self.subTest(path=relative):
                self.assertFalse((project / relative).exists(), relative)
        self.assertFalse(
            (project / ".agentic-template/maintenance-artifacts.json").exists()
        )
        for relative in RETAINED_PATHS:
            with self.subTest(path=relative):
                self.assertTrue((project / relative).exists(), relative)
        self.assertFalse((project / ".copier-answers.yml").exists())
        self.assertTrue((project / "SECURITY.md").is_file())
        self.assertTrue((project / "CONTRIBUTING.md").is_file())

    def test_all_scaffold_apply_installs_exits_one_and_cleans(self) -> None:
        project, record = self._snapshot("scaffold")
        bundle = write_bundle(Path(self.tmp.name), supplied=False, record=record)
        # Scaffold slots remain unready: the install completes and the hook
        # runs once, but the command reports not-ready at exit 1.
        self.assertEqual(self._apply(project, bundle), 1)
        self.assertTrue((project / ".agentic-template/project.json").is_file())
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)
        for relative in CLEANUP_PATHS:
            with self.subTest(path=relative):
                self.assertFalse((project / relative).exists(), relative)

    def test_cleanup_mismatch_refuses_then_leave_retains(self) -> None:
        project, record = self._snapshot("mismatch")
        bundle = write_bundle(Path(self.tmp.name), supplied=False, record=record)
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
        self.assertTrue(
            (project / ".agentic-template/maintenance-artifacts.json").is_file()
        )
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 0)
        self.assertEqual(self._apply(project, bundle, leave=True), 1)
        self.assertTrue((project / ".agentic-template/project.json").is_file())
        self.assertTrue(damaged.is_file())
        self.assertTrue(
            (project / ".agentic-template/maintenance-artifacts.json").is_file()
        )
        self.assertEqual(len(record.read_text(encoding="utf-8").splitlines()), 1)

    def test_apply_refuses_without_a_git_working_tree(self) -> None:
        parent = Path(self.tmp.name)
        project = parent / "plain"
        copy_tracked(ROOT, project)
        bundle = write_bundle(parent, supplied=True, record=parent / "plain-runs")
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
        self.assertFalse((project / ".agentic-template/project.json").exists())


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
_SHELL_SCRIPT_REFERENCE = re.compile(r"\.sh(?=[\s\"'#;]|$)")


def _yaml_mapping(path: Path) -> object:
    """Load a YAML document; callers cast the shape they expect."""
    with path.open(encoding="utf-8") as handle:
        return cast(object, yaml.safe_load(handle))


def _json_mapping(path: Path) -> object:
    """Load a JSON document; callers cast the shape they expect."""
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


class SourceContractTests(unittest.TestCase):
    """T13 source declarations: ownership split, exclusions, and inventory."""

    def test_adr_0001_states_the_ownership_split(self) -> None:
        text = ADR_0001.read_text(encoding="utf-8")
        self.assertIn("Copier owns source lifecycle updates", text)
        self.assertIn("bootstrap owns derived-output reconciliation", text)

    def test_copier_excludes_match_the_cleanup_inventory(self) -> None:
        config = cast(dict[str, object], _yaml_mapping(ROOT / "copier.yml"))
        excludes = sorted(cast(list[str], config["_exclude"]))
        inventory = cast(_InventoryDocument, _json_mapping(MAINTENANCE_INVENTORY))
        expected = sorted(
            [entry["path"] for entry in inventory["entries"]]
            + [".agentic-template/maintenance-artifacts.json"]
        )
        self.assertEqual(excludes, expected)

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
                in_run_block = False
                for line in text.splitlines():
                    if line.startswith("run:"):
                        in_run_block = True
                    elif not (in_run_block and line.startswith(" ")):
                        in_run_block = False
                    if in_run_block:
                        # Textual scan, never YAML parsing: run commands and
                        # their multiline continuations carry no .sh scripts.
                        self.assertNotRegex(line, _SHELL_SCRIPT_REFERENCE, line)

    def test_release_eligibility_script_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agentic-template-eligibility.") as raw:
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


def expected_cleanup_inventory() -> dict[str, object]:
    """Recompute the inventory exactly as the snapshot observer sees it.

    Tracked files only (``git ls-files``), real working-tree modes, so the
    committed inventory matches what a fixture copy of the tracked source
    observes.
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
                    child_path.stat().st_mode & 0o7777,
                )
            )
            parent = Path(child).parent
            while parent.as_posix() != raw and parent.as_posix() != ".":
                if parent.as_posix() not in seen_dirs:
                    seen_dirs.add(parent.as_posix())
                    directories.append(
                        (
                            RepoPath(parent.as_posix()),
                            (ROOT / parent).stat().st_mode & 0o7777,
                        )
                    )
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
