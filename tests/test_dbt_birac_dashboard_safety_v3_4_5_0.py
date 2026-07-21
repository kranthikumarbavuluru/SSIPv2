from __future__ import annotations

import ast
import hashlib
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/public_dashboard_app_v2_9.py"


def function_hash(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


class DBTBIRACDashboardSafetyTests(unittest.TestCase):
    def test_route_top_level_navigation_and_three_public_views_are_wired(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        self.assertIn('"DBT–BIRAC": "dbt-birac-programmes"', source)
        self.assertIn('elif page == "DBT–BIRAC":', source)
        header = source[source.index("def site_header"):source.index("def page_intro")]
        primary = header[header.index("primary_pages"):header.index("links = []")]
        self.assertIn('"DBT–BIRAC"', primary)
        self.assertNotIn('"Directory"', primary)
        self.assertNotIn('"Official Sources"', primary)
        self.assertIn('>Resources</a>', header)
        self.assertIn('>Sources</a>', header)
        section = source[source.index("def render_dbt_birac_page"):source.index("def main()")]
        for label in ("Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"):
            self.assertIn(label, section)
        for removed_label in ("Challenges & Competitions", "Incubator & Intermediary", "Guidelines & Evidence"):
            self.assertNotIn(removed_label, section)
        self.assertNotIn("Admin Review", section)
        self.assertNotIn("Preview · Not published", section)

    def test_dbt_documents_are_available_from_shared_resources(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        section = source[source.index("def render_resources"):source.index("def _dst_preview_notice")]
        self.assertIn("cached_dbt_birac_preview().documents", section)
        self.assertIn('"DOCUMENT":"Documents"', section)
        self.assertIn("Department of Biotechnology / BIRAC", section)
        self.assertIn('rel="noopener noreferrer"', section)

    def test_public_page_has_accessible_safe_links_and_governed_ownership(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        section = source[source.index("def _dbt_birac_preview_card"):source.index("def main()")]
        self.assertIn('target="_blank" rel="noopener noreferrer"', section)
        self.assertIn("Verified ownership", section)
        self.assertIn("Search DBT–BIRAC schemes", section)
        self.assertNotIn("Apply now", section)

    def test_home_implementation_and_shared_css_match_required_base(self) -> None:
        self.assertEqual(function_hash(APP, "render_home"), "566b5e31336f06a2b0609c3c5f9d35f122650fe030cbcd0d4fd96eae808bb7ca")
        for relative in ("assets/dashboard_theme.css", "ssip_dashboard/assets/styles.css"):
            baseline = subprocess.check_output(["git", "show", f"bdbe13d9ed6048eda33c23a0f3a19dcc7e512bdf:{relative}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), hashlib.sha256(baseline).hexdigest())


if __name__ == "__main__":
    unittest.main()
