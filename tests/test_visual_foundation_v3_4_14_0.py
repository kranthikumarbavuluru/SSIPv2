from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "public_dashboard_app_v2_9.py"
CSS = ROOT / "assets" / "styles" / "ssip_public_dashboard.css"


class VisualFoundationV34140Tests(unittest.TestCase):
    def test_release_version_is_declared(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        self.assertIn('APP_VERSION = "3.4.14.0-visual-foundation"', source)

    def test_named_visual_tokens_and_interaction_rules_exist(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        for token in (
            "--ssip-ink:",
            "--ssip-navy:",
            "--ssip-cobalt:",
            "--ssip-mint:",
            "--ssip-border:",
            "--ssip-shadow-2:",
        ):
            self.assertIn(token, css)
        self.assertIn("font-variant-numeric: tabular-nums", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("touch-action: manipulation", css)
        self.assertIn("@media (max-width: 820px)", css)

    def test_density_pass_reclaims_vertical_space_without_losing_touch_targets(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("--ssip-density-gap:", css)
        self.assertIn("min-height: 230px !important", css)
        self.assertIn("-webkit-line-clamp: 2", css)
        self.assertIn("@media (pointer: coarse)", css)
        self.assertIn("min-height: 44px !important", css)

    def test_catalogue_cards_share_one_grid_system(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("/* v3.4.14.0 shared Home card grid", css)
        self.assertIn(".scheme-results-grid,\n.home-featured-grid,\n.home-call-grid,\n.home-source-grid", css)
        self.assertIn(".home-featured-grid,\n.home-call-grid,\n.home-source-grid", css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr)) !important", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr)) !important", css)
        self.assertIn("grid-template-columns: 1fr !important", css)

    def test_more_navigation_label_is_not_duplicated_by_pseudo_content(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("/* v3.4.14.0 navigation copy calibration", css)
        self.assertIn(".ssip-nav-more > summary::before", css)
        self.assertIn("content: none !important", css)

    def test_visual_foundation_does_not_replace_catalogue_logic(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("presentation layer", css)
        self.assertNotIn("sqlite", css.lower())
        self.assertNotIn("catalogue_snapshot", css.lower())


if __name__ == "__main__":
    unittest.main()
