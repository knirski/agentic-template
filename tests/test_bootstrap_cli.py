"""CLI adapters, scaffold classification, and end-to-end command families.

Covers T12 validation: golden command-family exit mappings, text/JSON parity,
status/planning/recovery never running the hook, refusal/rollback/recovery hook
counts, all-scaffold installs exiting nonzero while remaining installed,
cleanup marker collision and leave override, phase-specific recovery, and
post-lock revalidation.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast, get_type_hints, override
from unittest.mock import patch

from scripts.bootstrap.canonical_json import canonical_json
from scripts.bootstrap.cli import (
    ParsedCommand,
    _decode_existing_manifest,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    _init_failure,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    _manifest_identity,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    _recorded_render,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper type contract
    execute_command,
    main,
    parse_argv,
)
from scripts.bootstrap.diagnostics import RecoveryFailure
from scripts.bootstrap.errors import (
    CommandError,
    ErrnoClass,
    TransactionError,
    TransactionPrimitive,
)
from scripts.bootstrap.identity import PosixMode, TargetIdentity
from scripts.bootstrap.journal import (
    JournalEnvelope,
    JournalTarget,
    PreparationIdentity,
    PreparationRole,
    PreparationSpec,
    encode_journal,
    new_transaction_id,
)
from scripts.bootstrap.manifest import CandidateManifest
from scripts.bootstrap.plan_digest import PlanReceipt, reconstruct_plan
from scripts.bootstrap.planner import CreateFileOperation, ReplaceFileOperation
from scripts.bootstrap.presentation import (
    CommandResult,
    render_json,
    render_text,
)
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.scaffold import PROJECT_VALIDATION_SCAFFOLD
from scripts.bootstrap.transaction import derive_preparation_specs, derive_preparations
from scripts.bootstrap.values import JournalPhase

ROOT = Path(__file__).resolve().parent.parent


def test_lifecycle_manifest_helpers_preserve_candidate_type() -> None:
    decode_annotations = get_type_hints(_decode_existing_manifest)
    recorded_annotations = get_type_hints(_recorded_render)
    identity_annotations = get_type_hints(_manifest_identity)

    assert decode_annotations["return"] == Result[CandidateManifest, CommandError]
    assert recorded_annotations["manifest"] is CandidateManifest
    assert identity_annotations["manifest"] is CandidateManifest


SCAFFOLD_README = "# Placeholder\n\n<!-- agentic-template:placeholder:readme -->\n"
SCAFFOLD_PRD = "# Product\n\n<!-- agentic-template:placeholder:prd -->\n"
SCAFFOLD_SECURITY = "# Security\n\n<!-- agentic-template:placeholder:security -->\n"
SCAFFOLD_CONTRIBUTING = (
    "# Contributing\n\n<!-- agentic-template:placeholder:contributing -->\n"
)
SCAFFOLD_HOOK = (
    "#!/bin/sh\n# agentic-template:unconfigured:validate-project\n"
    "echo unconfigured\nexit 0\n"
)

SUPPLIED_README = "# Product\n\n## Setup\nRun it.\n\n## Validation\nRun `python3 scripts/validate_repository.py`.\n"
SUPPLIED_PRD = (
    "# Product\n## Problem\nP.\n## Goals\nG.\n## Non-goals\nN.\n"
    "## Users and workflows\nU.\n## Requirements\n### REQ-001: Works\nBody.\n"
    "## Quality attributes\nQ.\n## Release criteria\nR.\n## Open questions\nO.\n"
)
SUPPLIED_SECURITY = "# Security\n\nReport privately.\n"
SUPPLIED_CONTRIBUTING = "# Contributing\n\nWelcome.\n"
SUPPLIED_HOOK = "#!/bin/sh\necho ok\nexit 0\n"


def _parse(argv: list[str]) -> ParsedCommand:
    match parse_argv(argv):
        case Ok(parsed):
            assert not isinstance(parsed, str)
            return parsed
        case Err(error):
            raise AssertionError(f"parse failed: {error}")


def _exit_code(result: CommandResult) -> int:
    from scripts.bootstrap.presentation import (
        _family_exit_code,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    )

    return _family_exit_code(result.command, result.outcome)


class TemplatePackage:
    """A synthetic template root supplying the six scaffold slots plus legal files."""

    root: Path

    def __init__(self, parent: Path) -> None:
        self.root = parent / "template"
        self.root.mkdir()
        for relative, content, mode in (
            ("README.md", SCAFFOLD_README, 0o644),
            ("docs/prd.md", SCAFFOLD_PRD, 0o644),
            ("SECURITY.md", SCAFFOLD_SECURITY, 0o644),
            ("CONTRIBUTING.md", SCAFFOLD_CONTRIBUTING, 0o644),
            ("scripts/validate-project", SCAFFOLD_HOOK, 0o755),
            ("LICENSE", "Apache-2.0\n", 0o644),
            ("NOTICE.md", "Notice.\n", 0o644),
            ("LICENSES/Apache-2.0.txt", "Apache text.\n", 0o644),
            ("source-contract.txt", "template source.\n", 0o644),
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_text(content, encoding="utf-8")
            path.chmod(mode)
        project_validation = self.root / ".github/workflows/project-validation.yml"
        project_validation.parent.mkdir(parents=True, exist_ok=True)
        _ = project_validation.write_bytes(PROJECT_VALIDATION_SCAFFOLD)
        project_validation.chmod(0o644)
        ownership = self.root / ".agentic-template/source-ownership.json"
        ownership.parent.mkdir(parents=True, exist_ok=True)
        _ = ownership.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "lifecycle_paths": ["source-contract.txt"],
                    "snapshot_cleanup_paths": [],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def install_recording_hook(self, hook_runs: Path) -> None:
        """Make the template's scaffold hook record its own execution."""

        hook = self.root / "scripts/validate-project"
        _ = hook.write_text(
            "#!/bin/sh\n"
            + "# agentic-template:unconfigured:validate-project\n"
            + "echo run >> "
            + str(hook_runs)
            + "\nexit 0\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)


class ScaffoldFixture:
    """A full GitHub-style snapshot: source copy plus placeholder seed files."""

    root: Path
    hook_runs: Path

    def __init__(self, parent: Path, template: TemplatePackage) -> None:
        self.root = parent / "project"
        self.root.mkdir()
        tracked = (
            subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z"],
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .split("\0")
        )
        for relative in sorted(set(filter(None, tracked))):
            source = ROOT / relative
            if not source.is_file():
                continue
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = shutil.copy2(source, target)
        _ = shutil.copy2(
            template.root / ".agentic-template/source-ownership.json",
            self.root / ".agentic-template/source-ownership.json",
        )
        # The source's cleanup-control inventory is exercised by the
        # real-snapshot fixtures (test_github_template_readiness.py); the CLI
        # suite controls it explicitly through ``_make_fixture(maintenance=True)``
        # so its cleanup cases stay independent of the live source tree's
        # inventory.  The source-ownership declaration is generated-lifecycle
        # source and stays in the fixture.
        target = self.root / ".agentic-template/maintenance-artifacts.json"
        if target.is_file():
            _ = target.unlink()
        self.hook_runs = parent / "hook-runs"
        _ = self.hook_runs.write_text("", encoding="utf-8")
        template.install_recording_hook(self.hook_runs)
        for relative in (
            "README.md",
            "docs/prd.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
            "scripts/validate-project",
            "LICENSE",
            "NOTICE.md",
            "LICENSES/Apache-2.0.txt",
            "source-contract.txt",
            ".github/workflows/project-validation.yml",
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _ = shutil.copy2(template.root / relative, target)
        _ = subprocess.run(
            ["git", "init", "-q", "-b", "main"], cwd=self.root, check=True
        )
        _ = subprocess.run(
            ["git", "-C", str(self.root), "add", "-A"], check=True, capture_output=True
        )
        _ = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "scaffold",
            ],
            check=True,
            capture_output=True,
        )

    def run_count(self) -> int:
        return len(self.hook_runs.read_text(encoding="utf-8").splitlines())


