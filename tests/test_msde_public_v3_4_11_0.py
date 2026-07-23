from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.msde_public import build_msde_public_bundle, load_active_msde_supplement


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_DIR = ROOT / "data" / "departments" / "msde" / "v3_4_11_0"


class MSDEPublicationTests(unittest.TestCase):
    def test_active_snapshot_hash_and_official_sources(self) -> None:
        manifest = json.loads((PUBLICATION_DIR / "active_publication_manifest_v3_4_11_0.json").read_text(encoding="utf-8"))
        payload = (PUBLICATION_DIR / manifest["inventory_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["inventory_sha256"])
        rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        self.assertEqual(len(rows), 25)
        self.assertTrue(all(row["official_page_url"].startswith("https://www.msde.gov.in/") for row in rows))
        self.assertTrue(any(row["canonical_name"].startswith("Pradhan Mantri Kaushal Vikas Yojana 4.0") for row in rows))

    def test_public_projection_separates_msde_schemes_and_history(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        public = build_msde_public_bundle(bundle.records)
        self.assertEqual(len(public.permanent_records), 22)
        self.assertEqual(len(public.current_calls), 0)
        self.assertEqual(len(public.historical_records), 3)
        self.assertTrue(any(row.scheme_name.startswith("Pradhan Mantri Kaushal Vikas Yojana 3.0") for row in public.historical_records))

    def test_verified_funding_is_optional_and_evidence_bound(self) -> None:
        supplement = load_active_msde_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["msde_pmkk"]["funding_maximum"], 7000000)
        self.assertIsNone(records["msde_pmkvy_4"]["funding_maximum"])

    def test_closed_comment_window_is_historical_not_current(self) -> None:
        supplement = load_active_msde_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["msde_coe_vtc_comments_2026"]["application_status"], "CLOSED")
        self.assertEqual(records["msde_coe_vtc_comments_2026"]["closing_date"], "2026-06-28")


class MSDERouteTests(unittest.TestCase):
    def test_route_and_navigation_are_wired(self) -> None:
        source = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        css = (ROOT / "assets" / "styles" / "ssip_public_dashboard.css").read_text(encoding="utf-8")
        self.assertIn('"MSDE": "msde-programmes"', source)
        self.assertIn('"MSDE": "MSDE"', source)
        self.assertIn("def render_msde_page", source)
        self.assertIn("MSDE Historical Calls & Cycles", source)
        self.assertIn("ssip-nav-department-msde", css)


if __name__ == "__main__":
    unittest.main()
