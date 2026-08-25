# Test Suite Speedup: Deterministic Git Env, Parallel Execution, Fixture Factory, Native Pytest

## Problem

The pytest suite (1404 tests, ~45s serial wall time) has four problems:

1. **A proven flake.** `CliFamilyTests` teardown intermittently fails with
   `OSError: [Errno 39] Directory not empty` on fixture `.git` directories
   (~7% isolated, ~25% per file run). Root cause established empirically: a
   detached git auto-maintenance child process survives `setUp`'s synchronous
   `subprocess.run` calls and writes into fixture `.git` directories during
   teardown. Evidence: an audit-hook probe showed zero in-process writes during
   teardown; a flow probe failed 15/80 iterations at baseline versus 0/80 with
   git auto-maintenance disabled (`gc.auto=0`, `gc.autoDetach=false`,
   `maintenance.auto=false`); every failure was removable 50ms later, with
   random single subtrees left over (`objects/info/packs`, `hooks/*`, `info`).

2. **Serial-only execution.** `pytest-xdist` is absent; CI runs one process on
   multi-core runners. The 15 slowest tests (~22s of 45s) are subprocess-heavy
   end-to-end suites that parallelize trivially.

3. **Duplicated fixture construction.** Three near-identical implementations of
   "copy tracked source → overlay scaffold slots → seed-commit a git repo"
   exist (`ScaffoldFixture` in `test_bootstrap_cli.py`, `_snapshot()` in
   `test_github_template_readiness.py`, `_activate_source()` in
   `test_source_bootstrap.py`), plus four bespoke copytree ignore lists and
   scattered inline `git init/add` sites in observation/recovery/state-root
   suites. The shared helper docstrings already complain about copy-drift risk.

4. **Pre-pytest test idiom.** All suites are `unittest.TestCase` classes with
   manual `setUp`/`tearDown` lifecycles, `self.assert*` calls, and `subTest`
   loops — forgoing pytest's fixture injection, parametrization reporting,
   plain asserts, and richer failure output. This is also the root cause of the
   bridge machinery any fixture architecture otherwise needs.

Who has the problem: every contributor running tests locally (slow feedback,
flaky red) and CI (wall time, flaky reruns).

## Scope

**In scope**

- Session-wide deterministic git environment for test-spawned subprocesses
  (`tests/conftest.py` autouse fixture).
- `pytest-xdist` dependency; `-n auto` in CI; documented local usage.
- New `tests/factory.py`: pristine-source snapshot, project/seed-repo/bundle
  builders replacing all duplicated fixture construction.
- Migration of suites onto the factory, first via direct builder calls
  (validated against every existing assertion), then to native pytest.
- Full `unittest.TestCase` → plain-pytest conversion as the **concluding
  phase** of this effort: plain functions/modules, fixture requests, plain
  asserts, `subTest` → `parametrize`.
- Staged delivery: eight independently green checkpoints; stage 4 is the
  fallback boundary; the native-pytest phase is terminal.

**Out of scope**

- Any change under `scripts/` (production code untouched).
- `tests/test_copier_bootstrap.py` (standalone script, not pytest-collected);
  the collected `test_copier.py` smoke suite keeps its local copytree.
- Coverage-lane restructuring; mutmut configuration semantics (its pinned
  files keep their paths and the `-k` target keeps its test name).
- Generated-project tooling (`tests/` is removed by snapshot cleanup, so the
  conftest never ships to adopters).

## User Stories

- **US-1 (must): Deterministic git environment.** As a contributor, when I run
  the suite, fixture git repos never produce detached-maintenance writes during
  teardown.
  - Given any suite run, when fixtures create git repos, then every git
    subprocess inherits `gc.auto=0`, `gc.autoDetach=false`,
    `maintenance.auto=false`, and nulled global/system git config.
  - Accept: 40 consecutive runs of
    `tests/test_bootstrap_cli.py::CliFamilyTests::test_text_json_parity`
    pass; 10 consecutive full-file runs pass.

- **US-2 (must): Parallel execution.** As a contributor, I can run
  `uv run pytest -n auto`; CI does the same.
  - Accept: full suite green under `-n auto`; `.github/workflows/template-ci.yml`
    pytest line includes `-n auto`; coverage report still produced (worker-
    combined); CONTRIBUTING.md documents local usage.

- **US-3 (must): One fixture factory.** As a maintainer, every suite that
  builds project directories consumes `tests/factory.py`.
  - Accept: no inline fixture-repo construction outside `factory.py`/conftest;
    `copy_tracked` deleted; all suites green.

