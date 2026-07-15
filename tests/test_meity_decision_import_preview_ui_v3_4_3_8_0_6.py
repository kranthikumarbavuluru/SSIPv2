from __future__ import annotations

import ast
import unittest
from pathlib import Path


class MeitYDecisionImportPreviewUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = (
            Path(__file__).resolve().parents[1]
            / "ui/meity_decision_import_preview_v3_4_3_8_0_6.py"
        )
        cls.text = cls.path.read_text(encoding="utf-8")
        ast.parse(cls.text)

    def test_three_step_import_workflow_exists(self) -> None:
        for marker in (
            "Step 1 — Upload the decision worksheet",
            "Step 2 — Validate the worksheet",
            "Step 3 — Review the validation result",
        ):
            self.assertIn(marker, self.text)

    def test_database_and_publication_are_not_applied(self) -> None:
        self.assertIn(
            "This page does not update the database",
            self.text,
        )
        self.assertIn("Database write performed", self.text)
        self.assertIn("Publication performed", self.text)
        self.assertIn("Admin bridge applied", self.text)

    def test_rejected_rows_are_clearly_separated(self) -> None:
        self.assertIn("Rejected Rows", self.text)
        self.assertIn(
            "Rejected rows never enter the Admin bridge",
            self.text,
        )

    def test_signed_plan_can_be_downloaded(self) -> None:
        self.assertIn(
            "Download the signed Admin-bridge plan",
            self.text,
        )
        self.assertIn("decision_plan_signature", self.text)

    def test_strict_mode_is_default(self) -> None:
        self.assertIn(
            "Block the whole plan when any row is invalid",
            self.text,
        )
        self.assertIn("value=True", self.text)


if __name__ == "__main__":
    unittest.main()
