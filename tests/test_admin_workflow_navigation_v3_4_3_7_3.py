from __future__ import annotations

import unittest
from pathlib import Path

from services.admin_workflow_navigation_v3_4_3_7_3 import (
    NAVIGATION_VERSION,
    WORKFLOW_PHASES,
    guidance_for_route,
    phase_for_route,
    route_for_label,
    workflow_snapshot,
    workspace_labels,
)


ROOT = Path(__file__).resolve().parents[1]
ADMIN_UI = ROOT / "ui/admin_review_app_v1.py"


class AdminWorkflowNavigationTests(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(NAVIGATION_VERSION, "3.4.3.7.3")

    def test_workspace_order_starts_with_agent_intake(self) -> None:
        self.assertEqual(
            workspace_labels(),
            (
                "1. Agent Intake & Dry Run",
                "2. Verify Pending Records",
                "3. Stage & Publish Approved Records",
                "4. Ingestion History",
                "5. Historical Archive",
                "6. Audit Trail",
            ),
        )

    def test_routes_preserve_existing_workspace_contract(self) -> None:
        self.assertEqual(
            route_for_label("1. Agent Intake & Dry Run"),
            "Department Agent Intake",
        )
        self.assertEqual(
            route_for_label("2. Verify Pending Records"),
            "Review Inbox",
        )
        self.assertEqual(
            route_for_label("3. Stage & Publish Approved Records"),
            "Publication Queue",
        )

    def test_primary_phase_mapping(self) -> None:
        self.assertEqual(phase_for_route("Department Agent Intake"), 1)
        self.assertEqual(phase_for_route("Review Inbox"), 2)
        self.assertEqual(phase_for_route("Publication Queue"), 4)
        self.assertIsNone(phase_for_route("Audit Trail"))

    def test_four_governed_phases_are_explicit(self) -> None:
        self.assertEqual(
            [phase.title for phase in WORKFLOW_PHASES],
            [
                "Agent intake",
                "Human verification",
                "Staging quality",
                "Publication",
            ],
        )

    def test_snapshot_uses_live_counts(self) -> None:
        snapshot = workflow_snapshot(
            "Review Inbox",
            {
                "pending_reviews": 2,
                "staged_schemes": 45,
            },
        )
        self.assertEqual(snapshot[1]["status"], "2 pending")
        self.assertTrue(snapshot[1]["active"])
        self.assertEqual(snapshot[2]["status"], "45 staged")

    def test_guidance_is_actionable(self) -> None:
        self.assertIn(
            "Start here",
            guidance_for_route("Department Agent Intake"),
        )
        self.assertIn(
            "Review imported pending records",
            guidance_for_route("Review Inbox"),
        )
        self.assertIn(
            "preflight",
            guidance_for_route("Publication Queue"),
        )

    def test_admin_ui_uses_new_navigation(self) -> None:
        source = ADMIN_UI.read_text(encoding="utf-8")
        self.assertIn(
            "services.admin_workflow_navigation_v3_4_3_7_3",
            source,
        )
        self.assertIn("workspace_labels()", source)
        self.assertIn("index=0", source)
        self.assertIn("workflow_snapshot(workspace, counts)", source)

    def test_admin_ui_explains_empty_pending_queue(self) -> None:
        source = ADMIN_UI.read_text(encoding="utf-8")
        self.assertIn(
            "Verification queue complete: there are no pending records.",
            source,
        )
        self.assertIn(
            "Approved records remain non-public",
            source,
        )

    def test_no_governance_actions_are_changed(self) -> None:
        source = ADMIN_UI.read_text(encoding="utf-8")
        self.assertIn(
            "service.approve(selected_id, edited",
            source,
        )
        self.assertIn(
            "publication.bulk_action(",
            source,
        )
        self.assertIn(
            "expected_signature=report",
            source,
        )


if __name__ == "__main__":
    unittest.main()
