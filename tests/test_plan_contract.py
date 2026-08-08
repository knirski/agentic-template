#!/usr/bin/env python3
"""Validate the structured plan authoring contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs/specs/2026-08-05-deterministic-project-bootstrap/plan.json"
SPEC_PLAN = ROOT / ".agents/skills/spec-plan/SKILL.md"


class PlanContractTests(unittest.TestCase):
    def test_task_execution_order_and_pull_request_metadata(self) -> None:
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        expected_order = [
            "id",
            "name",
            "depends_on",
            "inputs",
            "description",
            "execution",
            "files",
            "validation",
        ]

        for phase in plan["phases"]:
            for task in phase["tasks"]:
                self.assertEqual(list(task), expected_order, task["id"])
                execution = task["execution"]
                if execution["status"] == "pending":
                    self.assertNotIn("github_prs", execution, task["id"])
                else:
                    self.assertIsInstance(execution.get("github_prs"), list, task["id"])

    def test_future_plan_guidance_documents_the_same_contract(self) -> None:
        guidance = SPEC_PLAN.read_text(encoding="utf-8")
        self.assertLess(
            guidance.index('"description":'), guidance.index('"execution":')
        )
        self.assertIn('"github_prs": []', guidance)


if __name__ == "__main__":
    unittest.main()
