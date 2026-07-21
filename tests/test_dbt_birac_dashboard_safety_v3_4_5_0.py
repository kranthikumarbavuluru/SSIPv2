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
    def test_route_navigation_and_seven_views_are_wired(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        self.assertIn('"DBT–BIRAC": "dbt-birac-programmes"', source)
        self.assertIn('elif page == "DBT–BIRAC":', source)
        for label in (
            "Schemes & Programmes", "Current Verified Calls", "Challenges & Competitions",
            "Incubator & Intermediary", "Historical Calls", "Guidelines & Evidence", "Admin Review",
        ):
            self.assertIn(label, source)

    def test_preview_has_accessible_safe_links_and_mobile_breakpoints(self) -> None:
        source = APP.read_text(encoding="utf-8-sig")
        section = source[source.index("def _dbt_birac_preview_card"):source.index("def main()")]
        self.assertIn('target="_blank" rel="noopener noreferrer"', section)
        self.assertIn("@media (max-width:430px)", section)
        self.assertIn("aria-label=\"Governed ownership chain\"", section)
        self.assertNotIn("Apply now", section)

    def test_home_implementation_and_shared_css_match_required_base(self) -> None:
        self.assertEqual(function_hash(APP, "render_home"), "566b5e31336f06a2b0609c3c5f9d35f122650fe030cbcd0d4fd96eae808bb7ca")
        for relative in ("assets/dashboard_theme.css", "ssip_dashboard/assets/styles.css"):
            baseline = subprocess.check_output(["git", "show", f"bdbe13d9ed6048eda33c23a0f3a19dcc7e512bdf:{relative}"], cwd=ROOT)
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), hashlib.sha256(baseline).hexdigest())


if __name__ == "__main__":
    unittest.main()
