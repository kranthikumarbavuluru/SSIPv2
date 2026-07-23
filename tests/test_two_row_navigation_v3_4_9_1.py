from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "public_dashboard_app_v2_9.py"
CSS = ROOT / "assets" / "styles" / "ssip_public_dashboard.css"


class TwoRowNavigationTests(unittest.TestCase):
    def test_header_separates_portal_tools_and_departments(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        header = source[source.index("def site_header"):source.index("def page_intro")]
        self.assertIn('aria-label="Portal navigation"', header)
        self.assertIn('aria-label="Department navigation"', header)
        self.assertIn("ssip-header-nav-stack", header)
        self.assertIn('class="ssip-nav-link ssip-nav-department', header)
        self.assertIn('ssip-nav-more{more_class}', header)

    def test_department_palette_and_responsive_overflow_are_defined(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        for department in ("dst", "meity", "dpiit", "dbt-birac", "msme", "dot", "idex", "msde", "moe"):
            self.assertIn(f".ssip-nav-department-{department}", css)
        self.assertIn(".ssip-primary-nav-departments", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn(":focus-visible", css)


if __name__ == "__main__":
    unittest.main()
