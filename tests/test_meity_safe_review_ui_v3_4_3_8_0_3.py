from __future__ import annotations

import ast
import unittest
from pathlib import Path


class MeitYSafeReviewUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_safe_family_review_v3_4_3_8_0_3.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_ambiguous_accept_recommendation_is_blocked(self) -> None:
        self.assertIn(
            '"ACCEPT_RECOMMENDATION" in allowed',
            self.text,
        )
        self.assertIn(
            "Unsafe decision wording detected",
            self.text,
        )

    def test_deep_review_requires_child_selection(self) -> None:
        self.assertIn("requires_child_selection", self.text)
        self.assertIn("Select at least one child record before saving", self.text)
        self.assertIn("selection_ready", self.text)

    def test_save_button_is_disabled_until_safe(self) -> None:
        self.assertIn("disabled=not save_ready", self.text)
        self.assertIn("requires_admin_note", self.text)
        self.assertIn("decision_ready", self.text)

    def test_evidence_at_a_glance_fields_exist(self) -> None:
        for marker in (
            "Safe status",
            "Temporal validation",
            "Parent-link result",
            "Application window",
            "Application route",
            "Last verified",
            "Repaired parent",
            "Current-status evidence",
        ):
            self.assertIn(marker, self.text)

    def test_session_decisions_invalidate_on_signature_change(self) -> None:
        self.assertIn("session_state_signature", self.text)
        self.assertIn("Previous session decisions were cleared", self.text)
        self.assertIn("bundle_signature", self.text)


if __name__ == "__main__":
    unittest.main()
