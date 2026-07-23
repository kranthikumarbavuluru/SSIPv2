from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = (
    PROJECT_ROOT
    / "assets/styles/ssip_public_dashboard.css"
)


class DepartmentTabContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8-sig")

    def test_light_mode_tab_labels_are_explicitly_visible(self) -> None:
        required = (
            'html:not(:has(#ssip-dark-mode)) '
            'div[data-testid="stTabs"]',
            'color: #405873 !important;',
            '-webkit-text-fill-color: #405873 !important;',
            'opacity: 1 !important;',
            'visibility: visible !important;',
        )
        for marker in required:
            self.assertIn(marker, self.css)

    def test_inactive_and_selected_light_tabs_are_covered(self) -> None:
        self.assertIn(
            'button[role="tab"][aria-selected="false"]',
            self.css,
        )
        self.assertIn(
            'button[role="tab"][aria-selected="true"]',
            self.css,
        )
        self.assertIn(
            'color: #0b4da5 !important;',
            self.css,
        )

    def test_dark_mode_tab_contrast_is_preserved(self) -> None:
        required = (
            'html:has(#ssip-dark-mode) '
            'div[data-testid="stTabs"]',
            'color: #c7d8ec !important;',
            '-webkit-text-fill-color: #ffffff !important;',
            'background-color: #4da3ff !important;',
        )
        for marker in required:
            self.assertIn(marker, self.css)

    def test_streamlit_tab_highlight_is_branded(self) -> None:
        self.assertIn(
            '[data-baseweb="tab-highlight"]',
            self.css,
        )
        self.assertIn(
            'background-color: #1261c9 !important;',
            self.css,
        )

    def test_fix_is_scoped_to_tabs(self) -> None:
        marker_start = self.css.index(
            "v3.4.3.7.9.1 — readable Streamlit department tabs"
        )
        block = self.css[marker_start:]
        self.assertIn('data-testid="stTabs"', block)
        self.assertNotIn(
            'div[data-testid="stRadioGroup"]',
            block,
        )


if __name__ == "__main__":
    unittest.main()
