from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "apps" / "ssip_public_dashboard_v3_4_0_4.py"


class SsipPublicDashboardThemeTest(unittest.TestCase):
    def test_dashboard_provides_a_dark_mode_toggle(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn('key="ssip_dark_mode"', source)
        self.assertIn('st.session_state["ssip_dark_mode"] = False', source)
        self.assertIn('if dark_mode:', source)

    def test_dark_theme_covers_app_shell_and_core_dashboard_surfaces(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("DARK_THEME_CSS", source)
        self.assertIn(".stApp", source)
        self.assertIn("section[data-testid=\"stSidebar\"]", source)
        self.assertIn(".entity-card", source)
        self.assertIn('div[data-testid="stMetric"]', source)
        self.assertIn('div[data-testid="stLinkButton"]', source)

    def test_light_mode_is_explicitly_styled_for_reliable_contrast(self) -> None:
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("LIGHT_THEME_CSS", source)
        self.assertIn('st.markdown(f"<style>{LIGHT_THEME_CSS}</style>"', source)
        self.assertIn('header[data-testid="stHeader"]', source)


if __name__ == "__main__":
    unittest.main()
