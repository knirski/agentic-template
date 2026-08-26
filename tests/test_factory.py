"""Fidelity pins binding the factory engine to today's baseline constructions.

Every assertion compares factory output against a live construction from the
pre-factory suite layers (``ScaffoldFixture``/``TemplatePackage``, the
readiness ``_snapshot`` flow, ``fixtures.write_bundle``); nothing is pinned to
hardcoded digests.
"""

from __future__ import annotations

import hashlib
import os
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
    write_answer_bundle,
)
from tests.fixtures import (
    SCAFFOLD_CONTRIBUTING,
    SCAFFOLD_SECURITY,
    copy_tracked,
    run,
    scaffold_hook,
    tracked_files,
    write_bundle,
)
from tests.test_bootstrap_cli import ScaffoldFixture, TemplatePackage


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


def test_synthetic_project_matches_cli_baseline(tmp_path: Path) -> None:
    """build_snapshot_project(synthetic) equals ScaffoldFixture construction."""
    baseline_parent = tmp_path / "baseline"
    baseline_parent.mkdir()
    baseline = ScaffoldFixture(baseline_parent, TemplatePackage(baseline_parent))

    parent = tmp_path / "factory"
    parent.mkdir()
    project = build_snapshot_project(
        parent,
        SnapshotConfig(template="synthetic"),
        pristine=_pristine(tmp_path),
    )

    records = (baseline.hook_runs, project.hook_runs)
    _assert_same_tree(
        _tree(baseline.root, records),
        _tree(project.root, records),
        _untracked_source_extras(),
    )
    assert project.template_root is None or project.template_root.is_dir()

    assert _git_text(project.root, "rev-list", "--count", "HEAD") == "1"
    assert _git_text(project.root, "symbolic-ref", "--short", "HEAD") == "main"

    assert project.run_count() == 0
    assert baseline.run_count() == 0
    for root in (project.root, baseline.root):
        executed = run([str(root / "scripts/validate-project")])
        assert executed.returncode == 0, executed.stderr
    assert project.run_count() == 1
    assert baseline.run_count() == 1


def test_live_project_matches_readiness_baseline(tmp_path: Path) -> None:
    """build_snapshot_project(live) equals the GitHubBootstrapTests._snapshot flow."""
    baseline_parent = tmp_path / "baseline"
    baseline_parent.mkdir()
    baseline_root = baseline_parent / "snap"
    copy_tracked(factory.REPO_ROOT, baseline_root)
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


@pytest.mark.parametrize(
    ("supplied", "capabilities", "settings"),
    (
        (False, None, None),
        (True, None, None),
        (True, ("nix", "cachix-publish"), {"cachix-publish": {"cache_name": "x"}}),
    ),
    ids=("all-scaffold", "supplied-portable", "supplied-custom-profile"),
)
def test_answer_bundle_matches_canonical_writer(
    tmp_path: Path,
    supplied: bool,
    capabilities: tuple[str, ...] | None,
    settings: dict[str, dict[str, str | bool]] | None,
) -> None:
    canonical_record = tmp_path / "record-canonical"
    candidate_record = tmp_path / "record-candidate"
    canonical = write_bundle(
        tmp_path,
        supplied=supplied,
        record=canonical_record,
        name="canonical",
        capabilities=capabilities,
        capability_settings=settings,
    )
    candidate = write_answer_bundle(
        tmp_path,
        supplied=supplied,
        record=candidate_record,
        name="candidate",
        capabilities=capabilities,
        capability_settings=settings,
    )
    _assert_same_tree(
        _tree(canonical, (canonical_record, candidate_record)),
        _tree(candidate, (canonical_record, candidate_record)),
    )
    if supplied:
        hook = candidate / "content/validate-project"
        assert stat.S_IMODE(hook.stat().st_mode) & 0o111 == 0o111


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
