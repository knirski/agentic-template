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
import unittest
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
    inconsistent here (-- T4 uses `commit` singular string, T5-T8 omit it --)
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


class PlanContractTests(unittest.TestCase):
    def test_task_execution_order_and_pull_request_metadata(self) -> None:
        # Why: the real plan.json is the canonical example of this contract.
        # Its task key order must keep `execution` between `description` and
        # `files`, and the `github_prs` rule (pending omits it; everyone else
        # carries a list) must hold. A drift here means either the plan data
        # or the documented schema changed without the other following.
        #
        # The canonical plan predates `new_abstractions` (added by upstream
        # spec-plan v3.1.0), so it legitimately lacks that key. Pinning the
        # exact existing shape would reject any FUTURE plan.json that follows
        # the documented contract, so assert the positional contract instead:
        # the canonical keys in order, with an optional `new_abstractions`
        # between `files` and `validation` when present.
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
                self.assertEqual(keys, expected, task["id"])
                execution = task["execution"]
                execution = cast(dict[str, object], execution)
                if execution["status"] == "pending":
                    self.assertNotIn("github_prs", execution, task["id"])
                else:
                    self.assertIsInstance(execution.get("github_prs"), list, task["id"])

    def test_future_plan_guidance_documents_the_same_contract(self) -> None:
        # Why: `npx skills update` overwrites spec-plan wholesale. If the
        # `execution`/`github_prs` schema vanishes from the guidance, future
        # plans would be authored against a weaker contract with no signal.
        # These substring anchors fail loudly the moment upstream's prose
        # replaces the example.
        guidance = SPEC_PLAN.read_text(encoding="utf-8")
        self.assertLess(
            guidance.index('"description":'), guidance.index('"execution":')
        )
        self.assertIn('"github_prs": []', guidance)

    def test_real_plan_json_satisfies_execution_contract(self) -> None:
        # Why: the order/`github_prs` test above only checks surface shape.
        # This runs the full inline invariant (status vocabulary; pending vs
        # completed completion shape; non-empty evidence on completed tasks)
        # against the actual repository plan, so the contract's deepest rules
        # are validated against ground truth rather than synthetic data.
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
                self.assertEqual(failures, (), f"{task['id']}: {failures}")

    def test_spec_plan_documents_the_full_execution_contract(self) -> None:
        # Why: the previous guidance test only pins two substrings. This pins
        # the discriminated-union explanation, the task key order mentioning
        # `execution`, the inline + tracker examples, and the two verification
        # bullets. Together they make deleting the contract from spec-plan
        # fail several tests at once instead of one brittle one.
        guidance = SPEC_PLAN.read_text(encoding="utf-8")
        self.assertIn(
            "Each task carries its own `execution` discriminated union", guidance
        )
        self.assertIn(
            "Keep task keys in this order: `id`, `name`, `depends_on`, `inputs`, `description`, `execution`",
            guidance,
        )
        self.assertIn('"mode": "inline", "status": "pending"', guidance)
        self.assertIn('"mode": "tracker", "tracker": {"provider": "github"', guidance)
        self.assertIn(
            "Every task has execution metadata in the selected mode", guidance
        )
        self.assertIn(
            "Every non-pending task has a `github_prs` list, and pending tasks omit it",
            guidance,
        )

    def test_spec_implement_documents_the_execution_lifecycle(self) -> None:
        # Why: spec-plan DEFINES the contract; spec-implement is the only skill
        # that tells the agent to maintain it during execution. Upstream dropped
        # these paragraphs, and NO existing test caught it (the schema in the
        # data file stayed valid because it was written before the update). This
        # pin makes a silent regression of spec-implement fail immediately.
        skill = SPEC_IMPLEMENT.read_text(encoding="utf-8")
        self.assertIn(
            "When a task's `execution.mode` is `inline`, before starting it set its `execution.status` to",
            skill,
        )
        self.assertIn("set it to `completed` and record completion date", skill)
        self.assertIn("If blocked, set it to `blocked`", skill)
        self.assertIn("Never mix modes within a task", skill)
        # Guards the rule that inline_MODE state lives in plan.json, not in an
        # informal note or inferred from git history.
        self.assertIn("its `plan.json` execution entry is required", skill)
        # The completion checklist bullet that depends on this contract.
        self.assertIn(
            "every task's inline execution status is `completed`, or every referenced",
            skill,
        )

    def test_spec_finish_documents_the_completion_gate(self) -> None:
        # Why: spec-finish is the VERIFY link. Without this paragraph, the PR
        # step can proceed while inline tasks are still in_progress/blocked,
        # defeating the point of tracking progress. This pin keeps the gate.
        skill = SPEC_FINISH.read_text(encoding="utf-8")
        self.assertIn(
            "every task's inline execution status is `completed` with evidence, or every",
            skill,
        )

    def test_execution_status_vocabulary_is_consistent_across_skills(self) -> None:
        # Why: spec-plan and spec-implement describe the same status machine.
        # If someone edits one skill and renames or drops a status, the other
        # would silently disagree. This asserts the four canonical statuses
        # appear in spec-plan (the definition) and the three transition targets
        # the agent performs appear in spec-implement, keeping the cycle coherent.
        spec_plan = SPEC_PLAN.read_text(encoding="utf-8")
        spec_implement = SPEC_IMPLEMENT.read_text(encoding="utf-8")
        for status in INLINE_STATUSES:
            self.assertIn(status, spec_plan, msg=f"spec-plan missing status {status}")
        for status in ("in_progress", "completed", "blocked"):
            self.assertIn(
                status, spec_implement, msg=f"spec-implement missing status {status}"
            )


