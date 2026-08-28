# Test Troubleshooting

## Maintenance-artifacts.json Staleness

### Symptom

Multiple unrelated tests fail with one of two messages:

```
BOOTSTRAP_CONTRACT_CLEANUP_CONTRACT_INVALID: tests: Cleanup contract invalid
```

or:

```
maintenance-artifacts.json is stale; regenerate it from the tracked source
```

The failing tests are typically spread across `test_bootstrap_lifecycle.py`, `test_source_bootstrap.py`, `test_github_template_readiness.py`, and `test_regenerate_cleanup_inventory.py`.

### Root Cause

`.rygor/maintenance-artifacts.json` records SHA256 hashes of every file and directory listed in `CLEANUP_PATHS`. When any tracked file under a cleanup path changes — even a whitespace-only JSON reformatting — the directory digest no longer matches the committed inventory.

The most common trigger is editing `docs/specs/` files (especially `plan.json`) because `docs/specs` is a cleanup path. A tool that reformats JSON (e.g., `json.dump(indent=2)`) will silently change the file bytes without changing semantic content.

During `bootstrap_project.py apply`, the observation pipeline recomputes the directory hashes from the snapshot, detects the mismatch, and emits `CleanupContractMismatch`. Any test that calls `_activate_source()` or `_activate()` will then fail.

### Fix

Regenerate the inventory from the current working tree:

```bash
uv run python scripts/regenerate_cleanup_inventory.py
```

Then commit the updated `.rygor/maintenance-artifacts.json` alongside the source change.

### Prevention

After modifying any file under a cleanup path, always regenerate before running the full suite:

```bash
uv run python scripts/regenerate_cleanup_inventory.py
uv run pytest -q
```

The canonical list of cleanup paths is `CLEANUP_PATHS` in `tests/fixtures.py`.

### Related Files

- `.rygor/maintenance-artifacts.json` — the committed inventory
- `scripts/regenerate_cleanup_inventory.py` — regeneration script
- `tests/fixtures.py` — defines `CLEANUP_PATHS` and `expected_cleanup_inventory()`
- `tests/test_github_template_readiness.py` — `test_cleanup_inventory_matches_the_tracked_source` validates the inventory is current
