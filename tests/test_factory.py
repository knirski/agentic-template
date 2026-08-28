"""Fidelity pins binding the factory engine to today's baseline constructions.

Every assertion compares factory output against a live construction from the
pre-factory suite layers (``ScaffoldFixture``/``TemplatePackage``, the
readiness ``_snapshot`` flow, the canonical answer-bundle document); nothing
is pinned to hardcoded digests.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import cast

import pytest

from tests import factory
from tests.factory import (
    SnapshotConfig,
    build_pristine_snapshot,
    build_snapshot_project,
    pristine_snapshot,
    seed_repo,
)
from tests.fixtures import (
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    run,
    scaffold_hook,
    tracked_files,
)


def _digest_entry(path: Path, records: tuple[Path, ...]) -> tuple[int, str]:
    mode = stat.S_IMODE(path.lstat().st_mode)
    if path.is_symlink():
        return mode, "symlink:" + os.fspath(path.readlink())
    if path.is_dir():
        return mode, "dir"
    data = path.read_bytes()
    for record in records:
        data = data.replace(str(record).encode(), b"<hook-runs>")
    return mode, hashlib.sha256(data).hexdigest()


def _tree(root: Path, records: tuple[Path, ...] = ()) -> dict[str, tuple[int, str]]:
    entries: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        entries[relative] = _digest_entry(path, records)
    return entries


def _assert_same_tree(
    baseline: dict[str, tuple[int, str]],
    candidate: dict[str, tuple[int, str]],
    tolerated_extra_sources: frozenset[str] | None = None,
) -> None:
    missing = sorted(set(baseline) - set(candidate))
    extra = sorted(
        set(candidate) - set(baseline) - (tolerated_extra_sources or frozenset())
    )
    assert not missing, f"factory omitted baseline paths: {missing}"
    assert not extra, f"factory added unexpected paths: {extra}"
    diverged = [
        relative for relative, entry in baseline.items() if candidate[relative] != entry
    ]
    assert not diverged, f"factory diverges from baseline at: {diverged}"


def _untracked_source_extras() -> frozenset[str]:
    """Untracked non-ignored source files the pristine set adds over ls-files."""
    listed = subprocess.run(
        ["git", "-C", str(factory.REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    plain_tracked = {entry for entry in listed.split("\0") if entry}
    return frozenset(set(tracked_files(factory.REPO_ROOT)) - plain_tracked)


def _pristine(tmp_path: Path) -> Path:
    return build_pristine_snapshot(root=factory.REPO_ROOT, parent=tmp_path)


def _git_text(root: Path, *args: str) -> str:
    result = run(["git", *args], cwd=root)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


_BASELINE_TEMPLATE_FILES = (
    ("README.md", "# Placeholder\n\n<!-- rygor:placeholder:readme -->\n", 0o644),
    ("docs/prd.md", "# Product\n\n<!-- rygor:placeholder:prd -->\n", 0o644),
    ("SECURITY.md", "# Security\n\n<!-- rygor:placeholder:security -->\n", 0o644),
    (
        "CONTRIBUTING.md",
        "# Contributing\n\n"
        + "<!-- rygor:placeholder:contributing -->\n\n"
        + "## Running tests\n\n"
        + "Run the test suite serially with `uv run pytest`. For faster feedback on a multi-core machine,\n"
        + "run `uv run pytest -n auto --dist=worksteal` to distribute tests across available workers.\n",
        0o644,
    ),
    (
        "scripts/validate-project",
        "#!/bin/sh\n# rygor:unconfigured:validate-project\necho unconfigured\nexit 0\n",
        0o755,
    ),
    ("LICENSE", "Apache-2.0\n", 0o644),
    ("NOTICE.md", "Notice.\n", 0o644),
    ("LICENSES/Apache-2.0.txt", "Apache text.\n", 0o644),
    ("source-contract.txt", "template source.\n", 0o644),
)


def _baseline_synthetic_fixture(parent: Path) -> tuple[Path, Path]:
    """Independent replication of the pre-factory CLI fixture construction."""
    import json

    from scripts.bootstrap.paths import RepoPath
    from scripts.bootstrap.scaffold import (
        PROJECT_VALIDATION_SCAFFOLD,
        SCAFFOLD_SOURCE_PATHS,
    )

    template = parent / "template"
    template.mkdir()
    for relative, content, mode in _BASELINE_TEMPLATE_FILES:
        path = template / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8")
        path.chmod(mode)
    project_validation = template / ".github/workflows/project-validation.yml"
    project_validation.parent.mkdir(parents=True, exist_ok=True)
    _ = project_validation.write_bytes(PROJECT_VALIDATION_SCAFFOLD)
    project_validation.chmod(0o644)
    for installed, source in SCAFFOLD_SOURCE_PATHS.items():
        source_path = template / source.value
        source_path.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(template / installed.value, source_path)
    ownership = template / ".rygor/source-ownership.json"
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

    root = parent / "project"
    root.mkdir()
    listed = subprocess.run(
        ["git", "-C", str(factory.REPO_ROOT), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout.decode()
    hook_runs = parent / "hook-runs"
    _ = hook_runs.write_text("", encoding="utf-8")
    hook_text = (
        "#!/bin/sh\n# rygor:unconfigured:validate-project\necho run >> "
        + str(hook_runs)
        + "\nexit 0\n"
    )
    for relative in sorted({entry for entry in listed.split("\0") if entry}):
        source = factory.REPO_ROOT / relative
        if not source.is_file():
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, target)
    _ = shutil.copy2(
        ownership,
        root / ".rygor/source-ownership.json",
    )
    inventory = root / ".rygor/maintenance-artifacts.json"
    if inventory.is_file():
        _ = inventory.unlink()
    hook = template / "scripts/validate-project"
    _ = hook.write_text(hook_text, encoding="utf-8")
    hook.chmod(0o755)
    mirror = (
        template / SCAFFOLD_SOURCE_PATHS[RepoPath("scripts/validate-project")].value
    )
    _ = shutil.copy2(hook, mirror)
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
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(template / relative, target)
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
        factory.git(*args, cwd=root)
    return root, hook_runs


def test_synthetic_project_matches_cli_baseline(tmp_path: Path) -> None:
    """build_snapshot_project(synthetic) equals the pre-factory CLI construction."""
    baseline_parent = tmp_path / "baseline"
    baseline_parent.mkdir()
    baseline_root, baseline_record = _baseline_synthetic_fixture(baseline_parent)

    parent = tmp_path / "factory"
    parent.mkdir()
    project = build_snapshot_project(
        parent,
        SnapshotConfig(template="synthetic"),
        pristine=_pristine(tmp_path),
    )

    records = (baseline_record, project.hook_runs)
    _assert_same_tree(
        _tree(baseline_root, records),
        _tree(project.root, records),
        _untracked_source_extras(),
    )
    assert project.template_root is None or project.template_root.is_dir()

    assert _git_text(project.root, "rev-list", "--count", "HEAD") == "1"
    assert _git_text(project.root, "symbolic-ref", "--short", "HEAD") == "main"

    def run_count(record: Path) -> int:
        return len(record.read_text(encoding="utf-8").splitlines())

    assert run_count(project.hook_runs) == 0
    assert run_count(baseline_record) == 0
    for root in (project.root, baseline_root):
        executed = run([str(root / "scripts/validate-project")])
        assert executed.returncode == 0, executed.stderr
    assert run_count(project.hook_runs) == 1
    assert run_count(baseline_record) == 1


def test_live_project_matches_readiness_baseline(tmp_path: Path) -> None:
    """build_snapshot_project(live) equals the GitHubBootstrapTests._snapshot flow."""
    baseline_parent = tmp_path / "baseline"
    baseline_parent.mkdir()
    baseline_root = baseline_parent / "snap"
    baseline_root.mkdir()
    for relative in tracked_files(factory.REPO_ROOT):
        source = factory.REPO_ROOT / relative
        if not source.is_file():
            continue
        destination = baseline_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = shutil.copy2(source, destination)
    record = baseline_parent / "snap-hook-runs"
    _ = record.write_text("", encoding="utf-8")
    hook = baseline_root / "scripts/validate-project"
    _ = hook.write_text(scaffold_hook(record), encoding="utf-8")
    hook.chmod(0o755)
    _ = (
        baseline_root / "scripts/bootstrap/fragments/scaffolds/validate-project"
    ).write_text(scaffold_hook(record), encoding="utf-8")
    _ = (baseline_root / "CONTRIBUTING.md").write_text(
        SCAFFOLD_CONTRIBUTING, encoding="utf-8"
    )
    _ = (baseline_root / "SECURITY.md").write_text(SCAFFOLD_SECURITY, encoding="utf-8")
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
        factory.git(*args, cwd=baseline_root)

    parent = tmp_path / "factory"
    parent.mkdir()
    project = build_snapshot_project(
        parent, SnapshotConfig(), pristine=_pristine(tmp_path)
    )

    records = (record, project.hook_runs)
    _assert_same_tree(
        _tree(baseline_root, records),
        _tree(project.root, records),
    )


def test_seed_repo_builds_clean_committed_worktree(tmp_path: Path) -> None:
    root = seed_repo(
        tmp_path,
        {
            "README.md": "# Seed\n",
            "docs/nested/intro.md": "Intro\n",
            "scripts/run.sh": b"#!/bin/sh\nexit 0\n",
        },
    )
    assert (root / "README.md").read_text(encoding="utf-8") == "# Seed\n"
    assert (root / "docs/nested/intro.md").read_text(encoding="utf-8") == "Intro\n"
    assert (root / "scripts/run.sh").read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert _git_text(root, "status", "--porcelain") == ""
    assert _git_text(root, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git_text(root, "rev-list", "--count", "HEAD") == "1"


def test_template_dispatch_rejects_unknown_source(tmp_path: Path) -> None:
    template = cast(factory.TemplateSource, cast(object, "unknown"))
    config = SnapshotConfig(template=template)
    with pytest.raises(AssertionError):
        _ = build_snapshot_project(
            tmp_path / "out", config, pristine=_pristine(tmp_path)
        )


def test_pristine_snapshot_cache_returns_identical_path() -> None:
    first = pristine_snapshot()
    second = pristine_snapshot()
    assert first == second
    assert first.is_dir()