class BundleDir:
    """A bundle directory: bootstrap.json plus content files."""

    root: Path

    def __init__(
        self,
        parent: Path,
        *,
        all_scaffold: bool,
        record_path: Path | None = None,
    ) -> None:
        self.root = parent / "bundle"
        self.root.mkdir()
        content: dict[str, object] = {
            "schema_version": 1,
            "project": {"name": "example", "default_branch": "main"},
            "profile": {"id": "portable"},
            "content": {
                "prd": (
                    {"mode": "scaffold"}
                    if all_scaffold
                    else {"mode": "file", "path": "content/prd.md"}
                ),
                "readme": (
                    {"mode": "scaffold"}
                    if all_scaffold
                    else {"mode": "file", "path": "content/readme.md"}
                ),
                "validation_hook": (
                    {"mode": "scaffold"}
                    if all_scaffold
                    else {"mode": "file", "path": "content/validate-project"}
                ),
                "security_policy": (
                    {"mode": "scaffold"}
                    if all_scaffold
                    else {"mode": "file", "path": "content/security.md"}
                ),
                "contributing": (
                    {"mode": "scaffold"}
                    if all_scaffold
                    else {"mode": "file", "path": "content/contributing.md"}
                ),
            },
            "licensing": {"mode": "retain-apache-2.0"},
            "capability_settings": {},
        }
        if not all_scaffold:
            content_dir = self.root / "content"
            content_dir.mkdir()
            _ = (content_dir / "prd.md").write_text(SUPPLIED_PRD, encoding="utf-8")
            _ = (content_dir / "readme.md").write_text(
                SUPPLIED_README, encoding="utf-8"
            )
            _ = (content_dir / "security.md").write_text(
                SUPPLIED_SECURITY, encoding="utf-8"
            )
            _ = (content_dir / "contributing.md").write_text(
                SUPPLIED_CONTRIBUTING, encoding="utf-8"
            )
            hook = content_dir / "validate-project"
            if record_path is not None:
                _ = hook.write_text(
                    "#!/bin/sh\necho run >> " + str(record_path) + "\nexit 0\n",
                    encoding="utf-8",
                )
            else:
                _ = hook.write_text(SUPPLIED_HOOK, encoding="utf-8")
            hook.chmod(0o755)
        _ = (self.root / "bootstrap.json").write_text(
            json.dumps(content, sort_keys=True), encoding="utf-8"
        )


