#!/usr/bin/env python3
"""Validate the structured plan authoring contract.

This file guards a LOCAL contract that is NOT present upstream. The Atelier
planning skills (`martinffx/atelier`, v3.1.x) removed inline execution tracking
from `plan.json`: the upstream `execution` step machine was deleted and only
external tracker linking survives. This repository deliberately re-introduces
an inline `execution` field so `plan.json` is self-describing about task
progress, because that is the contract the repository itself follows (see the
real `docs/specs/.../plan.json`, whose tasks record `status`, `completion`, and
linked `github_prs`).

`npx skills update martinffx/atelier` performs a wholesale overwrite of
`.agents/skills/*`. When that drops our local additions these tests fail,
which is exactly the safety net `.agents/AGENTS.md` asks for: re-apply the
patches deliberately rather than accepting a silent regression. Three skills
form one cycle and must stay coherent:

  spec-plan      -> DEFINE  the `execution`/`github_prs` schema and rules
  spec-implement -> UPDATE  `execution.status` as tasks progress
  spec-finish    -> VERIFY  every task is `completed` before finishing

The tests below pin each link: the schema on the real `plan.json`, the schema
on synthetic shapes (both inline + tracker branches), and the three skills'
documentation of the contract so a dropped patch fails a test immediately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs/specs/2026-08-05-deterministic-project-bootstrap/plan.json"
SPEC_PLAN = ROOT / ".agents/skills/spec-plan/SKILL.md"
SPEC_IMPLEMENT = ROOT / ".agents/skills/spec-implement/SKILL.md"
SPEC_FINISH = ROOT / ".agents/skills/spec-finish/SKILL.md"

# The complete status vocabulary the inline `execution` discriminator allows.
# Defined once here so the schema, the implement transitions, and the finish
# gate can all be checked against the same set (see the coherence test).
INLINE_STATUSES: frozenset[str] = frozenset(
    {"pending", "in_progress", "blocked", "completed"}
)


def execution_invariant_failures(task: dict[str, object]) -> tuple[str, ...]:
    """Return invariant failures for a task's `execution` entry.

    Pure on purpose: it is exercised both against the real `plan.json` (ground
    truth) and against synthetic shapes (so the tracker branch is covered even
    though the current plan only uses inline mode). The rules mirror what
    `spec-plan` documents, narrowed to what the real plan data actually follows:

    inline mode:
      - status is one of INLINE_STATUSES
      - pending: no `github_prs`, `completion` is null
      - non-pending: `github_prs` is a list; a `completed` task additionally
        carries a `completion` object with `completed_at` and a non-empty
        `evidence` list
    tracker mode:
      - a `tracker` object and a string `ref`; `github_prs` is a list (present
        even when empty, per the documented tracker example)
      - must NOT carry inline `status`/`completion` (no mode mixing)

    Note on `commits`: the `spec-plan` prose recommends recording commit(s),
    but this validator does NOT require them. The real plan data is historically
    inconsistent here -- T4 uses `commit` singular string, T5-T8 omit it --
    and the load-bearing proof of completion is `evidence`, which IS required.
    Enforcing `commits` would fail on existing data for no cycle-coverage gain.

    Returns a tuple of human-readable failures (empty means valid).
    """
    failures: list[str] = []
    task_id = str(task.get("id", "<no-id>"))

    if "execution" not in task:
        return (f"{task_id}: missing execution field",)
    execution = task["execution"]
    if not isinstance(execution, dict):
        return (f"{task_id}: execution is not an object",)
    execution = cast(dict[str, object], execution)

    mode = execution.get("mode")
    status = execution.get("status")
    completion = execution.get("completion")
    has_github_prs = "github_prs" in execution
    github_prs = execution.get("github_prs")

    # `execution.mode` is the discriminator; anything else is malformed.
    if mode not in ("inline", "tracker"):
        return (f"{task_id}: execution.mode is {mode!r}, expected inline or tracker",)

    if mode == "inline":
        if status not in INLINE_STATUSES:
            failures.append(
                f"{task_id}: inline status {status!r} not in {sorted(INLINE_STATUSES)}"
            )
        # Inline and tracker are mutually exclusive within one task.
        if "tracker" in execution:
            failures.append(f"{task_id}: inline task must not carry tracker fields")
        if status == "pending":
            # A pending task has nothing to review yet, so it must not show a PR
            # list (the presence of `github_prs` implies reviewable work).
            if has_github_prs:
                failures.append(f"{task_id}: pending inline task must omit github_prs")
            if completion is not None:
                failures.append(
                    f"{task_id}: pending inline task must have null completion"
                )
        else:
            # Every non-pending status represents reviewable work, so the PR
            # list is mandatory here (possibly empty until a PR is opened).
            if not has_github_prs or not isinstance(github_prs, list):
                failures.append(
                    f"{task_id}: non-pending inline task needs github_prs as a list"
                )
            if status == "completed":
                # The contract requires proof that "completed" is not asserted
                # from vibes: a `completion` object recording when and the
                # non-empty evidence. `commits` is intentionally not enforced
                # (see the docstring note above).
                if not isinstance(completion, dict):
                    failures.append(
                        f"{task_id}: completed inline task needs a completion object"
                    )
                else:
                    completion = cast(dict[str, object], completion)
                    if "completed_at" not in completion:
                        failures.append(f"{task_id}: completion missing completed_at")
                    evidence = completion.get("evidence")
                    if not isinstance(evidence, list) or not evidence:
                        failures.append(
                            f"{task_id}: completion needs a non-empty evidence list"
                        )
    else:  # tracker mode
        # Tracker mode delegates live status to the external record, so the
        # inline status/completion fields must not also be present (no mixing).
        if status is not None:
            failures.append(f"{task_id}: tracker task must not carry inline status")
        if completion is not None:
            failures.append(f"{task_id}: tracker task must not carry inline completion")
        tracker = execution.get("tracker")
        if not isinstance(tracker, dict):
            failures.append(f"{task_id}: tracker task needs a tracker object")
        if not isinstance(execution.get("ref"), str):
            failures.append(f"{task_id}: tracker ref must be a string URL")
        if not has_github_prs or not isinstance(github_prs, list):
            failures.append(f"{task_id}: tracker task needs github_prs as a list")

    return tuple(failures)


def test_task_execution_order_and_pull_request_metadata() -> None:
    plan = cast(dict[str, object], json.loads(PLAN.read_text(encoding="utf-8")))
    canonical_order = [
        "id",
        "name",
        "depends_on",
        "inputs",
        "description",
        "execution",
        "files",
        "validation",
    ]

    phases = plan["phases"]
    assert isinstance(phases, list)
    phases = cast(list[dict[str, object]], phases)
    for phase in phases:
        tasks = phase["tasks"]
        assert isinstance(tasks, list)
        tasks = cast(list[dict[str, object]], tasks)
        for task in tasks:
            keys = list(task)
            expected = canonical_order
            if "new_abstractions" in keys:
                expected = [
                    *canonical_order[:6],
                    "new_abstractions",
                    *canonical_order[6:],
                ]
            assert keys == expected, task["id"]
            execution = task["execution"]
            execution = cast(dict[str, object], execution)
            if execution["status"] == "pending":
                assert "github_prs" not in execution, task["id"]
            else:
                assert isinstance(execution.get("github_prs"), list), task["id"]


def test_future_plan_guidance_documents_the_same_contract() -> None:
    guidance = SPEC_PLAN.read_text(encoding="utf-8")
    assert guidance.index('"description":') < guidance.index('"execution":')
    assert '"github_prs": []' in guidance


def test_real_plan_json_satisfies_execution_contract() -> None:
    plan = cast(dict[str, object], json.loads(PLAN.read_text(encoding="utf-8")))
    phases = plan["phases"]
    assert isinstance(phases, list)
    phases = cast(list[dict[str, object]], phases)
    for phase in phases:
        tasks = phase["tasks"]
        assert isinstance(tasks, list)
        tasks = cast(list[dict[str, object]], tasks)
        for task in tasks:
            failures = execution_invariant_failures(task)
            assert failures == (), f"{task['id']}: {failures}"


def test_spec_plan_documents_the_full_execution_contract() -> None:
    guidance = SPEC_PLAN.read_text(encoding="utf-8")
    assert (
        "Each task carries its own `execution` discriminated union" in guidance
    )
    assert (
        "Keep task keys in this order: `id`, `name`, `depends_on`, `inputs`, `description`, `execution`"
        in guidance
    )
    assert '"mode": "inline", "status": "pending"' in guidance
    assert '"mode": "tracker", "tracker": {"provider": "github"' in guidance
    assert (
        "Every task has execution metadata in the selected mode" in guidance
    )
    assert (
        "Every non-pending task has a `github_prs` list, and pending tasks omit it"
        in guidance
    )


def test_spec_implement_documents_the_execution_lifecycle() -> None:
    skill = SPEC_IMPLEMENT.read_text(encoding="utf-8")
    assert (
        "When a task's `execution.mode` is `inline`, before starting it set its `execution.status` to"
        in skill
    )
    assert "set it to `completed` and record completion date" in skill
    assert "If blocked, set it to `blocked`" in skill
    assert "Never mix modes within a task" in skill
    assert "its `plan.json` execution entry is required" in skill
    assert (
        "every task's inline execution status is `completed`, or every referenced"
        in skill
    )


def test_spec_finish_documents_the_completion_gate() -> None:
    skill = SPEC_FINISH.read_text(encoding="utf-8")
    assert (
        "every task's inline execution status is `completed` with evidence, or every"
        in skill
    )


def test_execution_status_vocabulary_is_consistent_across_skills() -> None:
    spec_plan = SPEC_PLAN.read_text(encoding="utf-8")
    spec_implement = SPEC_IMPLEMENT.read_text(encoding="utf-8")
    for status in INLINE_STATUSES:
        assert status in spec_plan, f"spec-plan missing status {status}"
    for status in ("in_progress", "completed", "blocked"):
        assert (
            status in spec_implement
        ), f"spec-implement missing status {status}"


def _assert_failure(task: dict[str, object], fragment: str) -> None:
    failures = execution_invariant_failures(task)
    assert any(
        fragment in failure for failure in failures
    ), f"expected {fragment!r} in {failures}"


def test_inline_pending_shape_is_valid() -> None:
    task: dict[str, object] = {
        "id": "S1",
        "execution": {"mode": "inline", "status": "pending", "completion": None},
    }
    assert execution_invariant_failures(task) == ()


def test_inline_pending_rejects_github_prs_and_completion() -> None:
    pending_with_prs: dict[str, object] = {
        "id": "S2",
        "execution": {
            "mode": "inline",
            "status": "pending",
            "completion": None,
            "github_prs": [],
        },
    }
    _assert_failure(pending_with_prs, "pending inline task must omit github_prs")
    pending_with_completion: dict[str, object] = {
        "id": "S3",
        "execution": {"mode": "inline", "status": "pending", "completion": {}},
    }
    _assert_failure(
        pending_with_completion, "pending inline task must have null completion"
    )


def test_inline_completed_shape_is_valid() -> None:
    task: dict[str, object] = {
        "id": "S4",
        "execution": {
            "mode": "inline",
            "status": "completed",
            "completion": {
                "completed_at": "2026-08-13",
                "commits": ["abc123"],
                "evidence": ["tests pass"],
            },
            "github_prs": ["https://github.com/owner/repo/pull/1"],
        },
    }
    assert execution_invariant_failures(task) == ()


def test_inline_completed_rejects_missing_completion_object() -> None:
    no_completion: dict[str, object] = {
        "id": "S5",
        "execution": {
            "mode": "inline",
            "status": "completed",
            "completion": None,
            "github_prs": ["https://github.com/owner/repo/pull/1"],
        },
    }
    _assert_failure(no_completion, "completed inline task needs a completion object")


def test_inline_completed_rejects_missing_required_completion_fields() -> None:
    missing_evidence: dict[str, object] = {
        "id": "S6",
        "execution": {
            "mode": "inline",
            "status": "completed",
            "completion": {"completed_at": "2026-08-13"},
            "github_prs": [],
        },
    }
    _assert_failure(missing_evidence, "needs a non-empty evidence list")
    missing_date: dict[str, object] = {
        "id": "S7",
        "execution": {
            "mode": "inline",
            "status": "completed",
            "completion": {"evidence": ["tests pass"]},
            "github_prs": [],
        },
    }
    _assert_failure(missing_date, "completion missing completed_at")


def test_inline_non_pending_requires_github_prs_list() -> None:
    with_prs: dict[str, object] = {
        "id": "S8",
        "execution": {
            "mode": "inline",
            "status": "in_progress",
            "completion": None,
            "github_prs": [],
        },
    }
    assert execution_invariant_failures(with_prs) == ()
    without_prs: dict[str, object] = {
        "id": "S9",
        "execution": {
            "mode": "inline",
            "status": "in_progress",
            "completion": None,
        },
    }
    _assert_failure(without_prs, "non-pending inline task needs github_prs as a list")


def test_tracker_shape_is_valid() -> None:
    task: dict[str, object] = {
        "id": "S10",
        "execution": {
            "mode": "tracker",
            "tracker": {"provider": "github", "location": "owner/repo"},
            "ref": "https://github.com/owner/repo/issues/9",
            "github_prs": [],
        },
    }
    assert execution_invariant_failures(task) == ()


def test_tracker_rejects_missing_ref_and_mode_mixing() -> None:
    no_ref: dict[str, object] = {
        "id": "S11",
        "execution": {
            "mode": "tracker",
            "tracker": {"provider": "github", "location": "owner/repo"},
            "github_prs": [],
        },
    }
    _assert_failure(no_ref, "tracker ref must be a string URL")
    mixed: dict[str, object] = {
        "id": "S12",
        "execution": {
            "mode": "tracker",
            "tracker": {"provider": "github", "location": "owner/repo"},
            "ref": "https://github.com/owner/repo/issues/9",
            "github_prs": [],
            "status": "pending",  # inline field leaks into tracker mode
        },
    }
    _assert_failure(mixed, "tracker task must not carry inline status")


def test_unknown_mode_and_missing_execution_are_rejected() -> None:
    bad_mode: dict[str, object] = {
        "id": "S13",
        "execution": {"mode": "mystery", "status": "pending"},
    }
    _assert_failure(bad_mode, "expected inline or tracker")
    no_execution: dict[str, object] = {"id": "S14", "name": "no execution"}
    assert execution_invariant_failures(no_execution) == (
        "S14: missing execution field",
    )
