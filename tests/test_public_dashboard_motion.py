from __future__ import annotations

import unittest
from pathlib import Path

from ssip_dashboard.components import metric_card


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicDashboardMotionTest(unittest.TestCase):
    def test_integer_metric_is_visible_without_animation_and_has_accessible_value(self) -> None:
        html = metric_card("Total Records", 42, "Current catalogue")

        self.assertIn('class="metric-value"', html)
        self.assertNotIn("is-counting", html)
        self.assertNotIn("--ssip-count", html)
        self.assertIn('aria-label="42"', html)
        self.assertIn(">42</div>", html)

    def test_non_numeric_metric_remains_plain_text(self) -> None:
        html = metric_card("Funding", "Not recorded")

        self.assertNotIn("is-counting", html)
        self.assertNotIn("--ssip-count", html)
        self.assertIn("Not recorded", html)

    def test_motion_is_reduced_and_forced_layout_replay_is_absent(self) -> None:
        css = (PROJECT_ROOT / "assets" / "dashboard_theme.css").read_text(
            encoding="utf-8"
        )
        app = (PROJECT_ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertNotIn("offsetWidth", app)
        self.assertNotIn("enable_landing_animations", app)

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

    def test_navigation_has_skip_link_and_shareable_page_state(self) -> None:
        app = (PROJECT_ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('class="skip-link"', app)
        self.assertIn('id="ssip-main-content"', app)
        self.assertIn("st.query_params", app)
        self.assertIn("PAGE_SLUGS", app)


if __name__ == "__main__":
    unittest.main()