class ExecutionInvariantSyntheticTests(unittest.TestCase):
    """Exercise the invariant validator on synthetic shapes.

    The real plan.json only uses inline mode, so the tracker branch would be
    untested without these. Each test names the rule it guards, and includes a
    negative case so the validator is shown to reject violations, not just
    accept valid shapes.
    """

    def _assert_failure(self, task: dict[str, object], fragment: str) -> None:
        # Helper: the validator returns a TUPLE of messages, so `assertIn` on
        # the tuple would check element equality, not substring presence.
        # Match the fragment against any message, mirroring how a real failure
        # is localised during debugging.
        failures = execution_invariant_failures(task)
        self.assertTrue(
            any(fragment in failure for failure in failures),
            msg=f"expected {fragment!r} in {failures}",
        )

    def test_inline_pending_shape_is_valid(self) -> None:
        task: dict[str, object] = {
            "id": "S1",
            "execution": {"mode": "inline", "status": "pending", "completion": None},
        }
        self.assertEqual(execution_invariant_failures(task), ())

    def test_inline_pending_rejects_github_prs_and_completion(self) -> None:
        pending_with_prs: dict[str, object] = {
            "id": "S2",
            "execution": {
                "mode": "inline",
                "status": "pending",
                "completion": None,
                "github_prs": [],
            },
        }
        self._assert_failure(
            pending_with_prs, "pending inline task must omit github_prs"
        )
        pending_with_completion: dict[str, object] = {
            "id": "S3",
            "execution": {"mode": "inline", "status": "pending", "completion": {}},
        }
        self._assert_failure(
            pending_with_completion, "pending inline task must have null completion"
        )

    def test_inline_completed_shape_is_valid(self) -> None:
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
        self.assertEqual(execution_invariant_failures(task), ())

    def test_inline_completed_rejects_missing_completion_object(self) -> None:
        no_completion: dict[str, object] = {
            "id": "S5",
            "execution": {
                "mode": "inline",
                "status": "completed",
                "completion": None,
                "github_prs": ["https://github.com/owner/repo/pull/1"],
            },
        }
        self._assert_failure(
            no_completion, "completed inline task needs a completion object"
        )

    def test_inline_completed_rejects_missing_required_completion_fields(self) -> None:
        # `evidence` and `completed_at` are the required proof of completion.
        # Omitting either would let a task be marked done without verifiable
        # ground, which is exactly what the gate in spec-finish defends against.
        missing_evidence: dict[str, object] = {
            "id": "S6",
            "execution": {
                "mode": "inline",
                "status": "completed",
                "completion": {"completed_at": "2026-08-13"},
                "github_prs": [],
            },
        }
        self._assert_failure(missing_evidence, "needs a non-empty evidence list")
        missing_date: dict[str, object] = {
            "id": "S7",
            "execution": {
                "mode": "inline",
                "status": "completed",
                "completion": {"evidence": ["tests pass"]},
                "github_prs": [],
            },
        }
        self._assert_failure(missing_date, "completion missing completed_at")

    def test_inline_non_pending_requires_github_prs_list(self) -> None:
        # in_progress/blocked need not carry `completion`, but they DO need a
        # `github_prs` list (they represent reviewable work, just not finished).
        with_prs: dict[str, object] = {
            "id": "S8",
            "execution": {
                "mode": "inline",
                "status": "in_progress",
                "completion": None,
                "github_prs": [],
            },
        }
        self.assertEqual(execution_invariant_failures(with_prs), ())
        without_prs: dict[str, object] = {
            "id": "S9",
            "execution": {
                "mode": "inline",
                "status": "in_progress",
                "completion": None,
            },
        }
        self._assert_failure(
            without_prs, "non-pending inline task needs github_prs as a list"
        )

    def test_tracker_shape_is_valid(self) -> None:
        task: dict[str, object] = {
            "id": "S10",
            "execution": {
                "mode": "tracker",
                "tracker": {"provider": "github", "location": "owner/repo"},
                "ref": "https://github.com/owner/repo/issues/9",
                "github_prs": [],
            },
        }
        self.assertEqual(execution_invariant_failures(task), ())

    def test_tracker_rejects_missing_ref_and_mode_mixing(self) -> None:
        no_ref: dict[str, object] = {
            "id": "S11",
            "execution": {
                "mode": "tracker",
                "tracker": {"provider": "github", "location": "owner/repo"},
                "github_prs": [],
            },
        }
        self._assert_failure(no_ref, "tracker ref must be a string URL")
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
        self._assert_failure(mixed, "tracker task must not carry inline status")

    def test_unknown_mode_and_missing_execution_are_rejected(self) -> None:
        bad_mode: dict[str, object] = {
            "id": "S13",
            "execution": {"mode": "mystery", "status": "pending"},
        }
        self._assert_failure(bad_mode, "expected inline or tracker")
        no_execution: dict[str, object] = {"id": "S14", "name": "no execution"}
        self.assertEqual(
            execution_invariant_failures(no_execution),
            ("S14: missing execution field",),
        )


if __name__ == "__main__":
    _ = unittest.main()