- **US-4 (must): Pay only for what you use.** Tests that never request
  fixtures never trigger builds; requesting tests get fresh per-test projects.
  - Accept: verified structurally once suites are native (a test not naming a
    fixture cannot invoke it); single-file wall time does not regress.

- **US-5 (should): Fast, faithful materialization.** Per-fixture projects come
  from stdlib `shutil.copytree` off a session pristine snapshot, preserving
  bytes and modes. The fidelity test pins the full selection contract: the
  enumerated file set (tracked plus non-ignored untracked, dangling-symlink
  entries omitted) and byte/mode equality against today's construction.
  - Accept: focused fidelity test compares byte digests and permission bits
    against today's construction output on this machine.

- **US-6 (must): Native pytest suite.** After the final phase, suites are plain
  pytest modules/functions using fixture injection, plain asserts, and
  `parametrize` (each former `subTest` case reported individually).
  - Accept: no `unittest.TestCase` subclasses remain under `tests/`;
    `rg 'unittest'` finds nothing but this spec; collection covers the same
    behaviors (former subtests appear as distinct parametrized ids); mutmut's
    pinned files collect cleanly and the `-k` filter target keeps its name.

- **US-7 (must): Staged delivery with green checkpoints.**

| # | Stage | End state |
|---|---|---|
| 1 | conftest deterministic-git-env autouse fixture | US-1 |
| 2 | xdist dependency + CI `-n auto` + CONTRIBUTING note | US-2 |
| 3 | `tests/factory.py` engine + `tests/test_factory.py` | suite untouched, green |
| 4 | All shape A–C suites on direct builder calls | US-3, US-5 |
| 5 | Dead-code removal (`copy_tracked`, eager paths, duplicate builders) + full serial validation | clean baseline |
| 6 | Native conftest fixture graph + one exemplar suite converted end-to-end (class → functions + fixture requests) | graph exercised immediately, no dead window; conversion pattern established |
| 7 | Remaining suites converted batch-by-batch: `TestCase` → functions, `assert*` → asserts, `subTest` → `parametrize`, `setUp`/`tearDown` → fixtures | US-4, US-6 |
| 8 | Final validation: ruff, basedpyright, collection comparison, mutmut pinned-file collect + targeted mutant sample, coverage flags intact | all criteria |

Stage 4 is the explicit fallback boundary: stopping there still delivers the
flake fix, parallelism, deduplication, and speedups, leaving the suite fully
unittest-compatible. Stages 6–8 are terminal: they convert the suite to native
pytest and nothing depends beyond them.

## Constraints

- Stages 1–5 must keep every suite runnable as-is (`unittest.TestCase`
  intact); the constraint lifts progressively during stages 6–7 per batch.
- Mutmut's pinned selection references four test-file paths plus a `-k` filter
  naming `test_canonical_json_round_trips_arbitrary_strict_values`; converted
  files keep their paths and that test keeps its name (or `pyproject.toml` is
  updated in the same commit — prefer keeping the name).
- Test node ids change during stage 7 (`Class::method` → `module::function`);
  nothing in CI, scripts, or docs references specific node ids (verified by
  repository search during stage 8).
- Coverage flags on `template-ci.yml` stay; xdist combines worker coverage.
- No `addopts` changes (mutmut runs its own pytest invocations).
- `factory.py` follows repository typed-FP conventions: frozen dataclasses,
  closed unions dispatched via `match`/`case` ending in `assert_never`, pure
  functions with explicit inputs, no production `Result` imports (test
  infrastructure follows the existing `tests/fixtures.py` conventions per the
  AGENTS.md pragmatism clause).

## Context

**Suite inventory by fixture shape** (research result):

| Shape | Suites | Today |
|---|---|---|
| A: tracked-source snapshot repo | `test_bootstrap_cli` (40 tests), `GitHubBootstrapTests`, `test_source_bootstrap._activate_source`, no-git refusal case | three inline copies of the same flow; ~107ms/fixture × ~50 |
| B: partial-tree copies | `GitHubSnapshot.setUp`, `test_repository_validation`, `test_project_readiness`, `test_capability_matrix` | bespoke `copytree` ignore lists, ~20–60ms |
| C: tiny synthetic repos | `test_bootstrap_observation`, `test_bootstrap_recovery`, `test_bootstrap_state_root` | inline `git init/add` subprocesses per site |
| D: copier path | `test_copier.py` (collected smoke), `test_copier_bootstrap.py` (script) | out of factory scope |

