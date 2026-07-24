from __future__ import annotations

import ast
from pathlib import Path
import unittest

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps/public_dashboard_app_v2_9.py"


class MediaRunsPublicDashboardTests(unittest.TestCase):
    def test_media_records_are_governed_catalogue_records(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        media = [record for record in bundle.records if record.master_id.startswith("media_")]
        self.assertEqual({record.scheme_name for record in media}, {
            "Ignition Grant - iNurture Foundation / ABES EC",
            "RTIH MedTech Catalyst Program",
        })

    def test_home_prioritises_media_calls_and_more_route_is_wired(self) -> None:
        tree = ast.parse(APP.read_text(encoding="utf-8-sig"))
        source = APP.read_text(encoding="utf-8-sig")
        render_home = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "render_home")
        render_home_source = ast.get_source_segment(source, render_home) or ""
        self.assertIn('media_calls = [item for item in current_calls if is_media_derived_record(item)]', render_home_source)
        self.assertIn('current_calls = (media_calls + other_calls)[:6]', render_home_source)
        self.assertIn('"Media Runs": "media-runs"', source)
        self.assertIn('f\'<a target="_top" href="?page={PAGE_SLUGS["Media Runs"]}">Media runs</a>\'', source)


if __name__ == "__main__":
    unittest.main()
