from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/public_dashboard_app_v2_9.py"


class DepartmentHistoryChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APP.read_text(encoding="utf-8-sig")
        ast.parse(cls.source)

    def test_shared_chart_preserves_unknown_dates_and_accessible_values(self) -> None:
        start = self.source.index("def _department_history_chart")
        end = self.source.index("def _meity_historical_card", start)
        helper = self.source[start:end]
        self.assertIn("Date not recorded", helper)
        self.assertIn('role="img"', helper)
        self.assertIn("history-row", helper)
        self.assertIn("title=", helper)

    def test_department_pages_render_history_charts(self) -> None:
        for heading in (
            "DPIIT Historical Calls by Closing Year",
            "DBT–BIRAC Historical Calls by Closing Year",
            "MSME Historical References by Evidenced Year",
        ):
            self.assertIn(heading, self.source)
        self.assertIn("date_getter=lambda item: item.closing_date", self.source)


if __name__ == "__main__":
    unittest.main()