def _make_fixture(
    tmp_path: Path,
    *,
    copier: bool = False,
    maintenance: bool = False,
) -> tuple[TemplatePackage, ScaffoldFixture]:
    template = TemplatePackage(tmp_path)
    fixture = ScaffoldFixture(tmp_path, template)
    if copier:
        _ = (fixture.root / ".copier-answers.yml").write_text(
            "_commit: 0.1.0\n", encoding="utf-8"
        )
    if maintenance:
        ownership = fixture.root / ".agentic-template/source-ownership.json"
        _ = ownership.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "lifecycle_paths": [],
                    "snapshot_cleanup_paths": ["tests"],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        inventory = fixture.root / ".agentic-template/maintenance-artifacts.json"
        _ = inventory.write_text(
            json.dumps(_inventory_document(fixture), sort_keys=True), encoding="utf-8"
        )
    return template, fixture


def _inventory_document(fixture: ScaffoldFixture) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "path": "tests",
                "kind": "directory",
                "sha256": _directory_digest(fixture),
            },
        ],
    }


def _directory_digest(fixture: ScaffoldFixture) -> str:
    # The declared digest must equal what the shell observes over the fixture
    # copy (tracked files only, canonical modes), never the live source tree
    # with its untracked caches.  Modes mirror the observer: 0o644 plus the
    # executable bit for files, 0o755 for directories.
    from scripts.bootstrap.paths import RepoPath
    from scripts.bootstrap.scaffold import cleanup_directory_digest

    files: list[tuple[RepoPath, bytes, int]] = []
    directories: list[tuple[RepoPath, int]] = []
    root = fixture.root / "tests"
    for current, dirs, names in os.walk(root):
        for name in sorted(names):
            path = Path(current) / name
            relative = RepoPath(path.relative_to(fixture.root).as_posix())
            files.append(
                (relative, path.read_bytes(), 0o644 | (path.stat().st_mode & 0o100))
            )
        for name in sorted(dirs):
            path = Path(current) / name
            relative = RepoPath(path.relative_to(fixture.root).as_posix())
            directories.append((relative, 0o755))
    return cleanup_directory_digest(
        RepoPath("tests"), files=tuple(files), directories=tuple(directories)
    )