**Measured baselines:** serial suite 45s; `_make_fixture()` 107ms;
`copy_tracked()` 20ms warm; materialization benchmark on this machine's btrfs
`/tmp`: today's loop 13.6ms, plain `shutil.copytree(pristine)` 9.8ms, custom
`os.copy_file_range` loop 10.6ms (bytes+modes identical for both).

**Framework facts (verified against docs):**
- Factories-as-fixtures returning callables are the documented pattern for
  multiple per-test constructions; `tmp_path`/`tmp_path_factory` own lifetimes.
  (Custom markers were evaluated for config passing and dropped alongside the
  unittest bridges — explicit typed `SnapshotConfig` values won.)
- xdist: session-scoped fixtures execute once **per worker**; the FileLock
  recipe exists for exactly-once semantics but is unnecessary here — the
  pristine build is ~15ms with no git, so 20 workers pay ~noise total, without
  adding a `filelock` dependency or cross-worker coupling.
- The documented modernization path for unittest suites is incremental
  conversion to plain asserts/functions — this design executes that path
  deliberately, after the shared fixture foundation exists.

**Prior art:** pypa/pip keeps fixture builders in a dedicated library module
(`tests/lib/local_repos.py`) separate from conftest wiring; large pytest-native
suites (pip, pydantic) consume session-pricy resources exclusively through
conftest-declared fixtures with `tmp_path_factory` lifetime management.

### Terminology

Test-infrastructure-local terms used consistently below (not product-domain
terms; CONTEXT.md unaffected):

- **Pristine snapshot**: one per-worker copy of the source file set enumerated
  by `tests/fixtures.py::tracked_files()` — `git ls-files -co
  --exclude-standard`, i.e. tracked **plus non-ignored untracked** files, with
  entries whose paths fail `is_file()` (today the committed `.claude/skills/*`
  symlinks) omitted exactly as the current helper does. Built by copying each
  enumerated file individually (preserving bytes and modes); never a
  `copytree` over the repository root. No git metadata is copied, and the
  snapshot is materialized once and only ever read.
- **Materialization**: producing a per-test writable tree by copying the
  pristine snapshot (a tree of plain regular files) with stdlib
  `shutil.copytree`.
- **Seed commit**: the single `git init/add/commit` sequence giving a fixture a
  recognized worktree.
- **Snapshot project**: a materialized tree + scaffold overlay + seed commit +
  recording-hook state, returned as one value.
- **Exemplar conversion**: the stage-6 suite whose class-to-function rewrite
  defines the mechanical pattern all later batches follow.

## Architecture

Three layers, strict dependency direction:

```
suites (plain pytest modules, post-stage-7)
    │ requests fixtures / calls builders
conftest.py                   ← pytest coupling only: scopes, tmp_path
    │ wraps
factory.py                    ← pure engine: no pytest imports
```

`factory.py` mirrors the functional-core/imperative-shell rule: importable
anywhere, testable without pytest; all framework knowledge lives in conftest.

**`tests/conftest.py`**

- Session-scoped autouse fixture `deterministic_git_env` force-setting the git
  environment (intent-revealing, visible in `--setup-plan`).
- Fixture graph (native signatures — no unittest bridges):

| Fixture | Scope | Returns |
|---|---|---|
| `pristine_source` | session | `factory.pristine_snapshot()` |
| `make_bundle(tmp_path)` | function | partial of `write_answer_bundle` bound to the test's tmp dir |
| `make_seed_repo(tmp_path)` | function | partial of `seed_repo` |
| `materialized_tree(tmp_path)` | function | tracked-tree copy, no git |
| `scaffolded_project(tmp_path)` | function | default-config snapshot project for the common case |

Snapshot projects are constructed by requesting `pristine_source` +
`tmp_path` and calling `factory.build_snapshot_project(...)` directly in the
rare tests needing non-default configuration; the common case gets a thin
`scaffolded_project(tmp_path)` fixture with default `SnapshotConfig()`.
Configuration travels as explicit typed values, never as stringly markers —
the marker mechanism was a unittest-era workaround and is dropped with it.

**Suite conversion pattern (exemplar-defined, applied per batch in stage 7)**

- `class CliFamilyTests(unittest.TestCase)` → module-level `def test_*`
  functions; `setUp`/`tearDown` bodies dissolve into fixture requests
  (`tmp_path`, `scaffolded_project`, `make_bundle`).
