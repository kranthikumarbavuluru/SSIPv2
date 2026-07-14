from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "apps/public_dashboard_app_v2_9.py"


class MeitYHistoricalDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = APP_PATH.read_text(encoding="utf-8-sig")
        cls.tree = ast.parse(cls.text)

    def test_dashboard_is_valid_python(self) -> None:
        self.assertIsNotNone(self.tree)

    def test_three_meity_tabs_exist(self) -> None:
        for marker in (
            '"MeitY Schemes"',
            '"Current MeitY Calls"',
            '"MeitY Historical Archive"',
        ):
            self.assertIn(marker, self.text)

    def test_historical_archive_has_no_apply_action(self) -> None:
        start = self.text.index(
            "def _meity_historical_card("
        )
        end = self.text.index(
            "def render_meity_historical_archive(",
            start,
        )
        block = self.text[start:end]
        self.assertNotIn("Apply now", block)
        self.assertNotIn("application_url", block)
        self.assertIn(
            "Historical reference only",
            block,
        )

    def test_archive_disclaimer_and_manifest_are_visible(self) -> None:
        self.assertIn(
            "Governed MeitY historical reconstruction",
            self.text,
        )
        self.assertIn("Apply actions: 0", self.text)
        self.assertIn("additional ", self.text)
        self.assertIn(
            "identities remain under reconstruction",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
