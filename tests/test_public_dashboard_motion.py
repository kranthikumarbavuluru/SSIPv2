from __future__ import annotations

import unittest
from pathlib import Path

from ssip_dashboard.components import metric_card


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicDashboardMotionTest(unittest.TestCase):
    def test_integer_metric_has_count_up_target_and_accessible_value(self) -> None:
        html = metric_card("Total Records", 42, "Current catalogue")

        self.assertIn('class="metric-value is-counting"', html)
        self.assertIn('style="--ssip-count: 42"', html)
        self.assertIn('aria-label="42"', html)

    def test_non_numeric_metric_remains_plain_text(self) -> None:
        html = metric_card("Funding", "Not recorded")

        self.assertNotIn("is-counting", html)
        self.assertNotIn("--ssip-count", html)
        self.assertIn("Not recorded", html)

    def test_motion_styles_include_chart_reveal_and_reduced_motion_fallback(self) -> None:
        css = (PROJECT_ROOT / "ssip_dashboard" / "assets" / "styles.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("@keyframes ssip-donut-reveal", css)
        self.assertIn("@keyframes ssip-count-up", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_dark_theme_styles_and_toggle_are_present(self) -> None:
        css = (PROJECT_ROOT / "ssip_dashboard" / "assets" / "styles.css").read_text(
            encoding="utf-8"
        )
        app = (PROJECT_ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("#ssip-dark-mode", css)
        self.assertIn(":root:has(#ssip-dark-mode)", css)
        self.assertIn('key="ssip_dark_mode"', app)
        self.assertIn('id="ssip-dark-mode"', app)


if __name__ == "__main__":
    unittest.main()
