"""The release-time cleanup-inventory regeneration wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "regenerate_cleanup_inventory.py"
INVENTORY = REPO_ROOT / ".agentic-template" / "maintenance-artifacts.json"


def test_regeneration_is_idempotent_against_the_tracked_source() -> None:
    """Running the writer on a current tree leaves the committed bytes alone."""
    before = INVENTORY.read_bytes()
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert INVENTORY.read_bytes() == before


def test_trees_without_the_machinery_skip_cleanly(tmp_path: Path) -> None:
    """Generated projects lack tests/ and the inventory; they must not fail."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "machinery absent" in result.stderr
