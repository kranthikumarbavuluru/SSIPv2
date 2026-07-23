from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = (
    PROJECT_ROOT
    / "assets/styles/ssip_public_dashboard.css"
)


class DefinitiveDepartmentTabContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8-sig")
        cls.start = cls.css.index(
            "v3.4.3.7.9.2 — definitive version-tolerant"
        )
        cls.block = cls.css[cls.start:]

    def test_role_based_selector_does_not_require_button_tag(self) -> None:
        self.assertIn(
            '[data-baseweb="tab-list"] [role="tab"]',
            self.block,
        )
        self.assertIn(
            '[data-testid="stTabs"] [role="tab"]',
            self.block,
        )
        self.assertNotIn(
            'button[role="tab"]',
            self.block,
        )

    def test_all_nested_label_nodes_are_forced_visible(self) -> None:
        required = (
            '[data-baseweb="tab-list"] [role="tab"] *',
            '[data-testid="stTabs"] [role="tab"] *',
            'opacity: 1 !important;',
            'visibility: visible !important;',
            'filter: none !important;',
            'mix-blend-mode: normal !important;',
        )
        for marker in required:
            self.assertIn(marker, self.block)

    def test_colour_tracks_ssip_theme_variables(self) -> None:
        self.assertIn(
            'var(--public-ink, #10213f)',
            self.block,
        )
        self.assertIn(
            'var(--public-blue-dark, #0b3a82)',
            self.block,
        )
        self.assertIn(
            'var(--public-blue, #1261c9)',
            self.block,
        )
        self.assertNotIn(
            'html:not(:has(#ssip-dark-mode))',
            self.block,
        )

    def test_inactive_and_selected_states_are_explicit(self) -> None:
        self.assertIn(
            '[aria-selected="false"]',
            self.block,
        )
        self.assertIn(
            '[aria-selected="true"]',
            self.block,
        )
        self.assertIn(
            'box-shadow: inset 0 -2px 0',
            self.block,
        )

    def test_markdown_label_fallback_is_present(self) -> None:
        self.assertIn(
            '[data-testid="stMarkdownContainer"] p',
            self.block,
        )


if __name__ == "__main__":
    unittest.main()
