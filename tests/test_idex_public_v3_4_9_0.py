from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.idex_public import build_idex_public_bundle, load_active_idex_supplement


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_DIR = ROOT / "data" / "departments" / "idex" / "v3_4_9_0"


class IDEXPublicationTests(unittest.TestCase):
    def test_active_bundle_is_hash_verified_and_complete(self) -> None:
        manifest = json.loads((PUBLICATION_DIR / "active_publication_manifest_v3_4_9_0.json").read_text(encoding="utf-8"))
        payload = (PUBLICATION_DIR / manifest["inventory_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["inventory_sha256"])
        rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        self.assertEqual(len(rows), 35)
        self.assertTrue(all(row["official_page_url"].startswith("https://idex.gov.in/") for row in rows))

    def test_public_projection_separates_programmes_current_and_history(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        public = build_idex_public_bundle(bundle.records)
        self.assertEqual(len(public.permanent_records), 3)
        self.assertEqual(len(public.current_calls), 1)
        self.assertEqual(len(public.historical_records), 31)
        self.assertEqual(public.current_calls[0].scheme_name, "iDEX Open Challenge")
        self.assertEqual(public.current_calls[0].closing_date, "2026-09-30")
        self.assertTrue(all(row.application_status == "CLOSED" for row in public.historical_records))

    def test_grant_caps_are_preserved_as_evidence_bound_values(self) -> None:
        supplement = load_active_idex_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["idex_scheme"]["funding_maximum"], 15000000)
        self.assertEqual(records["idex_aditi4"]["funding_maximum"], 250000000)
        self.assertEqual(records["idex_open_challenge_2026"]["funding_maximum"], 15000000)


class IDEXDashboardRouteTests(unittest.TestCase):
    def test_route_and_governance_copy_are_wired(self) -> None:
        source = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8")
        self.assertIn('"iDEX": "idex-programmes"', source)
        self.assertIn("def render_idex_page", source)
        self.assertIn("iDEX Schemes, Programmes, Calls & Archive", source)
        self.assertIn('metric_card("Schemes & programmes"', source)
        self.assertIn('iDEX scheme(s) and programme(s)', source)
        self.assertIn("Current Calls & Challenges", source)
        self.assertIn("iDEX ownership and status governance", source)
        self.assertIn("idex_initial_governed_public_20260722", (PUBLICATION_DIR / "active_publication_manifest_v3_4_9_0.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
