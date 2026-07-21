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
        self.assertIn("No public Apply action", block)

    def test_dpiit_page_is_explicitly_preview_only(self) -> None:
        start = self.text.index("def render_dpiit_page()")
        end = self.text.index("def main()", start)
        block = self.text[start:end]
        self.assertIn("Preview · Not published", block)
        self.assertIn("Admin Review", block)
        self.assertIn("Evidence Resources", block)


if __name__ == "__main__":
    unittest.main()
