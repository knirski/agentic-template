"""The release-time cleanup-inventory regeneration wrapper."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

import scripts.regenerate_cleanup_inventory as regenerator

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / ".rygor" / "maintenance-artifacts.json"


def test_regeneration_is_idempotent_from_any_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Running the writer from any directory leaves a current tree alone.

    The invocation directory is deliberately not the repository root: the
    script must anchor both the inventory it rewrites and the git tree the
    fixture of truth hashes, or a release hook running elsewhere would hash
    the wrong tree.
    """
    monkeypatch.chdir(tmp_path)
    before = INVENTORY.read_bytes()
    assert regenerator.main() == 0
    assert INVENTORY.read_bytes() == before


def test_trees_without_the_machinery_skip_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Generated projects lack tests/ and the inventory; they must not fail."""
    monkeypatch.setattr(regenerator, "INVENTORY_PATH", tmp_path / "absent.json")
    assert regenerator.main() == 0
    assert "machinery absent" in capsys.readouterr().err


def test_main_guard_regenerates_from_a_foreign_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The release hook entrypoint anchors itself and exits zero."""
    monkeypatch.chdir(tmp_path)
    before = INVENTORY.read_bytes()
    with pytest.raises(SystemExit) as exc:
        _ = runpy.run_path(str(regenerator.__file__), run_name="__main__")
    assert exc.value.code == 0
    assert INVENTORY.read_bytes() == before
