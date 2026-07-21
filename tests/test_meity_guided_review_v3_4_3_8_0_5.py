from __future__ import annotations

import ast
import unittest
from pathlib import Path

from services.meity_guided_review_v3_4_3_8_0_5 import (
    allowed_action_records,
    note_required,
    plain_action_label,
    queue_bucket,
    simple_record_summary,
)


class MeitYGuidedReviewTests(unittest.TestCase):
    def test_plain_language_labels_hide_technical_codes(self) -> None:
        self.assertEqual(
            plain_action_label("NEEDS_MORE_EVIDENCE"),
            "Needs more official evidence",
        )
        self.assertEqual(
            plain_action_label("CONFIRM_HISTORICAL"),
            "Confirm as a historical reference",
        )

    def test_accept_recommendation_is_removed(self) -> None:
        actions = allowed_action_records(
            {
                "allowed_decisions": (
                    "PENDING;ACCEPT_RECOMMENDATION;"
                    "NEEDS_MORE_EVIDENCE;DEFER"
                )
            }
        )
        codes = [row["code"] for row in actions]
        self.assertNotIn("ACCEPT_RECOMMENDATION", codes)

    def test_incomplete_link_record_goes_to_needs_evidence(self) -> None:
        bucket = queue_bucket(
            {"link_integrity_complete": "False"},
            {"temporal_validation": "CURRENT_STATUS_NOT_PROVEN"},
        )
        self.assertEqual(bucket, "NEEDS EVIDENCE")

    def test_safe_record_can_be_ready_to_confirm(self) -> None:
        bucket = queue_bucket(
            {
                "link_integrity_complete": "True",
                "safe_positive_decision_allowed": "True",
            },
            {"temporal_validation": "NOT_APPLICABLE"},
        )
        self.assertEqual(bucket, "READY TO CONFIRM")

    def test_current_record_gets_current_check_bucket(self) -> None:
        bucket = queue_bucket(
            {
                "link_integrity_complete": "True",
                "safe_positive_decision_allowed": "True",
            },
            {
                "temporal_validation": (
                    "CURRENT_STATUS_EVIDENCE_COMPLETE"
                )
            },
        )
        self.assertEqual(bucket, "CURRENT OPPORTUNITY CHECK")

    def test_more_evidence_and_rejection_require_note(self) -> None:
        bundle = {"requires_admin_note": "False"}
        self.assertTrue(note_required(bundle, "NEEDS_MORE_EVIDENCE"))
        self.assertTrue(note_required(bundle, "REJECT_CLASSIFICATION"))
        self.assertFalse(note_required(bundle, "DEFER"))

    def test_summary_is_short_and_plain(self) -> None:
        summary = simple_record_summary(
            {
                "link_integrity_complete": "False",
                "safe_positive_decision_allowed": "False",
            },
            {
                "entity_type": "PERMANENT_PROGRAMME",
                "temporal_validation": "NOT_APPLICABLE",
                "verified_information_url": (
                    "https://msh.meity.gov.in/schemes/genesis"
                ),
                "verified_application_url": "",
                "application_route_withheld_reason": (
                    "GLOBAL_CURRENT_EVIDENCE_INCOMPLETE"
                ),
            },
        )
        self.assertEqual(len(summary), 3)
        self.assertIn("permanent MeitY programme", summary[0])
        self.assertIn("official information source was verified", summary[1])


class MeitYGuidedReviewSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_guided_review_v3_4_3_8_0_5.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_page_has_three_simple_steps(self) -> None:
        for marker in (
            "Step 1 — Check the official source",
            "Step 2 — Check the system summary",
            "Step 3 — Choose one action",
        ):
            self.assertIn(marker, self.text)

    def test_technical_details_are_hidden_by_default(self) -> None:
        self.assertIn(
            "Advanced evidence details — open only when needed",
            self.text,
        )
        self.assertIn("expanded=False", self.text)

    def test_one_record_at_a_time_and_progress_exist(self) -> None:
        self.assertIn("Choose a record", self.text)
        self.assertIn("Completed this session", self.text)
        self.assertIn("Remaining", self.text)

    def test_save_moves_to_next_remaining_record(self) -> None:
        self.assertIn(
            "Save decision and show the next record",
            self.text,
        )
        self.assertIn("st.rerun()", self.text)
        self.assertIn("Remaining records", self.text)

    def test_only_verified_links_are_buttons(self) -> None:
        self.assertIn("verified_information_url", self.text)
        self.assertIn("verified_application_url", self.text)
        self.assertIn("Open the verified official page", self.text)
        self.assertIn("Open the verified application route", self.text)
        self.assertNotIn(
            'child.get("raw_application_url")\n        st.link_button',
            self.text,
        )

    def test_positive_confirmation_stays_safety_gated(self) -> None:
        self.assertIn("safe_positive_decision_allowed", self.text)
        self.assertIn("disabled=not save_ready", self.text)
        self.assertIn(
            "Confirmation is blocked because the official link evidence",
            self.text,
        )

    def test_no_database_or_publication_write(self) -> None:
        self.assertIn("Database write: No", self.text)
        self.assertIn("Publication: No", self.text)


if __name__ == "__main__":
    unittest.main()
