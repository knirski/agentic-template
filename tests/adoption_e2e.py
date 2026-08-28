"""Adoption end-to-end helpers for the journaled adoption suites.

Shared by the transaction, recovery, and crash-stateful adoption suites so
the three files do not re-define the target and bundle builders, the whole
-tree capture, or the crash harness with silent drift.  Only the adoption
suites import this module; the shared fixture modules import neither it nor
each other at module level.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import cast
from unittest.mock import patch

from scripts.bootstrap import transaction_machine
from scripts.bootstrap.planner import DirectoryOperation, FileOperation
from scripts.bootstrap.presentation import CommandResult
from scripts.bootstrap.result import Err, Ok, Result
from scripts.bootstrap.transaction import (
    CompiledTransaction,
    EffectError,
    ObservedPathState,
)
from scripts.bootstrap.values import JournalPhase
from tests.git_config import deterministic_git_environment


def run(
    command: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=deterministic_git_environment(env),
        text=True,
        capture_output=True,
        check=False,
    )


ADOPTER_README = (
    "# Adopter Product\n\n"
    "## Setup\n\n"
    "Install the adopter toolchain.\n\n"
    "## Validation\n\n"
    "Run `uv run --python 3.14 scripts/validate_repository.py`.\n"
)
ADOPTER_NOTES = "adopter notes\n"


def run_cli(argv: list[str]) -> CommandResult:
    """Execute one parsed bootstrap command in-process on the repo template."""

    from scripts.bootstrap.cli import execute_command, parse_argv
    from tests.factory import REPO_ROOT

    match parse_argv(argv):
        case Ok(parsed) if not isinstance(parsed, str):
            return execute_command(parsed, template_root=str(REPO_ROOT))
        case Ok(_) | Err(_):
            raise AssertionError(f"parse failed: {argv!r}")


def cli_exit_code(result: CommandResult) -> int:
    """Map one command result through the family exit-code taxonomy."""

    from scripts.bootstrap.presentation import (
        _family_exit_code,  # pyright: ignore[reportPrivateUsage]  deliberate private-helper unit test
    )

    return _family_exit_code(result.command, result.outcome)


def adoption_target(parent: Path, **files: str) -> Path:
    """Create one committed manifest-free, non-bare Git working tree."""

    from tests.factory import seed_repo

    parent.mkdir(parents=True, exist_ok=True)
    return seed_repo(
        parent,
        {"README.md": ADOPTER_README, "notes.txt": ADOPTER_NOTES, **files},
        name="adoptee",
    )


def empty_adoption_target(parent: Path, *, name: str = "adoptee") -> Path:
    """Create one manifest-free, non-bare Git working tree with no files."""

    root = parent / name
    root.mkdir(parents=True)
    _ = run(["git", "init", "-q", "--initial-branch=main"], cwd=root)
    committed = run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=root,
    )
    assert committed.returncode == 0
    return root


def adoption_bundle(
    parent: Path,
    record: Path,
    *,
    collisions: dict[str, str] | None = None,
    hook_status: int = 0,
    name: str = "bundle",
) -> Path:
    """Write one adoption answer bundle with optional collision declarations."""

    from tests.factory import write_answer_bundle

    parent.mkdir(parents=True, exist_ok=True)
    bundle = write_answer_bundle(parent, supplied=True, record=record, name=name)
    if collisions:
        document = cast(
            "dict[str, object]",
            json.loads((bundle / "bootstrap.json").read_text(encoding="utf-8")),
        )
        document["collisions"] = dict(collisions)
        _ = (bundle / "bootstrap.json").write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )
    if hook_status != 0:
        hook = bundle / "content/validate-project"
        _ = hook.write_text(
            f"#!/bin/sh\necho run >> {record}\nexit {hook_status}\n", encoding="utf-8"
        )
        hook.chmod(0o755)
    return bundle


def capture_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    """Capture every regular file (relative path, bytes, mode) below ``root``.

    Administrative transaction state is excluded: ``.git`` because it holds
    the state root, and ``.rygor-stage`` because stage/rollback litter is
    transaction-internal, not project state.
    """

    state: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if relative == ".rygor-stage" or relative.startswith(".rygor-stage/"):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        state[relative] = (path.read_bytes(), info.st_mode & 0o777)
    return state


class TransactionCrash(BaseException):
    """Raised by the crash harness to simulate process death mid-transaction."""


@contextlib.contextmanager
def crashing_transaction(
    *, apply_at: int | None = None, seal_clean: bool = False
) -> Generator[dict[str, bool]]:
    """Simulate process death inside the real transaction machine.

    ``apply_at`` aborts on entering the Nth apply effect (operations 1 through
    N-1 stay installed behind a MUTATING journal); ``seal_clean`` aborts on the
    first forward cleanup effect behind a SEALED journal.  The harness releases
    the held lock and closes the state-root descriptor before raising, which
    matches what process death leaves on disk.
    """

    from scripts.bootstrap.locking import release_lock

    fired = {"apply": False, "clean": False}
    counters = {"apply": 0}
    real_apply = transaction_machine._execute_apply_one  # pyright: ignore[reportPrivateUsage]  deliberate crash harness seam
    real_clean = transaction_machine._execute_clean_one  # pyright: ignore[reportPrivateUsage]  deliberate crash harness seam

    def _die(resources: transaction_machine.TransactionResources) -> None:
        if resources.lock is not None:
            release_lock(resources.lock)
            resources.lock = None
        if resources.state_root_fd is not None:
            os.close(resources.state_root_fd)
            resources.state_root_fd = None

    def crash_apply(
        operation: FileOperation | DirectoryOperation,
        compiled: CompiledTransaction,
        resources: transaction_machine.TransactionResources,
    ) -> Result[ObservedPathState, EffectError]:
        if apply_at is not None:
            counters["apply"] += 1
            if counters["apply"] >= apply_at and not fired["apply"]:
                fired["apply"] = True
                _die(resources)
                raise TransactionCrash(f"apply #{apply_at}")
        return real_apply(operation, compiled, resources)

    def crash_clean(
        compiled: CompiledTransaction,
        phase: JournalPhase,
        index: int,
        resources: transaction_machine.TransactionResources,
    ) -> Result[None, EffectError]:
        if seal_clean and phase is JournalPhase.SEALED and not fired["clean"]:
            fired["clean"] = True
            _die(resources)
            raise TransactionCrash("sealed cleanup")
        return real_clean(compiled, phase, index, resources)

    with (
        patch.object(transaction_machine, "_execute_apply_one", crash_apply),
        patch.object(transaction_machine, "_execute_clean_one", crash_clean),
    ):
        yield fired
