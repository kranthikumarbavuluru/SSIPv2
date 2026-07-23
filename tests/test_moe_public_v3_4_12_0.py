from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.catalogue_populations import split_catalogue_populations
from ssip_dashboard.metrics import compute_metrics, department_coverage
from ssip_dashboard.moe_public import build_moe_public_bundle, load_active_moe_supplement


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_DIR = ROOT / "data" / "departments" / "moe" / "v3_4_12_0"


class MOEPublicationTests(unittest.TestCase):
    def test_active_snapshot_hash_and_official_sources(self) -> None:
        manifest = json.loads((PUBLICATION_DIR / "active_publication_manifest_v3_4_12_0.json").read_text(encoding="utf-8"))
        payload = (PUBLICATION_DIR / manifest["inventory_file"]).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest["inventory_sha256"])
        rows = list(csv.DictReader(payload.decode("utf-8-sig").splitlines()))
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(row["official_page_url"].startswith("https://") for row in rows))
        self.assertTrue(any(row["scheme_code"] == "AICTE-IDEA" for row in rows))

    def test_public_projection_separates_programmes_current_call_and_history(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        public = build_moe_public_bundle(bundle.records)
        self.assertEqual(len(public.permanent_records), 12)
        self.assertEqual(len(public.current_calls), 1)
        self.assertEqual(len(public.historical_records), 2)
        self.assertEqual(public.current_calls[0].closing_date, "2026-08-15")
        self.assertEqual(public.current_calls[0].application_status, "OPEN")

    def test_funding_cap_is_optional_and_evidence_bound(self) -> None:
        supplement = load_active_moe_supplement(ROOT)
        records = {row["master_id"]: row for row in supplement.records}
        self.assertEqual(records["moe_innovative_startups_utsav"]["funding_maximum"], 1000000)
        self.assertIsNone(records["moe_iic"]["funding_maximum"])

    def test_home_explorer_and_live_calls_share_the_same_catalogue_records(self) -> None:
        bundle = load_catalogue(DashboardConfig.from_env(ROOT))
        populations = split_catalogue_populations(bundle.records)
        metrics = compute_metrics(bundle.records)
        self.assertIn("moe_pmrc_call_2026", {record.master_id for record in populations.application_call_records})
        self.assertTrue(any("Department of Higher Education" in label for label in department_coverage(populations.main_scheme_records)))
        self.assertGreaterEqual(metrics.total_explicit_departments, 1)


class MOERouteTests(unittest.TestCase):
    def test_route_and_navigation_are_wired(self) -> None:
        source = (ROOT / "apps" / "public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        css = (ROOT / "assets" / "styles" / "ssip_public_dashboard.css").read_text(encoding="utf-8")
        self.assertIn('"MoE": "moe-programmes"', source)
        self.assertIn('"MoE": "MoE"', source)
        self.assertIn("def render_moe_page", source)
        self.assertIn("MoE / AICTE Historical Calls", source)
        self.assertIn("ssip-nav-department-moe", css)


if __name__ == "__main__":
    unittest.main()
