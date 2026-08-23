"""The release-time cleanup-inventory regeneration wrapper."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

import scripts.regenerate_cleanup_inventory as regenerator

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / ".agentic-template" / "maintenance-artifacts.json"


def test_regeneration_is_idempotent_against_the_tracked_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running the writer on a current tree leaves the committed bytes alone."""
    monkeypatch.chdir(REPO_ROOT)
    before = INVENTORY.read_bytes()
    assert regenerator.main() == 0
    assert INVENTORY.read_bytes() == before


def test_trees_without_the_machinery_skip_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Generated projects lack tests/ and the inventory; they must not fail.

    Exercised through the real ``__main__`` guard so the release hook's exact
    entrypoint -- not just the function -- is what the suites pin.
    """
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _ = runpy.run_path(str(regenerator.__file__), run_name="__main__")
    assert exc.value.code == 0
    assert "machinery absent" in capsys.readouterr().err
