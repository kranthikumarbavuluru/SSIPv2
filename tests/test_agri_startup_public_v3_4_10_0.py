from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest

from ssip_dashboard.agri_startup_public import build_agri_startup_public_bundle, load_active_agri_startup_supplement
from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_DIR = ROOT / "data" / "departments" / "agri_startup" / "v3_4_10_0"


class AgriStartupPublicationTests(unittest.TestCase):
    def test_active_snapshot_hash_and_official_sources(self) -> None:
        manifest = json.loads((PUBLICATION_DIR / "active_publication_manifest_v3_4_10_0.json").read_text(encoding="utf-8"))
        payload = (PUBLICATION_DIR / manifest["inventory_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["inventory_sha256"])
        rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        self.assertEqual(len(rows), 37)
        self.assertTrue(all(row["official_page_url"].startswith("https://") for row in rows))
        self.assertFalse(any(row["record_kind"] == "INCUBATOR" for row in rows))
        audit = json.loads((PUBLICATION_DIR / manifest["audit_file"]).read_text(encoding="utf-8"))
        self.assertEqual(audit["source_coverage"]["enabled_official_sources"], 42)
        self.assertEqual(audit["published_projection"]["current_calls_with_official_deadlines"], 4)

    def test_public_projection_separates_startup_programmes_and_history(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        public = build_agri_startup_public_bundle(bundle.records)
        self.assertEqual(len(public.permanent_records), 21)
        self.assertEqual(len(public.current_calls), 4)
        self.assertEqual(len(public.historical_records), 12)
        self.assertEqual(public.current_calls[0].application_status, "OPEN")
        self.assertTrue(any(row.closing_date == "2026-08-16" for row in public.current_calls))

    def test_funding_caps_are_optional_and_evidence_bound(self) -> None:
        supplement = load_active_agri_startup_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["agri_agrisure"]["funding_maximum"], 250000000)
        self.assertEqual(records["agri_rkvy_rabi"]["funding_maximum"], 500000)
        self.assertIsNone(records["agri_sfac_vca"]["funding_maximum"])

    def test_current_calls_keep_official_deadlines_and_registration_links(self) -> None:
        supplement = load_active_agri_startup_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["agri_manage_pau_connect_2026"]["closing_date"], "2026-08-16")
        self.assertTrue(records["agri_manage_pau_connect_2026"]["application_url"].startswith("https://forms.gle/"))
        self.assertEqual(records["agri_apeda_bharati"]["application_status"], "STATUS_UNVERIFIED")
        self.assertEqual(records["agri_apeda_bharati_2025"]["application_status"], "CLOSED")
        self.assertEqual(records["agri_angrau_agriinvo_2025"]["closing_date"], "2026-01-17")
        self.assertEqual(records["agri_angrau_meristems_2025"]["funding_maximum"], 400000)
        self.assertEqual(records["agri_manage_cohort15_saip_2026"]["closing_date"], "2026-04-15")
        self.assertEqual(records["agri_manage_agri_eureka_2024"]["closing_date"], "2024-06-25")
        self.assertEqual(records["agri_pdkv_agritech_hackathon_2026"]["closing_date"], "2026-06-24")
        self.assertEqual(records["agri_manage_digital_marketing_2026"]["closing_date"], "2026-08-20")
        self.assertTrue(records["agri_manage_digital_marketing_2026"]["application_url"].startswith("https://forms.gle/"))
        self.assertEqual(records["agri_afbic_iitkgp_aop"]["funding_maximum"], 500000)


class AgriStartupDashboardRouteTests(unittest.TestCase):
    def test_route_and_governance_copy_are_wired(self) -> None:
        source = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8")
        self.assertIn('"Agriculture": "agri-startups"', source)
        self.assertIn("def render_agri_startup_page", source)
        self.assertIn("Agri-Startup Historical Innovation Calls", source)
        self.assertIn("General farmer-benefit schemes are excluded", source)
        self.assertIn("Incubator directories are discovery sources only", source)


if __name__ == "__main__":
    unittest.main()
