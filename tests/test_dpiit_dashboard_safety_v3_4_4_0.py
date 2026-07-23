from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "apps/public_dashboard_app_v2_9.py"


class DPIITDashboardSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = APP_PATH.read_text(encoding="utf-8-sig")

    def test_historical_preview_cards_do_not_render_apply_action(self) -> None:
        start = self.text.index("def _dpiit_preview_card(")
        end = self.text.index("def render_dpiit_page()", start)
        block = self.text[start:end]
        self.assertNotIn("Apply now", block)
        self.assertNotIn("record.application_url", block)
        self.assertIn("No Apply action", block)

    def test_dpiit_page_uses_three_public_department_views(self) -> None:
        start = self.text.index("def render_dpiit_page()")
        end = self.text.index("def cached_dbt_birac_preview()", start)
        block = self.text[start:end]
        for label in ("Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"):
            self.assertIn(label, block)
        for removed_label in ("Government Services", "Ecosystem Opportunities", "Evidence Resources", "Admin Review"):
            self.assertNotIn(removed_label, block)
        self.assertNotIn("Preview · Not published", block)
        self.assertIn("Published on this department page", block)

    def test_dpiit_documents_are_available_from_shared_resources(self) -> None:
        start = self.text.index("def render_resources")
        end = self.text.index("def _dst_preview_notice", start)
        block = self.text[start:end]
        self.assertIn("cached_dpiit_preview().documents", block)
        self.assertIn("Department for Promotion of Industry and Internal Trade (DPIIT)", block)


if __name__ == "__main__":
    unittest.main()