- `self.assertEqual(a, b)` family → bare `assert` with pytest introspection.
- `subTest` loops → `@pytest.mark.parametrize` with explicit ids.
- `patch(...)` contexts stay (unittest.mock remains the stdlib tool).
- Per-class constants (`SCAFFOLD_README`, bundles' JSON shapes) move to module
  level unchanged.

Unchanged throughout: render/assert helpers in `fixtures.py`,
`bootstrap_fixtures.py`, mutmut pins, coverage flags, all production code.
`TemplatePackage` moves into the factory as the synthetic-template variant;
genuinely unique fixtures (maintenance inventory digests, journal envelopes)
stay in their suites.

## API Design

```python
# tests/factory.py  (public surface; pytest-free)
type TemplateSource = Literal["live", "synthetic"]

@dataclass(frozen=True)
class SnapshotConfig:
    template: TemplateSource = "live"
    maintenance: bool = False
    copier_marker: bool = False

@dataclass(frozen=True)
class SnapshotProject:
    root: Path
    hook_runs: Path
    template_root: Path | None          # synthetic variant only
    def run_count(self) -> int: ...

def pristine_snapshot(*, root: Path = REPO_ROOT) -> Path      # lru_cache(1)
def build_pristine_snapshot(*, root: Path, parent: Path) -> Path
def copy_tree(source: Path, target: Path, *,
              ignore: frozenset[str] = CANONICAL_IGNORE) -> None
def build_snapshot_project(parent: Path, config: SnapshotConfig, *,
                           pristine: Path) -> SnapshotProject
def seed_repo(parent: Path, files: Mapping[str, str | bytes], *,
              name: str = "repo") -> Path
def write_answer_bundle(parent: Path, *, supplied: bool, record: Path,
                        name: str = "bundle",
                        capabilities: Sequence[str] | None = None,
                        capability_settings: Mapping[str, Mapping[str, str | bool]] | None = None,
                        ) -> Path
def git(*args: str, cwd: Path) -> None                # raises with captured stderr
```

Decisions:

- `template` dispatch is `match config.template:` with `"live"`, `"synthetic"`,
  and `case _: assert_never(...)` — exhaustiveness checked by basedpyright.
- `pristine_snapshot()` is the single sanctioned cache (`lru_cache(1)`); the
  session fixture delegates to it. Deliberate dual ownership, documented.
- `write_answer_bundle` merges `fixtures.write_bundle` and CLI `BundleDir`;
  `CANONICAL_IGNORE` centralizes four bespoke ignore lists; `seed_repo`
  replaces every inline git site.
- Error style: fail loud with captured stderr (today's `_snapshot` behavior).

## Data Model

Two frozen dataclasses above plus `CANONICAL_IGNORE: frozenset[str]`. The
pristine snapshot is an immutable-by-convention directory owned per worker;
per-test trees are its copies created under the requesting test's `tmp_path`.
Recording-hook state stays a plain text file counted by `run_count()`. No
persistence beyond tmp dirs; pytest owns lifetimes.

## Trade-offs

Rejected alternatives (with reasons, to prevent relitigating):

| Alternative | Why rejected |
|---|---|
| Keeping unittest permanently; serving it via `usefixtures`/marker bridges | bridge machinery exists solely for `TestCase` limitations; once migration is in scope the bridge is pure overhead — dropped |
| Plain-function factory as final state | kept as stage-4 milestone/fallback, not destination |
| Migrating to pytest *before* the factory exists | would block all speedups behind a 45-file mechanical churn with no payoff yet; foundation-first ordering lets each conversion batch be trivially reviewable |
| `git clone --shared` repos | origin remote trips protected-target refusal; alternates make fixtures non-self-contained |
| Custom reflink copier | benchmarked slower than stdlib `copytree`; stdlib owns FS differences |
| xdist FileLock exactly-once | build cost ≪ coordination + dependency |
| `-n auto` in `addopts` | would force parallelism into mutmut's pytest invocations |
| Production `Result` types in factory | test infra convention; AGENTS.md pragmatism clause |

Known limitations (accepted):

- Node ids change during stage 7; selection by old class-style ids stops
  working mid-rollout (verified nothing references them).
- On ext4 CI, materialization ≈ today's speed; wins there come from `-n auto`.
- `test_copier_bootstrap.py` remains outside the factory and unittest-era
  style (it is not collected).
- `subTest` → `parametrize` multiplies collected ids (~82 extra), inflating
  verbose output slightly; each case gains individual reporting and selection.

Resolved questions (were open during design, now decided):
CONTRIBUTING.md gains a short "Running tests" section documenting
`uv run pytest -n auto`; factory gets its own `tests/test_factory.py`;
stage 8 verifies mutmut via collection of the pinned files plus a targeted
mutant sample rather than a full mutation run.

## Open Questions

None.