class CliFamilyTests(unittest.TestCase):
    tmp: tempfile.TemporaryDirectory[str]  # pyright: ignore[reportUninitializedInstanceVariable]  assigned in setUp before every test
    template: TemplatePackage  # pyright: ignore[reportUninitializedInstanceVariable]  assigned in setUp before every test
    fixture: ScaffoldFixture  # pyright: ignore[reportUninitializedInstanceVariable]  assigned in setUp before every test
    bundle: BundleDir  # pyright: ignore[reportUninitializedInstanceVariable]  assigned in setUp before every test

    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        parent = Path(self.tmp.name)
        self.template, self.fixture = _make_fixture(parent)
        self.bundle = BundleDir(
            parent, all_scaffold=True, record_path=self.fixture.hook_runs
        )

    @override
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, argv: list[str]) -> CommandResult:
        return execute_command(_parse(argv), template_root=str(self.template.root))

    def target_arg(self) -> str:
        return str(self.fixture.root)

    def test_help_exits_zero(self) -> None:
        self.assertEqual(main(["--help"]), 0)
        self.assertEqual(main(["status", "--help"]), 0)

    def test_status_invalid_journal_exits_two(self) -> None:
        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        _ = (state_root / "journal.json").write_text("not json", encoding="utf-8")
        result = self.run_cli(["status", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 2)
        self.assertIn("state_root", render_text(result))

    def test_status_invalid_manifest_exits_two(self) -> None:
        manifest = self.fixture.root / ".agentic-template/project.json"
        manifest.parent.mkdir(exist_ok=True)
        _ = manifest.write_text("not json", encoding="utf-8")
        result = self.run_cli(["status", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 2)
        self.assertIn("manifest", render_text(result))

    def test_status_reports_hook_not_evaluated(self) -> None:
        result = self.run_cli(["status", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        self.assertIn("hook: not evaluated", render_text(result))

    def test_explain_adds_decision_trace(self) -> None:
        parsed = _parse(["--explain", "status", "--target", self.target_arg()])
        result = execute_command(parsed, template_root=str(self.template.root))
        text = render_text(result, explain=True)
        self.assertIn("state: status", text)
        self.assertIn("decision: describe_status", text)

    def test_color_always_emits_ansi(self) -> None:
        parsed = _parse(["--color", "always", "status", "--target", self.target_arg()])
        result = execute_command(parsed, template_root=str(self.template.root))
        self.assertIn("\x1b[", render_text(result, color=True))
        self.assertNotIn("\x1b[", render_text(result, color=False))

    def test_invalid_option_value_is_invalid_value(self) -> None:
        from scripts.bootstrap.errors import UsageError, UsageErrorKind

        for argv in (
            ["--format", "yaml", "status"],
            ["--color", "red", "status"],
        ):
            with self.subTest(argv=argv):
                match parse_argv(argv):
                    case Err(UsageError(kind=UsageErrorKind.INVALID_VALUE)):
                        pass
                    case _:
                        self.fail("expected INVALID_VALUE for an invalid option value")

    def test_usage_families_exit_two(self) -> None:
        cases = [
            ["frobnicate"],
            ["apply"],
            ["plan", "apply"],
            ["init", "--from", "x"],
            ["reconcile", "--overwrite-drift"],
            ["plan", "reconcile", "--overwrite-drift", "--out", "-"],
            ["restore", "--path", "README.md", "--path", "README.md"],
            ["--format", "json", "--quiet", "status"],
            ["--format", "json", "--color", "always", "status"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                match parse_argv(argv):
                    case Ok(_):
                        self.fail("expected a usage error")
                    case Err(_):
                        pass

    def test_init_writes_reviewable_bundle(self) -> None:
        parent = Path(self.tmp.name)
        output = parent / "out-bundle"
        result = self.run_cli(
            [
                "init",
                "--from",
                str(self.bundle.root / "bootstrap.json"),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(_exit_code(result), 0)
        self.assertTrue((output / "bootstrap.json").is_file())
        occupied = self.run_cli(
            [
                "init",
                "--from",
                str(self.bundle.root / "bootstrap.json"),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(_exit_code(occupied), 1)

    def test_init_materializes_file_content(self) -> None:
        parent = Path(self.tmp.name) / "second"
        parent.mkdir()
        bundle = BundleDir(parent, all_scaffold=False)
        output = Path(self.tmp.name) / "out-content"
        result = self.run_cli(
            [
                "init",
                "--from",
                str(bundle.root / "bootstrap.json"),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(_exit_code(result), 0)
        expected = {
            "README.md": SUPPLIED_README,
            "docs/prd.md": SUPPLIED_PRD,
            "SECURITY.md": SUPPLIED_SECURITY,
            "CONTRIBUTING.md": SUPPLIED_CONTRIBUTING,
            "scripts/validate-project": SUPPLIED_HOOK,
        }
        for relative, content in expected.items():
            target = output / relative
            self.assertTrue(target.is_file(), relative)
            self.assertEqual(target.read_text(encoding="utf-8"), content)
        self.assertEqual(stat.S_IMODE((output / "docs").stat().st_mode), 0o755)

    def test_init_failure_maps_oserror_to_closed_outcome(self) -> None:
        result = _init_failure(
            TransactionPrimitive.REMOVE_DIRECTORY,
            OSError(errno.ENOENT, "not a directory"),
            "subject",
        )
        self.assertEqual(result.command, "init")
        self.assertIsInstance(result.outcome, RecoveryFailure)
        self.assertEqual(_exit_code(result), 2)

    def test_init_maps_mkdir_failure_to_closed_outcome(self) -> None:
        parent = Path(self.tmp.name) / "third"
        parent.mkdir()
        bundle = BundleDir(parent, all_scaffold=False)
        output = Path(self.tmp.name) / "out-mkdir"
        error = TransactionError.primitive_failed(
            TransactionPrimitive.CREATE_DIRECTORY, ErrnoClass.NO_SPACE, "stage"
        )
        with patch(
            "scripts.bootstrap.cli.mkdir_parents_0755",
            return_value=Err(error),
        ):
            result = self.run_cli(
                [
                    "init",
                    "--from",
                    str(bundle.root / "bootstrap.json"),
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(_exit_code(result), 2)

    def test_init_maps_rmdir_failure_to_closed_outcome(self) -> None:
        parent = Path(self.tmp.name) / "fourth"
        parent.mkdir()
        bundle = BundleDir(parent, all_scaffold=False)
        output = Path(self.tmp.name) / "out-rmdir"
        target = Path(self.tmp.name) / "out-rmdir-target"
        target.mkdir()
        output.symlink_to(target, target_is_directory=True)
        result = self.run_cli(
            [
                "init",
                "--from",
                str(bundle.root / "bootstrap.json"),
                "--output",
                str(output),
            ]
        )
        self.assertEqual(_exit_code(result), 2)

    def test_init_maps_rename_failure_to_closed_outcome(self) -> None:
        parent = Path(self.tmp.name) / "fifth"
        parent.mkdir()
        bundle = BundleDir(parent, all_scaffold=False)
        output = Path(self.tmp.name) / "out-rename"
        with patch(
            "scripts.bootstrap.cli.os.rename",
            side_effect=OSError(errno.EXDEV, "cross-device link"),
        ):
            result = self.run_cli(
                [
                    "init",
                    "--from",
                    str(bundle.root / "bootstrap.json"),
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(_exit_code(result), 2)

    def test_init_rejects_reserved_markers(self) -> None:
        parent = Path(self.tmp.name)
        bundle = parent / "marked"
        bundle.mkdir()
        (bundle / "content").mkdir()
        _ = (bundle / "content" / "readme.md").write_text(
            "<!-- agentic-template:placeholder:readme -->\n", encoding="utf-8"
        )
        _ = (bundle / "bootstrap.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project": {"name": "example", "default_branch": "main"},
                    "profile": {"id": "portable"},
                    "content": {
                        "prd": {"mode": "scaffold"},
                        "readme": {"mode": "file", "path": "content/readme.md"},
                        "validation_hook": {"mode": "scaffold"},
                        "security_policy": {"mode": "scaffold"},
                        "contributing": {"mode": "scaffold"},
                    },
                    "licensing": {"mode": "retain-apache-2.0"},
                    "capability_settings": {},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        result = self.run_cli(
            [
                "init",
                "--from",
                str(bundle / "bootstrap.json"),
                "--output",
                str(parent / "out"),
            ]
        )
        self.assertEqual(_exit_code(result), 2)

    def test_status_describes_scaffold_and_never_exits_one(self) -> None:
        result = self.run_cli(["status", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        text = render_text(result)
        self.assertIn("scaffold", text)
        self.assertIn("github", text)
        self.assertEqual(self.fixture.run_count(), 0)

    def test_status_unsupported_target_describes_and_exits_zero(self) -> None:
        # The inspection family describes unsupported targets; it never exits 1.
        parent = Path(self.tmp.name)
        plain = parent / "plain"
        plain.mkdir()
        result = self.run_cli(["status", "--target", str(plain)])
        self.assertEqual(_exit_code(result), 0)
        self.assertIn("unsupported", render_text(result))

    def test_plan_apply_produces_receipt_and_exits_zero(self) -> None:
        result = self.run_cli(
            [
                "plan",
                "apply",
                "--bundle",
                str(self.bundle.root),
                "--target",
                self.target_arg(),
            ]
        )
        self.assertEqual(_exit_code(result), 0)
        envelope = cast(dict[str, object], json.loads(render_json(result)))
        state = cast(dict[str, object], envelope["state"])
        self.assertIsInstance(state["receipt"], dict)
        self.assertEqual(self.fixture.run_count(), 0)

    def test_plan_apply_out_file_exclusive(self) -> None:
        parent = Path(self.tmp.name)
        receipt = parent / "receipt.json"
        base = [
            "plan",
            "apply",
            "--bundle",
            str(self.bundle.root),
            "--target",
            self.target_arg(),
            "--out",
            str(receipt),
        ]
        first = self.run_cli(base)
        self.assertEqual(_exit_code(first), 0)
        self.assertTrue(receipt.is_file())
        second = self.run_cli(base)
        # An occupied --out destination is an argument invariant (usage), so
        # the planning family exits 2 before any observation happens.
        self.assertEqual(_exit_code(second), 2)

    def test_all_scaffold_apply_installs_and_exits_one(self) -> None:
        result = self.run_cli(
            ["apply", "--bundle", str(self.bundle.root), "--target", self.target_arg()]
        )
        self.assertEqual(_exit_code(result), 1)
        self.assertTrue(
            (self.fixture.root / ".agentic-template/project.json").is_file()
        )
        self.assertEqual(self.fixture.run_count(), 1)

    def test_restore_retains_existing_readiness_findings(self) -> None:
        applied = self.run_cli(
            ["apply", "--bundle", str(self.bundle.root), "--target", self.target_arg()]
        )
        self.assertEqual(_exit_code(applied), 1)
        restored = self.run_cli(["restore", "--target", self.target_arg()])
        self.assertEqual(_exit_code(restored), 1)
        self.assertIn("BOOTSTRAP_READINESS_BLOCKING", render_text(restored))

    def test_supplied_apply_exits_zero(self) -> None:
        parent = Path(self.tmp.name) / "supplied"
        parent.mkdir()
        supplied = BundleDir(
            parent, all_scaffold=False, record_path=self.fixture.hook_runs
        )
        result = self.run_cli(
            ["apply", "--bundle", str(supplied.root), "--target", self.target_arg()]
        )
        self.assertEqual(_exit_code(result), 0)
        self.assertEqual(self.fixture.run_count(), 1)

    def test_apply_already_installed_refuses(self) -> None:
        _ = self.run_cli(
            ["apply", "--bundle", str(self.bundle.root), "--target", self.target_arg()]
        )
        second = self.run_cli(
            ["apply", "--bundle", str(self.bundle.root), "--target", self.target_arg()]
        )
        self.assertEqual(_exit_code(second), 1)
        self.assertIn("run python3 scripts/validate_repository.py", render_text(second))

    def test_valid_cleanup_apply_removes_declared_paths(self) -> None:
        parent = Path(self.tmp.name) / "clean-valid"
        parent.mkdir()
        template, fixture = _make_fixture(parent, maintenance=True)
        result = execute_command(
            _parse(
                [
                    "apply",
                    "--bundle",
                    str(self.bundle.root),
                    "--target",
                    str(fixture.root),
                ]
            ),
            template_root=str(template.root),
        )
        self.assertEqual(_exit_code(result), 1)  # scaffold slots remain unready
        self.assertFalse((fixture.root / "tests").exists())
        self.assertFalse(
            (fixture.root / ".agentic-template/maintenance-artifacts.json").exists()
        )
        self.assertTrue((fixture.root / ".agentic-template/project.json").is_file())
        self.assertEqual(fixture.run_count(), 1)
        # A completed transaction leaves no stage litter behind.
        for stage_root in (
            fixture.root / ".agentic-template-stage",
            fixture.root / "docs/.agentic-template-stage",
            fixture.root / "scripts/.agentic-template-stage",
        ):
            self.assertFalse(stage_root.exists())

    def test_cleanup_mismatch_and_leave_override(self) -> None:
        parent = Path(self.tmp.name) / "cleanup"
        parent.mkdir()
        template, fixture = _make_fixture(parent, maintenance=True)
        # Damage one declared cleanup path so the inventory no longer matches.
        _ = (fixture.root / "tests/test_script_cores.py").write_text(
            "drift\n", encoding="utf-8"
        )
        refused = execute_command(
            _parse(
                [
                    "apply",
                    "--bundle",
                    str(self.bundle.root),
                    "--target",
                    str(fixture.root),
                ]
            ),
            template_root=str(template.root),
        )
        self.assertEqual(_exit_code(refused), 1)
        self.assertIn("CLEANUP_CONTRACT_INVALID", render_text(refused))
        self.assertIn("tests", render_text(refused))
        self.assertIn("--leave-maintenance-artifacts", render_text(refused))
        self.assertTrue(
            (fixture.root / ".agentic-template/maintenance-artifacts.json").is_file()
        )
        leave = execute_command(
            _parse(
                [
                    "apply",
                    "--bundle",
                    str(self.bundle.root),
                    "--target",
                    str(fixture.root),
                    "--leave-maintenance-artifacts",
                ]
            ),
            template_root=str(template.root),
        )
        self.assertEqual(_exit_code(leave), 1)  # scaffold slots remain unready
        self.assertTrue(
            (fixture.root / ".agentic-template/maintenance-artifacts.json").is_file()
        )
        self.assertTrue((fixture.root / ".agentic-template/project.json").is_file())

    def test_protected_target_refuses(self) -> None:
        parent = Path(self.tmp.name) / "protected"
        parent.mkdir()
        template, fixture = _make_fixture(parent)
        _ = subprocess.run(
            [
                "git",
                "-C",
                str(fixture.root),
                "remote",
                "add",
                "origin",
                "https://github.com/knirski/agentic-template.git",
            ],
            check=True,
            capture_output=True,
        )
        result = execute_command(
            _parse(
                [
                    "apply",
                    "--bundle",
                    str(self.bundle.root),
                    "--target",
                    str(fixture.root),
                ]
            ),
            template_root=str(template.root),
        )
        self.assertEqual(_exit_code(result), 1)

    def test_recover_no_journal_exits_zero_without_hook(self) -> None:
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        self.assertEqual(self.fixture.run_count(), 0)

    def test_recover_stale_pending_discards(self) -> None:
        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        _ = (state_root / "journal.pending").write_text("stale", encoding="utf-8")
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        self.assertFalse((state_root / "journal.pending").exists())

    def test_recover_invalid_journal_exits_two(self) -> None:
        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        _ = (state_root / "journal.json").write_text("not json", encoding="utf-8")
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 2)
        self.assertTrue((state_root / "journal.json").is_file())

    def test_recover_target_mismatch_exits_one(self) -> None:
        from scripts.bootstrap.identity import target_identity

        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        other = target_identity(b"/somewhere-else", device=1, inode=2)
        envelope = JournalEnvelope(
            operation="initial",
            target=JournalTarget.from_identity(other),
            phase=JournalPhase.PLANNED,
            transaction_id=new_transaction_id(),
            preparations=(),
        )
        _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 1)
        self.assertTrue((state_root / "journal.json").is_file())

    def test_planned_recovery_cleans_preparations(self) -> None:
        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        planned = self.run_cli(
            [
                "plan",
                "apply",
                "--bundle",
                str(self.bundle.root),
                "--target",
                self.target_arg(),
            ]
        )
        self.assertEqual(_exit_code(planned), 0)
        receipt = cast(dict[str, object], planned.state_document)["receipt"]
        identity = PreparationIdentity(
            transaction_id="ab" * 32,
            operation_index=0,
            role=PreparationRole.STAGE,
            ownership_token_sha256="cd" * 32,
            expected_kind="file",
            expected_raw_sha256="ef" * 32,
            expected_mode=PosixMode(0o644),
        )
        envelope = JournalEnvelope(
            operation="initial",
            target=JournalTarget.from_identity(_target_identity(self.fixture.root)),
            phase=JournalPhase.PLANNED,
            transaction_id="ab" * 32,
            preparations=(identity,),
            receipt=cast(PlanReceipt, receipt),
        )
        _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        self.assertFalse((state_root / "journal.json").exists())

    def test_sealed_recovery_cleans_surviving_stages(self) -> None:
        # A crash after install but before cleanup leaves a SEALED journal and
        # marked stage directories.  Recovery must finish the forward cleanup
        # using the journaled identities (original ownership-token hashes),
        # never freshly minted tokens.
        state_root = self.fixture.root / ".git/agentic-template"
        state_root.mkdir()
        planned = self.run_cli(
            [
                "plan",
                "apply",
                "--bundle",
                str(self.bundle.root),
                "--target",
                self.target_arg(),
            ]
        )
        self.assertEqual(_exit_code(planned), 0)
        receipt = cast(dict[str, object], planned.state_document)["receipt"]
        installed = self.run_cli(
            [
                "apply",
                "--bundle",
                str(self.bundle.root),
                "--target",
                self.target_arg(),
            ]
        )
        self.assertEqual(_exit_code(installed), 1)
        receipt = cast(dict[str, object], planned.state_document)["receipt"]
        match reconstruct_plan(
            cast(PlanReceipt, receipt), target=_target_identity(self.fixture.root)
        ):
            case Err(error):
                self.fail(f"receipt reconstruction failed: {error}")
            case Ok(plan):
                pass
        transaction_id = "ab" * 32
        token = bytes.fromhex("cd" * 32)
        specs = derive_preparation_specs(plan)
        preparations = derive_preparations(plan, transaction_id, (token,) * len(specs))

        def is_root_file_stage(spec: PreparationSpec) -> bool:
            if spec.role is not PreparationRole.STAGE or spec.expected_kind != "file":
                return False
            operation = plan.ordered_operations[spec.operation_index]
            match operation:
                case CreateFileOperation(path=path) | ReplaceFileOperation(path=path):
                    return "/" not in path.value
                case _:
                    return False

        stage_spec = next(spec for spec in specs if is_root_file_stage(spec))
        stage_identity = next(
            identity
            for identity in preparations
            if identity.role is PreparationRole.STAGE
            and identity.operation_index == stage_spec.operation_index
        )
        envelope = JournalEnvelope(
            operation="initial",
            target=JournalTarget.from_identity(_target_identity(self.fixture.root)),
            phase=JournalPhase.SEALED,
            transaction_id=transaction_id,
            preparations=preparations,
            receipt=cast(PlanReceipt, receipt),
        )
        _ = (state_root / "journal.json").write_bytes(encode_journal(envelope))
        stage_root = self.fixture.root / ".agentic-template-stage"
        stage_dir = stage_root / transaction_id / str(stage_spec.operation_index)
        stage_dir.mkdir(parents=True)
        marker = canonical_json(
            {
                "transaction_id": transaction_id,
                "operation_index": stage_identity.operation_index,
                "role": stage_identity.role.value,
                "token": token.hex(),
            }
        )
        _ = (stage_dir / "marker").write_bytes(marker)
        result = self.run_cli(["recover", "--target", self.target_arg()])
        self.assertEqual(_exit_code(result), 0)
        self.assertFalse((state_root / "journal.json").exists())
        self.assertFalse(stage_dir.exists())
        self.assertFalse(stage_root.exists())

    def test_text_json_parity(self) -> None:
        for argv in (
            ["status", "--target", self.target_arg()],
            [
                "plan",
                "apply",
                "--bundle",
                str(self.bundle.root),
                "--target",
                self.target_arg(),
            ],
            ["recover", "--target", self.target_arg()],
        ):
            with self.subTest(argv=argv):
                parsed = _parse(argv)
                result = execute_command(parsed, template_root=str(self.template.root))
                text = render_text(result)
                envelope = cast(dict[str, object], json.loads(render_json(result)))
                self.assertEqual(envelope["exit_code"], _exit_code(result))
                self.assertIn(envelope["outcome_class"], text)

    def test_main_json_emits_single_envelope(self) -> None:
        code = main(["--format", "json", "status", "--target", self.target_arg()])
        self.assertEqual(code, 0)


class EntryPointTests(unittest.TestCase):
    """The ``scripts/bootstrap_project.py`` adapter: process-level exit contract.

    ``runpy`` executes the real entry file with ``__name__ == "__main__"`` in
    this process so the guarded block and its ``SystemExit`` are exercised
    (and measured by coverage), with the child argv staged on ``sys.argv``.
    """

    def _run(self, *argv: str) -> int:
        import runpy

        original = sys.argv
        sys.argv = ["bootstrap_project.py", *argv]
        try:
            with self.assertRaises(SystemExit) as context:
                _ = runpy.run_path(
                    str(ROOT / "scripts/bootstrap_project.py"), run_name="__main__"
                )
        finally:
            sys.argv = original
        code = context.exception.code
        assert isinstance(code, int)
        return code

    def test_help_exits_zero(self) -> None:
        self.assertEqual(self._run("--help"), 0)

    def test_usage_error_exits_two(self) -> None:
        self.assertEqual(self._run("--bogus"), 2)


def _target_identity(root: Path) -> TargetIdentity:
    from scripts.bootstrap.identity import target_identity

    info = os.stat(root)
    return target_identity(
        os.fsencode(str(root)), device=info.st_dev, inode=info.st_ino
    )


if __name__ == "__main__":
    _ = unittest.main()
