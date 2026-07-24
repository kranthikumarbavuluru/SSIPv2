from __future__ import annotations

from pathlib import Path
import unittest

from ssip_dashboard.catalogue import load_catalogue
from ssip_dashboard.config import DashboardConfig
from ssip_dashboard.dot_public import (
    build_dot_public_bundle,
    is_official_dot_url,
    load_active_dot_supplement,
)


ROOT = Path(__file__).resolve().parents[1]


class DOTPublicationTests(unittest.TestCase):
    def test_active_bundle_is_hash_verified_and_complete(self) -> None:
        supplement = load_active_dot_supplement(ROOT)
        self.assertEqual(supplement.manifest["activation_status"], "ACTIVE")
        self.assertEqual(supplement.manifest["record_count"], 11)
        self.assertEqual(len(supplement.records), 11)
        self.assertEqual(len({row["master_id"] for row in supplement.records}), 11)
        self.assertTrue(all(is_official_dot_url(row["official_page_url"]) for row in supplement.records))

    def test_public_projection_separates_permanent_current_and_history(self) -> None:
        catalogue = load_catalogue(DashboardConfig.from_env(ROOT))
        bundle = build_dot_public_bundle(catalogue.records)
        self.assertEqual(len(bundle.permanent_records), 4)
        self.assertEqual(len(bundle.current_calls), 0)
        self.assertEqual(len(bundle.historical_records), 7)
        self.assertTrue(all(row.application_status == "CLOSED" for row in bundle.historical_records))
        self.assertTrue(all(row.current_location == "DOT_ACTIVE_PUBLICATION" for row in bundle.public_records))

    def test_structured_support_amounts_are_evidence_bound(self) -> None:
        catalogue = load_catalogue(DashboardConfig.from_env(ROOT))
        bundle = build_dot_public_bundle(catalogue.records)
        reimbursement = next(row for row in bundle.permanent_records if row.master_id == "dot_testing_reimbursement")
        self.assertEqual(reimbursement.funding_maximum, 5_000_000)
        hackathon = next(row for row in bundle.historical_records if row.master_id == "dot_dcis_hackathon")
        self.assertEqual(hackathon.funding_maximum, 100_000)


class DOTDashboardRouteTests(unittest.TestCase):
    def test_route_and_governance_copy_are_wired(self) -> None:
        source = (ROOT / "apps/public_dashboard_app_v2_9.py").read_text(encoding="utf-8-sig")
        self.assertIn('"DoT": "dot-programmes"', source)
        self.assertIn('elif page == "DoT":', source)
        self.assertIn("def render_dot_page", source)
        self.assertIn('"Schemes & Programmes", "Current Calls & Challenges", "Historical Archive"', source)
        self.assertIn("No current DoT call is published", source)
        self.assertIn("Department of Telecommunications (DoT)", source)


if __name__ == "__main__":
    unittest.main()
